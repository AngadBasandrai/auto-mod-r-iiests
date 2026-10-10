// Per-subreddit settings, read fresh on every trigger so a moderator can turn
// the bot off without waiting for a redeploy.
//
// A missing or malformed setting must never make the bot post when the
// moderator asked it not to, so `dryRun` defaults to true and the numeric
// limits fall back to the tightest value. `replyToEverything` is the one
// setting that defaults to the talkative side: the subreddit asked for a bot
// that joins in, and dry run and the hourly cap still bound it.

import { settings } from '@devvit/web/server';

export interface BotSettings {
  dryRun: boolean;
  replyToEverything: boolean;
  autoReplyUnflaired: boolean;
  minConfidence: number;
  maxRepliesPerHour: number;
  maxPostAgeMinutes: number;
}

const DEFAULTS: BotSettings = {
  dryRun: true,
  replyToEverything: true,
  autoReplyUnflaired: false,
  minConfidence: 0.7,
  maxRepliesPerHour: 8,
  maxPostAgeMinutes: 120,
};

function num(value: unknown, fallback: number, min: number, max: number): number {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.max(min, Math.min(max, parsed));
}

export async function load(): Promise<BotSettings> {
  try {
    const all = await settings.getAll<Partial<Record<keyof BotSettings, unknown>>>();
    return {
      // Only an explicit false disables the dry run. Anything else — missing,
      // null, a string — stays safe.
      dryRun: all.dryRun !== false,
      replyToEverything: all.replyToEverything !== false,
      autoReplyUnflaired: all.autoReplyUnflaired === true,
      minConfidence: num(all.minConfidence, DEFAULTS.minConfidence, 0, 1),
      maxRepliesPerHour: num(all.maxRepliesPerHour, DEFAULTS.maxRepliesPerHour, 0, 100),
      maxPostAgeMinutes: num(all.maxPostAgeMinutes, DEFAULTS.maxPostAgeMinutes, 0, 10_080),
    };
  } catch (error) {
    console.error(`Could not read settings, using safe defaults: ${String(error)}`);
    return { ...DEFAULTS };
  }
}
