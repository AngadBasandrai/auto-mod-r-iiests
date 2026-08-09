// Per-subreddit settings, read fresh on every trigger so a moderator can turn
// the bot off without waiting for a redeploy.
//
// Every default here is the cautious one. A missing or malformed setting must
// never make the bot post more than the moderator asked for, so `dryRun`
// defaults to true and the numeric limits fall back to the tightest value.

import { settings } from '@devvit/web/server';

export interface BotSettings {
  dryRun: boolean;
  autoReplyUnflaired: boolean;
  minConfidence: number;
  maxRepliesPerHour: number;
  maxPostAgeMinutes: number;
}

const DEFAULTS: BotSettings = {
  dryRun: true,
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
