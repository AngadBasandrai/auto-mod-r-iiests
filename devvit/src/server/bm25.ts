// BM25 Okapi, ported from the `rank_bm25` package the Python side uses so both
// halves of the project rank identically. Constants and the negative-IDF
// correction are taken from BM25Okapi verbatim.
//
// The index is built once per cold start over a few thousand documents, which
// costs single-digit milliseconds.

const K1 = 1.5;
const B = 0.75;
const EPSILON = 0.25;

// Latin, digits and Devanagari. Shared with the Python tokenizer in
// src/automod/index/store.py so the two produce the same terms.
const TOKEN = /[a-z0-9ऀ-ॿ]+/g;

export function tokenize(text: string): string[] {
  return (text ?? '').toLowerCase().match(TOKEN) ?? [];
}

export class BM25 {
  private readonly docFreqs: Map<string, number>[] = [];
  private readonly docLengths: number[] = [];
  private readonly idf = new Map<string, number>();
  private readonly avgdl: number;
  readonly size: number;

  constructor(corpus: string[][]) {
    this.size = corpus.length;

    // Document frequency per term, and per-document term counts.
    const nd = new Map<string, number>();
    let totalLength = 0;

    for (const document of corpus) {
      const frequencies = new Map<string, number>();
      for (const term of document) {
        frequencies.set(term, (frequencies.get(term) ?? 0) + 1);
      }
      this.docFreqs.push(frequencies);
      this.docLengths.push(document.length);
      totalLength += document.length;
      for (const term of frequencies.keys()) {
        nd.set(term, (nd.get(term) ?? 0) + 1);
      }
    }

    this.avgdl = this.size > 0 ? totalLength / this.size : 0;

    // A term in more than half the corpus gets a negative IDF, which would let
    // it subtract from a score. rank_bm25 floors those at a fraction of the
    // mean IDF rather than at zero; matching that keeps ranking parity.
    let idfSum = 0;
    const negative: string[] = [];
    for (const [term, freq] of nd) {
      const value = Math.log(this.size - freq + 0.5) - Math.log(freq + 0.5);
      this.idf.set(term, value);
      idfSum += value;
      if (value < 0) negative.push(term);
    }
    const averageIdf = this.idf.size > 0 ? idfSum / this.idf.size : 0;
    const floor = EPSILON * averageIdf;
    for (const term of negative) this.idf.set(term, floor);
  }

  /** Score every document against `queryTokens`. */
  scores(queryTokens: string[]): Float64Array {
    const out = new Float64Array(this.size);
    if (this.size === 0) return out;

    for (const term of queryTokens) {
      const idf = this.idf.get(term);
      if (idf === undefined) continue;
      for (let i = 0; i < this.size; i++) {
        const frequency = this.docFreqs[i]!.get(term);
        if (frequency === undefined) continue;
        const length = this.docLengths[i]!;
        const denominator =
          frequency + K1 * (1 - B + (B * length) / (this.avgdl || 1));
        out[i]! += (idf * (frequency * (K1 + 1))) / denominator;
      }
    }
    return out;
  }

  /** Top `topK` documents as [index, score], best first, zero scores dropped. */
  search(query: string, topK: number): [number, number][] {
    const tokens = tokenize(query);
    if (tokens.length === 0) return [];
    const scores = this.scores(tokens);

    const ranked: [number, number][] = [];
    for (let i = 0; i < scores.length; i++) {
      if (scores[i]! > 0) ranked.push([i, scores[i]!]);
    }
    ranked.sort((a, b) => b[1] - a[1]);
    return ranked.slice(0, topK);
  }
}
