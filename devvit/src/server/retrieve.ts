// Retrieval, ported from src/automod/retrieve.py.
//
// ONE DELIBERATE DIFFERENCE FROM THE PYTHON BOT.
//
// The Python pipeline is hybrid: BM25 plus dense vectors, fused with RRF. Dense
// retrieval cannot come along here — it needs fastembed/ONNX to embed the query
// at request time, and Devvit runs a JS sandbox with no native modules, while
// Groq has no embeddings endpoint to offload it to.
//
// So this is lexical only, and the loss is covered from two directions:
//   * the normalizer is asked for more aggressive spelling and transliteration
//     variants than the Python one, and every variant is searched;
//   * the LLM rerank, which was always the real precision gate, is unchanged.
//
// What genuinely degrades is pure paraphrase with no shared vocabulary — a
// question whose every content word differs from the record that answers it.
// The rerank cannot rescue those because they never reach the shortlist. If
// that shows up in practice, the fix is an embeddings provider added to the
// http allowlist, not more prompt work.

import { RETRIEVAL, ANSWER } from './config.js';
import { bm25, records, type QaRecord } from './corpus.js';
import { chatJson } from './groq.js';
import type { NormalizedQuery } from './lang.js';

export interface Hit {
  record: QaRecord;
  score: number;
  rank: number;
}

const RERANK_SYSTEM = `You score how well each candidate FAQ entry answers a student's question
about IIEST Shibpur.

Return JSON: {"scores": [{"id": <candidate id>, "score": 0.0-1.0}]}

Scoring guide:
- 1.0  directly and completely answers the question
- 0.7  answers the main part, or answers it for a closely related case
- 0.4  same topic, does not actually answer what was asked
- 0.0  unrelated, or only superficially shares words

Sharing a proper noun is not relevance. "Is IIEST a NIT?" scores 0.0 against
"What is IIEST-Chan?" -- both say IIEST and that is the only thing they have in
common. Ask yourself whether somebody reading this candidate would have their
actual question answered. If not, it is 0.0, however familiar the words look.

Be strict, and use the whole range -- if you are giving everything 0.7 you are
not discriminating. A wrong answer posted publicly is worse than no answer.
Score every candidate. Do not invent candidates.`;

/** Reciprocal Rank Fusion — combines rankings without needing comparable scores. */
function rrfFuse(rankedLists: [number, number][][], k: number): Map<number, number> {
  const fused = new Map<number, number>();
  for (const ranked of rankedLists) {
    ranked.forEach(([docId], position) => {
      fused.set(docId, (fused.get(docId) ?? 0) + 1 / (k + position + 1));
    });
  }
  return fused;
}

interface RerankResponse {
  scores?: { id?: unknown; score?: unknown }[];
}

/** LLM relevance scores in [0,1], keyed by record id. */
async function rerank(query: string, candidates: QaRecord[]): Promise<Map<number, number>> {
  const scores = new Map<number, number>();
  if (candidates.length === 0) return scores;

  const listing = candidates
    .map((c) => `[${c.id}] Q: ${c.question}\nA: ${c.answer.slice(0, 600)}`)
    .join('\n\n');

  const data = await chatJson<RerankResponse>(
    RERANK_SYSTEM,
    `Student's question:\n${query}\n\nCandidates:\n${listing}`,
    {},
    { kind: 'fast', maxTokens: 1024 }
  );

  for (const item of data.scores ?? []) {
    const id = Number(item.id);
    const score = Number(item.score);
    if (!Number.isFinite(id) || !Number.isFinite(score)) continue;
    scores.set(id, Math.max(0, Math.min(1, score)));
  }
  return scores;
}

/** Return the best records for `query`, most relevant first. */
export async function search(
  query: string,
  normalized: NormalizedQuery
): Promise<Hit[]> {
  const index = bm25();

  // Search the original wording and the normalized English separately: the
  // first catches Hinglish spellings in the corpus, the second the English
  // phrasing. Keyword variants get their own list so a single good alternate
  // spelling can pull a record into the shortlist on its own.
  const lists: [number, number][][] = [
    index.search(query, RETRIEVAL.bm25TopK),
    index.search(normalized.english, RETRIEVAL.bm25TopK),
  ];
  if (normalized.keywords.length > 0) {
    lists.push(index.search(normalized.keywords.join(' '), RETRIEVAL.bm25TopK));
  }

  const fused = rrfFuse(lists, RETRIEVAL.rrfK);
  if (fused.size === 0) return [];

  const ordered = [...fused.entries()].sort((a, b) => b[1] - a[1]);
  const shortlist = ordered
    .slice(0, RETRIEVAL.rerankCandidates)
    .map(([docId]) => records[docId])
    .filter((r): r is QaRecord => r !== undefined);

  const fallback = (): Hit[] =>
    shortlist.slice(0, RETRIEVAL.finalK).map((record, rank) => ({
      record,
      score: Math.min(1, (fused.get(record.id) ?? 0) * 10),
      rank,
    }));

  const scores = await rerank(normalized.english || query, shortlist);
  if (scores.size === 0) {
    console.warn('Rerank returned nothing; falling back to fused order');
    return fallback();
  }

  return shortlist
    .slice()
    .sort((a, b) => (scores.get(b.id) ?? 0) - (scores.get(a.id) ?? 0))
    .slice(0, RETRIEVAL.finalK)
    .map((record, rank) => ({ record, score: scores.get(record.id) ?? 0, rank }))
    .filter((hit) => hit.score > 0);
}

/** Top score, and how many hits clear half of it (the 'supporting' count). */
export function confidence(hits: Hit[]): { top: number; supporting: number } {
  const first = hits[0];
  if (!first) return { top: 0, supporting: 0 };
  const top = first.score;
  const threshold = Math.max(0.4, top * 0.5);
  return { top, supporting: hits.filter((h) => h.score >= threshold).length };
}

/** Gate on the reranked scores. Silence is the default. */
export function isConfident(hits: Hit[], minConfidence: number): boolean {
  const first = hits[0];
  if (!first) return false;
  const { top, supporting } = confidence(hits);
  if (top < minConfidence) return false;
  // One curated entry that nails the question is enough on its own; otherwise
  // we want corroboration before speaking.
  if (top >= ANSWER.trustedSoloScore && ANSWER.trustedSources.has(first.record.source)) {
    return true;
  }
  return supporting >= ANSWER.minSupporting;
}
