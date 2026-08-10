// The guards that decide whether a generated answer is allowed out. Both cases
// are real: they come from replaying r/iiests posts, and both would have posted.

import { describe, expect, it } from 'vitest';
import { hasTopic, isEcho } from './answer.js';

describe('isEcho', () => {
  it("rejects the poster's own words", () => {
    const question =
      'Introducing, IIEST-Chan\n\n' +
      'Meet IIEST-Chan, an anthropomorphic version of the IIEST clock tower. ' +
      "Fully hand drawn and shaded. Turns out I can't do shading if my life depends on it.";
    const answer =
      'IIEST-Chan is an anthropomorphic version of the IIEST clock tower, fully hand drawn and shaded.';
    expect(isEcho(answer, question)).toBe(true);
  });

  it('allows an answer that adds facts', () => {
    expect(
      isEcho(
        'In the 1st year hostels, rooms are typically shared by 4 students. Note that there ' +
          'might be a few exceptions with 8 people, but 4 is the major configuration.',
        'How many sharing room in 1st year ??'
      )
    ).toBe(false);
  });

  it("allows an answer reusing the question's nouns with a figure", () => {
    expect(
      isEcho(
        'The hostel fee is approximately Rs 27,000 per semester, including mess.',
        'What is the hostel fee?'
      )
    ).toBe(false);
  });

  it('never treats a short answer as an echo', () => {
    expect(isEcho('No, hostel is not mandatory.', 'Is hostel mandatory for first years?')).toBe(
      false
    );
  });

  it('does not flag a Hinglish answer to a Hinglish question', () => {
    expect(
      isEcho(
        'Hostel fees per semester lagbhag Rs 27,000 hai, including mess.',
        'hostel fees kitni hai'
      )
    ).toBe(false);
  });
});

describe('hasTopic', () => {
  it('rejects a bare plea for help', () => {
    // Real post: title "URGENT!!!", body "Can anyone help please".
    expect(hasTopic('URGENT!!!\n\nCan anyone help please')).toBe(false);
    expect(hasTopic('guys plz help urgent')).toBe(false);
    expect(hasTopic('Need advice, any suggestions? Thanks in advance')).toBe(false);
  });

  it('accepts a plea that names its subject', () => {
    expect(hasTopic('URGENT!!! can anyone help with hostel allotment please')).toBe(true);
    expect(
      hasTopic('Hello can seniors pls tell which electronics core companies to iiest shibpur')
    ).toBe(true);
  });

  it('accepts ordinary short questions', () => {
    for (const q of ['Is ragging bad?', 'hostel fees kitni hai', 'Is attendance strict']) {
      expect(hasTopic(q), q).toBe(true);
    }
  });
});
