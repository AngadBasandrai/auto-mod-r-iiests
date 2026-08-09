// The knowledge base, inlined into the server bundle at build time.
//
// Devvit's server entry is a single self-contained file with no filesystem, so
// the corpus cannot be read at runtime. scripts/export_corpus_json.py converts
// data/corpus/qa.jsonl into corpus.generated.json and esbuild inlines it.
//
// The BM25 index is built lazily on first use and then kept for the life of the
// process — cold starts pay a few milliseconds, everything after is free.

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

export const records: QaRecord[] = (rows as RawRow[]).map((row, index) => ({
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

let index: BM25 | undefined;

export function bm25(): BM25 {
  if (!index) {
    const started = Date.now();
    index = new BM25(records.map((record) => tokenize(lexicalText(record))));
    console.log(`Built BM25 over ${records.length} records in ${Date.now() - started}ms`);
  }
  return index;
}
