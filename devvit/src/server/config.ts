// The tuning knobs that live in config.yaml on the Python side. Anything an
// installing moderator should be able to change is a subreddit setting in
// devvit.json instead; this file holds the rest.

export const MODELS = {
  /** Query normalization and reranking — cheap and fast. */
  fast: 'gemini-3.5-flash-lite',
  /**
   * The user-facing answer. Not the newest Flash: gemini-3.8-flash ran out of
   * free-tier quota within the first few replies, and a bot that goes quiet
   * mid-afternoon is worse than one that writes slightly less well.
   */
  strong: 'gemini-3.5-flash',
  /** Used when `strong` is rate limited. Flash-Lite has its own, larger quota. */
  strongFallback: 'gemini-3.5-flash-lite',
} as const;

export const RETRIEVAL = {
  bm25TopK: 30,
  rrfK: 60,
  rerankCandidates: 12,
  finalK: 5,
} as const;

export const ANSWER = {
  /** ...and at least this many records must support the answer. */
  minSupporting: 2,
  maxAnswerChars: 1800,
  /** One curated entry that nails the question is enough on its own. */
  trustedSources: new Set(['reddit_wiki', 'reddit_pinned', 'student_wiki']),
  trustedSoloScore: 0.9,
  footer:
    "\n\n---\n^(I'm a bot answering from the r/iiests FAQ and community knowledge. " +
    'I can be wrong — check with a human for anything important.)\n',
} as const;

export const LEARN = {
  /** Threads are read once, after this long, so votes and corrections are in. */
  minThreadAgeHours: 24,
  /** Older threads are left alone; the bundled corpus already covers the past. */
  maxThreadAgeDays: 14,
  /** Only comments at this score or above are read. 1 is the author's own vote. */
  minCommentScore: 2,
  /** A learned record must clear this model confidence to be kept. */
  minConfidence: 0.7,
  /** Each scheduled run reads this many threads, within the 30 second budget. */
  threadsPerRun: 4,
  /** Learning stops here, so a bad month cannot swamp the curated corpus. */
  maxRecords: 3000,
} as const;

export const BOT = {
  triggerFlairs: ['Ask', 'Question', 'Admissions', 'Doubt'],
  /** From the subreddit owner, a comment containing any of these deletes the bot's reply. */
  removalTriggers: ['!badbot', '!delete', 'bad bot'],
  /** A reply this heavily downvoted is removed too. */
  removeBelowScore: -3,
  /** How many of the newest posts get a reply when a new version is installed. */
  catchUpPosts: 4,
} as const;
