// The tuning knobs that live in config.yaml on the Python side. Anything an
// installing moderator should be able to change is a subreddit setting in
// devvit.json instead; this file holds the rest.

export const MODELS = {
  /** Query normalization and reranking — cheap and fast. */
  fast: 'gemini-3.5-flash-lite',
  /** The user-facing answer. Handles Hindi/Hinglish generation noticeably better. */
  strong: 'gemini-3.8-flash',
  /** Used when `strong` is rate limited. */
  strongFallback: 'gemini-3.5-flash',
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
    'I can be wrong — check with a human for anything important. Reply `!badbot` to ' +
    'remove this comment.)\n',
} as const;

export const BOT = {
  triggerFlairs: ['Ask', 'Question', 'Admissions', 'Doubt'],
  /** Comment bodies containing any of these delete the bot's reply. */
  removalTriggers: ['!badbot', '!delete', 'bad bot'],
  /** A reply this heavily downvoted is removed too. */
  removeBelowScore: -3,
} as const;
