// Duplicate suppression and rate caps, backed by Devvit's Redis.
//
// Replaces data/state/seen.json and the GitHub Actions commit dance the Python
// bot used to persist it. Redis is per-installation, so each subreddit that
// installs the app gets its own counters.
//
// Every helper here fails CLOSED: if Redis is unreachable we report "already
// answered" and "over the cap", because double-posting is the failure that
// actually embarrasses you.

import { redis } from '@devvit/web/server';

const ANSWERED_TTL_SECONDS = 60 * 60 * 24 * 30; // 30 days

const answeredKey = (postId: string): string => `answered:${postId}`;
const hourKey = (hourStamp: number): string => `replies:${hourStamp}`;

/** Has the bot already answered this post? Assumes yes if Redis is down. */
export async function alreadyAnswered(postId: string): Promise<boolean> {
  try {
    return (await redis.get(answeredKey(postId))) !== undefined;
  } catch (error) {
    console.error(`Redis read failed for ${postId}, assuming answered: ${String(error)}`);
    return true;
  }
}

/** Record that the bot answered this post. */
export async function markAnswered(postId: string, commentId: string): Promise<void> {
  try {
    await redis.set(answeredKey(postId), commentId, { expiration: expiryFromNow() });
  } catch (error) {
    console.error(`Redis write failed for ${postId}: ${String(error)}`);
  }
}

function expiryFromNow(): Date {
  return new Date(Date.now() + ANSWERED_TTL_SECONDS * 1000);
}

/**
 * Reserve a reply slot for the current hour.
 *
 * Increments first and compares afterwards, so two triggers firing at once
 * cannot both see "7 of 8" and both post. An over-limit increment is not rolled
 * back — treating a rejected attempt as spent is the safe direction.
 */
export async function reserveReplySlot(maxPerHour: number): Promise<boolean> {
  const key = hourKey(Math.floor(Date.now() / 3_600_000));
  try {
    const count = await redis.incrBy(key, 1);
    // Two hours, so the window that is still being read is never evicted early.
    await redis.expire(key, 7200);
    if (count > maxPerHour) {
      console.log(`Hourly reply cap reached (${count - 1}/${maxPerHour})`);
      return false;
    }
    return true;
  } catch (error) {
    console.error(`Redis counter failed, refusing to reply: ${String(error)}`);
    return false;
  }
}

/** Remember a comment the bot posted, so !badbot can verify ownership cheaply. */
export async function markOwnComment(commentId: string): Promise<void> {
  try {
    await redis.set(`own:${commentId}`, '1', { expiration: expiryFromNow() });
  } catch (error) {
    console.error(`Redis write failed for comment ${commentId}: ${String(error)}`);
  }
}

export async function isOwnComment(commentId: string): Promise<boolean> {
  try {
    return (await redis.get(`own:${commentId}`)) !== undefined;
  } catch {
    return false;
  }
}
