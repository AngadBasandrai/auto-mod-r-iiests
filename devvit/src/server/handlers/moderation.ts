// Two secondary paths.
//
// onCommentCreate  — someone replying `!badbot` under one of the bot's comments
//                    makes it delete that comment. This is the escape hatch that
//                    lets the subreddit correct the bot without a moderator.
// onMention        — someone summoning the bot with u/iiests-faq-bot in a
//                    comment gets an answer to the thread's question, subject to
//                    exactly the same confidence gate as a new post.

import { reddit } from '@devvit/web/server';
import type { OnCommentCreateRequest, OnMentionInCommentCreateRequest } from '@devvit/web/shared';

import { generate, renderComment, shouldPost } from '../answer.js';
import { BOT } from '../config.js';
import * as settings from '../settings.js';
import * as state from '../state.js';

function isRemovalRequest(body: string): boolean {
  const text = body.toLowerCase();
  return BOT.removalTriggers.some((trigger) => text.includes(trigger));
}

export async function onCommentCreate(payload: OnCommentCreateRequest): Promise<unknown> {
  const comment = payload.comment;
  if (!comment?.body || !comment.parentId) return { status: 'skipped' };
  if (!isRemovalRequest(comment.body)) return { status: 'skipped', reason: 'not a removal' };

  // The parent must be a comment this app posted. Redis is the fast path; if it
  // has expired we ask Reddit, because a false negative here means the bot
  // ignores a legitimate !badbot.
  const parentId = comment.parentId;
  if (!parentId.startsWith('t1_')) return { status: 'skipped', reason: 'parent is not a comment' };

  if (!(await state.isOwnComment(parentId))) {
    try {
      const parent = await reddit.getCommentById(parentId as `t1_${string}`);
      const me = await reddit.getAppUser();
      // No app user means we cannot prove the comment is ours, and deleting
      // someone else's comment is far worse than ignoring a !badbot.
      if (!me?.username || parent.authorName !== me.username) {
        return { status: 'skipped', reason: 'parent is not ours' };
      }
    } catch (error) {
      console.warn(`Could not verify parent ${parentId}: ${String(error)}`);
      return { status: 'skipped', reason: 'could not verify ownership' };
    }
  }

  try {
    const parent = await reddit.getCommentById(parentId as `t1_${string}`);
    await parent.delete();
    console.log(`Deleted ${parentId} after "${comment.body.trim().slice(0, 60)}"`);
    return { status: 'deleted', commentId: parentId };
  } catch (error) {
    console.error(`Could not delete ${parentId}: ${String(error)}`);
    return { status: 'error', message: String(error) };
  }
}

export async function onMention(payload: OnMentionInCommentCreateRequest): Promise<unknown> {
  const comment = payload.comment;
  const post = payload.post;
  if (!comment?.id || !comment.body) return { status: 'skipped', reason: 'no comment' };

  const config = await settings.load();

  // The mention itself is usually "u/iiests-faq-bot what about X?". Strip the
  // summons and fall back to the post title when nothing else is said.
  const stripped = comment.body.replace(/\bu\/[A-Za-z0-9_-]+/g, '').trim();
  const question =
    stripped.length >= 15 ? stripped : `${post?.title ?? ''}\n\n${post?.selftext ?? ''}`.trim();

  if (question.length < 15) return { status: 'skipped', reason: 'nothing to answer' };

  if (await state.alreadyAnswered(comment.id)) {
    return { status: 'skipped', reason: 'already answered' };
  }
  if (!(await state.reserveReplySlot(config.maxRepliesPerHour))) {
    return { status: 'skipped', reason: 'hourly cap reached' };
  }

  const answer = await generate(question, config.minConfidence);

  if (!shouldPost(answer)) {
    console.log(`Staying quiet on mention ${comment.id}: ${answer.reason}`);
    return { status: 'silent', reason: answer.reason };
  }

  const body = renderComment(answer);

  if (config.dryRun) {
    console.log(
      `DRY RUN — would reply to mention ${comment.id}\n${'-'.repeat(60)}\n${body}\n${'-'.repeat(60)}`
    );
    return { status: 'dry-run' };
  }

  const reply = await reddit.submitComment({
    id: comment.id as `t1_${string}`,
    text: body,
    runAs: 'APP',
  });

  await state.markAnswered(comment.id, reply.id);
  await state.markOwnComment(reply.id);
  return { status: 'posted', commentId: reply.id };
}
