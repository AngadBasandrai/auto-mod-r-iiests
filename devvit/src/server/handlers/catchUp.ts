// Catch-up: when a version is installed, reply to the newest few posts.
//
// onPostSubmit only fires for posts made after the app is installed, so a fresh
// install would sit silent under a front page of threads it never saw. This
// runs once per installed version and gives the newest posts the same treatment
// a new post gets.
//
// Two of the postSubmit gates are deliberately absent. The post-age cutoff
// exists to stop a replayed trigger waking an old thread, and here waking recent
// threads is the whole point. The hourly cap is skipped because the batch is
// bounded by BOT.catchUpPosts already. The duplicate check and dry run stay.

import { reddit, redis } from '@devvit/web/server';
import type { OnAppInstallRequest, OnAppUpgradeRequest } from '@devvit/web/shared';

import { renderComment, respond, shouldPost } from '../answer.js';
import { BOT } from '../config.js';
import * as settings from '../settings.js';
import * as state from '../state.js';

// Bump this to make the next upgrade run the catch-up again. Without it every
// upgrade would work its way further down the listing, replying to posts the
// bot had already chosen to leave alone.
const RUN_KEY = 'catchup:v1';

async function replyTo(
  post: { id: string; title: string; body?: string | undefined },
  config: settings.BotSettings
): Promise<string> {
  if (await state.alreadyAnswered(post.id)) return 'already answered';

  const question = `${post.title}\n\n${post.body ?? ''}`.trim();
  if (question.length < 3) return 'nothing to answer';

  const answer = await respond(question, config.minConfidence, config.replyToEverything);
  if (!shouldPost(answer)) return `silent: ${answer.reason}`;

  const body = renderComment(answer);
  if (config.dryRun) {
    console.log(
      `DRY RUN — catch-up would reply to ${post.id} "${post.title}"\n` +
        `${'-'.repeat(60)}\n${body}\n${'-'.repeat(60)}`
    );
    return 'dry-run';
  }

  const comment = await reddit.submitComment({
    id: post.id as `t3_${string}`,
    text: body,
    runAs: 'APP',
  });
  await state.markAnswered(post.id, comment.id);
  await state.markOwnComment(comment.id);
  return `posted ${comment.id} (${answer.kind})`;
}

export async function onAppInstalled(
  payload: OnAppInstallRequest | OnAppUpgradeRequest
): Promise<unknown> {
  const subredditName = payload.subreddit?.name;
  if (!subredditName) return { status: 'skipped', reason: 'no subreddit in payload' };

  // Claimed before any work, so a retried trigger cannot post a second batch.
  if ((await redis.get(RUN_KEY)) !== undefined) {
    return { status: 'skipped', reason: 'catch-up already ran' };
  }
  await redis.set(RUN_KEY, new Date().toISOString());

  const config = await settings.load();
  const me = await reddit.getAppUser().catch(() => undefined);

  const posts = await reddit.getNewPosts({ subredditName, limit: BOT.catchUpPosts }).all();
  const candidates = posts.filter(
    (post) => !post.removed && !post.locked && post.authorName !== me?.username
  );

  // In parallel: a trigger has a 30 second budget and each post is three or
  // four model calls.
  const outcomes = await Promise.all(
    candidates.map(async (post) => {
      try {
        return `${post.id}: ${await replyTo(post, config)}`;
      } catch (error) {
        return `${post.id}: error ${String(error)}`;
      }
    })
  );

  console.log(`Catch-up on r/${subredditName}:\n${outcomes.join('\n')}`);
  return { status: 'done', outcomes };
}
