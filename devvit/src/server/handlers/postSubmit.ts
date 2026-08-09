// The main path: a new post arrives, and the bot decides whether it has
// anything worth saying.
//
// The gates fire in this order and every one of them defaults to staying quiet:
//   1. flair filter          — unless the moderator opted into unflaired posts
//   2. post age              — a replayed or delayed trigger can't wake old threads
//   3. duplicate check       — Redis, fails closed
//   4. hourly cap            — reserved before any model call, so a burst of
//                              posts can't each spend tokens on the way to being
//                              rejected
//   5. retrieval confidence  — reranked top score plus corroboration
//   6. the model's own "answerable" flag
//   7. dry run               — logs the exact comment, posts nothing

import { reddit } from '@devvit/web/server';
import type { OnPostSubmitRequest } from '@devvit/web/shared';

import { generate, renderComment, shouldPost } from '../answer.js';
import { BOT } from '../config.js';
import * as settings from '../settings.js';
import * as state from '../state.js';

export async function onPostSubmit(payload: OnPostSubmitRequest): Promise<unknown> {
  const post = payload.post;
  if (!post?.id) return { status: 'skipped', reason: 'no post in payload' };

  const config = await settings.load();

  const flair = post.linkFlair?.text?.trim() ?? '';
  if (!flair && !config.autoReplyUnflaired) {
    return { status: 'skipped', reason: 'unflaired' };
  }
  if (flair && !BOT.triggerFlairs.some((f) => f.toLowerCase() === flair.toLowerCase())) {
    return { status: 'skipped', reason: `flair '${flair}' is not a trigger` };
  }

  // createdAt is milliseconds since the epoch.
  const ageMinutes = (Date.now() - post.createdAt) / 60_000;
  if (ageMinutes > config.maxPostAgeMinutes) {
    return { status: 'skipped', reason: `post is ${Math.round(ageMinutes)} minutes old` };
  }

  if (await state.alreadyAnswered(post.id)) {
    return { status: 'skipped', reason: 'already answered' };
  }

  const question = `${post.title}\n\n${post.selftext ?? ''}`.trim();
  if (question.length < 15) return { status: 'skipped', reason: 'nothing to answer' };

  // Reserved before the model calls: an over-cap post should cost nothing.
  if (!(await state.reserveReplySlot(config.maxRepliesPerHour))) {
    return { status: 'skipped', reason: 'hourly cap reached' };
  }

  const answer = await generate(question, config.minConfidence);

  if (!shouldPost(answer)) {
    console.log(
      `Staying quiet on ${post.id}: ${answer.reason} ` +
        `(top ${answer.topScore.toFixed(2)}, ${answer.supporting} supporting)`
    );
    return { status: 'silent', reason: answer.reason, topScore: answer.topScore };
  }

  const body = renderComment(answer);

  if (config.dryRun) {
    console.log(
      `DRY RUN — would reply to ${post.id} "${post.title}"\n` +
        `top ${answer.topScore.toFixed(2)}, ${answer.supporting} supporting\n` +
        `${'-'.repeat(60)}\n${body}\n${'-'.repeat(60)}`
    );
    return { status: 'dry-run', topScore: answer.topScore };
  }

  const comment = await reddit.submitComment({
    id: post.id as `t3_${string}`,
    text: body,
    runAs: 'APP',
  });

  await state.markAnswered(post.id, comment.id);
  await state.markOwnComment(comment.id);
  console.log(`Replied to ${post.id} with ${comment.id} (top ${answer.topScore.toFixed(2)})`);

  return { status: 'posted', commentId: comment.id, topScore: answer.topScore };
}
