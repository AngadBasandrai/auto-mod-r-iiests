// Models wrap JSON in prose and code fences even in JSON mode. Every one of
// these shapes has been seen in practice.

import { describe, expect, it } from 'vitest';
import { parseJson } from './llm.js';

describe('parseJson', () => {
  it('parses plain JSON', () => {
    expect(parseJson('{"answerable": true}')).toEqual({ answerable: true });
  });

  it('parses a fenced block', () => {
    expect(parseJson('```json\n{"a": 1}\n```')).toEqual({ a: 1 });
  });

  it('parses an unlabelled fence', () => {
    expect(parseJson('```\n{"a": 1}\n```')).toEqual({ a: 1 });
  });

  it('recovers JSON after a prose preamble', () => {
    expect(parseJson('Here is the result:\n{"a": 1}\nHope that helps!')).toEqual({ a: 1 });
  });

  it('parses arrays', () => {
    expect(parseJson('[1, 2, 3]')).toEqual([1, 2, 3]);
  });

  it('returns undefined for unparseable output', () => {
    expect(parseJson('I cannot answer that.')).toBeUndefined();
  });

  it('returns undefined for empty output', () => {
    expect(parseJson('')).toBeUndefined();
  });
});
