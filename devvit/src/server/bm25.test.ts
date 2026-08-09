import { describe, expect, it } from 'vitest';
import { BM25, tokenize } from './bm25.js';

const CORPUS = [
  'What is the hostel fee? Mess fees are approximately Rs 27,700 per year.',
  'What is the hostel in-time? For the first two months in-time is 7PM.',
  'How are placements? The placement cell publishes reports every year.',
  'Where is the library? The central library is near the main building.',
].map((text) => tokenize(text));

describe('tokenize', () => {
  it('lowercases and keeps digits', () => {
    expect(tokenize('Hostel FEE 27700')).toEqual(['hostel', 'fee', '27700']);
  });

  it('keeps Devanagari', () => {
    expect(tokenize('छात्रावास fee')).toEqual(['छात्रावास', 'fee']);
  });

  it('drops punctuation', () => {
    expect(tokenize('in-time?')).toEqual(['in', 'time']);
  });

  it('is safe on empty input', () => {
    expect(tokenize('')).toEqual([]);
  });
});

describe('BM25', () => {
  const index = new BM25(CORPUS);

  it('ranks the relevant document first', () => {
    const [best] = index.search('hostel mess fee', 5);
    expect(best?.[0]).toBe(0);
  });

  it('distinguishes documents sharing a common term', () => {
    // Both hostel docs contain "hostel"; only one is about in-time.
    const [best] = index.search('in-time', 5);
    expect(best?.[0]).toBe(1);
  });

  it('returns nothing for terms absent from the corpus', () => {
    expect(index.search('cricket world cup', 5)).toEqual([]);
  });

  it('returns nothing for an empty query', () => {
    expect(index.search('', 5)).toEqual([]);
  });

  it('respects topK', () => {
    expect(index.search('the', 2).length).toBeLessThanOrEqual(2);
  });

  it('handles an empty corpus without throwing', () => {
    const empty = new BM25([]);
    expect(empty.search('anything', 5)).toEqual([]);
  });
});
