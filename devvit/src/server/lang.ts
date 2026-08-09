// Language handling for Hindi / English / romanized Hinglish.
// Ported from src/automod/lang.py, marker list and thresholds unchanged.
//
// Two layers:
//   * detect()        cheap, offline, deterministic. Decides which script the
//                     reply is written in. Unit tested.
//   * normalizeQuery() one small LLM call that restates the question in English
//                     and produces keyword variants.
//
// The keyword variants matter more here than they did in Python. The Python bot
// had dense vectors to catch "hostel fees kitni hai" ~ "What does accommodation
// cost?"; this one is lexical only, so the alternate spellings the normalizer
// produces are what carry transliteration across.

import { chatJson } from './groq.js';

const DEVANAGARI = /[ऀ-ॿ]/g;
const LATIN = /[A-Za-z]/g;

// High-signal romanized Hindi tokens.
//
// Every entry must be a word that essentially never appears in an English
// sentence. That rules out some genuinely common Hindi words — "the" (past
// tense), "he", "hi", "mere", "mat", "par" — because they collide with English
// and would misroute plain English questions into Hinglish replies. Likewise
// "fees" and "admission" are English, not markers, however often they appear.
// Precision matters more than recall: two markers are required to trigger.
const HINGLISH_MARKERS = new Set(
  `hai hain haii hei hoga hogi honge hota hoti hote tha thi
   kya kyu kyun kyon kaise kese kaisa kaisi kab kahan kahaan kaha
   kitna kitni kitne kaun konsa kaunsa kon
   nahi nahin nhi nai bilkul kuch koi sab sabhi
   mujhe mujhko mera meri hamara hamari tumhara tumhari aapka aapki
   apna apni uska uski unka unki iska iski
   karo karna karta karti karte krna kro karke krke
   milega milegi milta milti chahiye chaiye
   bhai bhaiya yaar bhii toh tho
   accha acha theek thik sahi galat matlab bata batao batado
   pata lagta lagega jyada zyada thoda bohot bahut bhot
   agar lekin magar phir fir waise abhi aaj kal jaldi
   zaroori zaruri chalega samajh dekho suno
   rehna rehne khana padhai padhna andar bahar`
    .split(/\s+/)
    .filter(Boolean)
);

export type Language = 'hi' | 'en' | 'hinglish';
export type Script = 'deva' | 'latin' | 'mixed';

export interface Detection {
  lang: Language;
  script: Script;
  isTransliterated: boolean;
  markerHits: string[];
}

const REPLY_STYLE: Record<Language, string> = {
  hi: 'Hindi, written in Devanagari script',
  hinglish:
    'romanized Hinglish (Hindi words in Latin script, mixed with English) — match the casual tone of the question',
  en: 'English',
};

export function replyStyle(detection: Detection): string {
  return REPLY_STYLE[detection.lang];
}

/** Offline language/script detection. No network. */
export function detect(text: string): Detection {
  const value = text ?? '';
  const deva = value.match(DEVANAGARI)?.length ?? 0;
  const latin = value.match(LATIN)?.length ?? 0;

  const words = value.toLowerCase().match(/[a-z]+/g) ?? [];
  const markerHits = [...new Set(words.filter((w) => HINGLISH_MARKERS.has(w)))].sort();

  let script: Script;
  if (deva && latin) script = 'mixed';
  else if (deva) script = 'deva';
  else script = 'latin';

  // Devanagari present in any real quantity -> answer in Hindi script.
  if (deva >= 3 && deva >= Math.floor(latin / 4)) {
    return { lang: 'hi', script, isTransliterated: false, markerHits };
  }

  // Two independent romanized-Hindi markers is a reliable Hinglish signal; one
  // is common in otherwise-English posts ("bhai anyone know...").
  if (markerHits.length >= 2) {
    return { lang: 'hinglish', script, isTransliterated: true, markerHits };
  }

  return { lang: 'en', script, isTransliterated: false, markerHits };
}

const NORMALIZE_SYSTEM = `You normalize questions asked by Indian engineering college students on Reddit.
The question may be in English, Hindi (Devanagari), romanized Hindi written in Latin
letters ("Hinglish"), or any mix. Spelling is often inconsistent.

Return ONLY a JSON object:
{
  "english_query": "the question restated as a clear, standalone English question",
  "keywords": ["5-12 short search terms"],
  "topic": "one of: admissions, academics, hostel, fees, placements, campus, clubs, exams, transfer, general",
  "is_question": true or false
}

Rules:
- "english_query" must preserve the exact intent. Do not answer it, do not add facts.
- "keywords" are used for keyword search against an FAQ written by students, so
  they must include BOTH the English term and the romanized Hindi term when they
  differ, plus likely misspellings and alternate transliterations a student would
  type. Example: for "hostel fees kitni hai" ->
  ["hostel fee", "hostal fees", "hostel charges", "chhatravas", "mess fees", "accommodation cost"].
- Set "is_question" to false if the text is a rant, announcement, meme, or greeting
  rather than something answerable.`;

export interface NormalizedQuery {
  original: string;
  english: string;
  keywords: string[];
  topic: string;
  isQuestion: boolean;
  detection: Detection;
}

interface NormalizeResponse {
  english_query?: string;
  keywords?: unknown[];
  topic?: string;
  is_question?: boolean;
}

/** Canonicalize a user question. Falls back to the raw text if Groq fails. */
export async function normalizeQuery(text: string): Promise<NormalizedQuery> {
  const original = (text ?? '').trim();
  const detection = detect(original);

  const data = await chatJson<NormalizeResponse>(
    NORMALIZE_SYSTEM,
    original.slice(0, 4000),
    {},
    { kind: 'fast', maxTokens: 512 }
  );

  const english = String(data.english_query ?? '').trim() || original;
  const keywords = (data.keywords ?? [])
    .map((k) => String(k).trim())
    .filter((k) => k.length > 0);

  return {
    original,
    english,
    keywords,
    topic: String(data.topic ?? 'general'),
    // Default true: a normalizer failure must not silently mute the bot in a
    // way that looks like a deliberate refusal.
    isQuestion: data.is_question ?? true,
    detection,
  };
}
