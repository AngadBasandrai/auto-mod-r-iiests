// The knowledge base: the bundled corpus plus what the bot has learned since.
//
// The bundled half is inlined into the server bundle at build time. Devvit's
// server entry is a single self-contained file with no filesystem, so it cannot
// be read at runtime. scripts/export_corpus_json.py converts
// data/corpus/qa.jsonl into corpus.generated.json and esbuild inlines it.
//
// The learned half lives in Redis, written by handlers/learn.ts from r/iiests
// comment threads. It is per-subreddit and changes while the app runs, so the
// BM25 index is rebuilt whenever the learned version counter moves, and reused
// otherwise. A rebuild over a few thousand records costs single-digit
// milliseconds; checking the counter costs one Redis read per post.

import { redis } from '@devvit/web/server';

import rows from './corpus.generated.json' with { type: 'json' };
import { BM25, tokenize } from './bm25.js';

export interface QaRecord {
  id: number;
  question: string;
  questionOriginal: string;
  answer: string;
  topic: string;
  source: string;
  ref: string;
  confidence: number;
}

interface RawRow {
  question?: string;
  question_original?: string;
  answer?: string;
  topic?: string;
  source?: string;
  ref?: string;
  confidence?: number;
}

/** A record learned from a comment thread, as stored in Redis. */
export interface LearnedRow {
  question: string;
  answer: string;
  topic: string;
  /** Permalink of the thread it came from, shown as the source. */
  ref: string;
  confidence: number;
  learnedAt: string;
}

export const LEARNED_KEY = 'learned:records';
export const LEARNED_VERSION_KEY = 'learned:version';

const bundled: QaRecord[] = (rows as RawRow[]).map((row, index) => ({
  id: index,
  question: row.question ?? '',
  questionOriginal: row.question_original || (row.question ?? ''),
  answer: row.answer ?? '',
  topic: row.topic ?? 'general',
  source: row.source ?? 'unknown',
  ref: row.ref ?? '',
  confidence: row.confidence ?? 1,
}));

/** Both spellings go in, so Hinglish and English queries both hit. */
function lexicalText(record: QaRecord): string {
  return `${record.questionOriginal}\n${record.question}\n${record.answer}\n${record.topic}`;
}

export interface Knowledge {
  records: QaRecord[];
  index: BM25;
  learned: number;
}

let cached: { version: string; knowledge: Knowledge } | undefined;

async function readLearned(): Promise<QaRecord[]> {
  const stored = await redis.hGetAll(LEARNED_KEY);
  // Sorted by field so ids are stable across processes for the same version.
  return Object.keys(stored)
    .sort()
    .flatMap((field) => {
      try {
        const row = JSON.parse(stored[field]!) as LearnedRow;
        return [
          {
            question: row.question,
            questionOriginal: row.question,
            answer: row.answer,
            topic: row.topic || 'general',
            source: 'reddit_comments',
            ref: row.ref,
            confidence: row.confidence,
          },
        ];
      } catch {
        return [];
      }
    })
    .map((record, position) => ({ ...record, id: bundled.length + position }));
}

/**
 * The current knowledge base and its index. If Redis is unreachable this falls
 * back to the bundled corpus alone rather than failing the reply.
 */
export async function knowledge(): Promise<Knowledge> {
  let version = 'bundled-only';
  let learned: QaRecord[] = [];
  try {
    version = (await redis.get(LEARNED_VERSION_KEY)) ?? '0';
    if (cached?.version === version) return cached.knowledge;
    learned = await readLearned();
  } catch (error) {
    console.warn(`Could not read learned records, using the bundled corpus: ${String(error)}`);
    if (cached) return cached.knowledge;
  }

  const started = Date.now();
  const records = [...bundled, ...learned];
  const index = new BM25(records.map((record) => tokenize(lexicalText(record))));
  console.log(
    `Built BM25 over ${records.length} records (${learned.length} learned) in ${Date.now() - started}ms`
  );

  const built = { records, index, learned: learned.length };
  cached = { version, knowledge: built };
  return built;
}
