// Offline language detection. Mirrors tests/test_lang.py on the Python side —
// if these two disagree, the corpus and the bot disagree about what language a
// question was asked in.

import { describe, expect, it } from 'vitest';
import { detect, replyStyle } from './lang.js';

describe('detect', () => {
  it('treats plain English as English', () => {
    expect(detect('What is the hostel fee?').lang).toBe('en');
    expect(detect('Anyone know when placements start?').lang).toBe('en');
  });

  it('treats Devanagari as Hindi', () => {
    const result = detect('छात्रावास का शुल्क कितना है?');
    expect(result.lang).toBe('hi');
    expect(result.script).toBe('deva');
  });

  it('treats two romanized markers as Hinglish', () => {
    const result = detect('hostel fees kitni hai');
    expect(result.lang).toBe('hinglish');
    expect(result.isTransliterated).toBe(true);
    expect(result.markerHits).toEqual(['hai', 'kitni']);
  });

  it('does not misroute English that happens to contain one marker', () => {
    // "bhai" alone is common in otherwise-English posts. One marker must not
    // be enough, or English questions get answered in Hinglish.
    expect(detect('bhai anyone know the placement stats?').lang).toBe('en');
  });

  it('handles mixed script', () => {
    expect(detect('hostel का fee कितना है भाई').script).toBe('mixed');
  });

  it('is safe on empty input', () => {
    const result = detect('');
    expect(result.lang).toBe('en');
    expect(result.markerHits).toEqual([]);
  });

  it('gives every language a reply style', () => {
    for (const text of ['What is the fee?', 'fees kitni hai bhai', 'शुल्क कितना है?']) {
      expect(replyStyle(detect(text)).length).toBeGreaterThan(0);
    }
  });
});
