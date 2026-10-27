// A learned record is published to every future asker, so anything that still
// points at a person must never make it in.

import { describe, expect, it } from 'vitest';
import { carriesPii } from './handlers/learn.js';

describe('carriesPii', () => {
  it('catches phone numbers, emails, usernames and links', () => {
    expect(carriesPii('Call the office on 98765 43210')).toBe(true);
    expect(carriesPii('Call +91-9876543210 for hostel')).toBe(true);
    expect(carriesPii('Mail hostel.office@iiests.ac.in')).toBe(true);
    expect(carriesPii('Ask u/some_senior about it')).toBe(true);
    expect(carriesPii('See https://example.com/form')).toBe(true);
  });

  it('lets ordinary facts through', () => {
    expect(carriesPii('Mess fees are about Rs 27,700 per year.')).toBe(false);
    expect(carriesPii('First-year hostels have 4 and 5 seater rooms.')).toBe(false);
    expect(carriesPii('Mid-sems are held in the 8th week, 2026 batch too.')).toBe(false);
  });
});
