// The confidence gate. This is the code that decides whether the bot speaks at
// all, so every one of these cases is a case where it must stay quiet.

import { describe, expect, it } from 'vitest';
import { confidence, isConfident, type Hit } from './retrieve.js';
import type { QaRecord } from './corpus.js';

function hit(score: number, source = 'whatsapp', id = 0): Hit {
  const record: QaRecord = {
    id,
    question: 'q',
    questionOriginal: 'q',
    answer: 'a',
    topic: 'general',
    source,
    ref: '',
    confidence: 0.8,
  };
  return { record, score, rank: id };
}

describe('confidence', () => {
  it('is zero with no hits', () => {
    expect(confidence([])).toEqual({ top: 0, supporting: 0 });
  });

  it('counts hits clearing half the top score', () => {
    const result = confidence([hit(0.9, 'whatsapp', 0), hit(0.5, 'whatsapp', 1), hit(0.1, 'whatsapp', 2)]);
    expect(result.top).toBe(0.9);
    expect(result.supporting).toBe(2);
  });

  it('applies a 0.4 floor so weak hits never corroborate', () => {
    // Half of 0.5 is 0.25, but a 0.3 hit is not support for anything.
    const result = confidence([hit(0.5, 'whatsapp', 0), hit(0.3, 'whatsapp', 1)]);
    expect(result.supporting).toBe(1);
  });
});

describe('isConfident', () => {
  it('refuses with no hits', () => {
    expect(isConfident([], 0.7)).toBe(false);
  });

  it('refuses below the threshold however many hits agree', () => {
    expect(isConfident([hit(0.6, 'whatsapp', 0), hit(0.6, 'whatsapp', 1)], 0.7)).toBe(false);
  });

  it('refuses a strong lone chat hit', () => {
    // One person in a group chat saying something is not enough.
    expect(isConfident([hit(0.95, 'whatsapp', 0)], 0.7)).toBe(false);
  });

  it('accepts a strong hit with corroboration', () => {
    expect(isConfident([hit(0.9, 'whatsapp', 0), hit(0.8, 'whatsapp', 1)], 0.7)).toBe(true);
  });

  it('accepts a lone curated entry that nails the question', () => {
    for (const source of ['reddit_wiki', 'reddit_pinned', 'student_wiki']) {
      expect(isConfident([hit(0.95, source, 0)], 0.7)).toBe(true);
    }
  });

  it('refuses a lone curated entry that only scores well', () => {
    // The solo path needs 0.9, not merely the configured minimum.
    expect(isConfident([hit(0.85, 'student_wiki', 0)], 0.7)).toBe(false);
  });

  it('honours a raised threshold', () => {
    const hits = [hit(0.75, 'whatsapp', 0), hit(0.75, 'whatsapp', 1)];
    expect(isConfident(hits, 0.7)).toBe(true);
    expect(isConfident(hits, 0.8)).toBe(false);
  });
});
