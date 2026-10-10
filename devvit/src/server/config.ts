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
  /** Under a reply that did not come from the FAQ, so it must not claim to. */
  banterFooter:
    "\n\n---\n^(I'm a bot, and this one isn't from the r/iiests FAQ. " +
    'Anything above that sounds like a fact may be made up — check with a human.)\n',
  /** Fixed in code, not left to the model, so a made-up answer is always labelled as one. */
  hallucinationHeader: "I don't know  \nbut being an LLM  \nI can hallucinate:\n\n",
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
