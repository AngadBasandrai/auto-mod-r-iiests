// Thin wrapper over the Gemini chat API, ported from src/automod/groq_client.py.
//
// Same three jobs: retry with backoff on rate limits, parse JSON tolerantly
// (models wrap JSON in prose or code fences even in JSON mode), and fall back
// from the strong model to a second one.
//
// Gemini rather than Groq because Reddit's fetch policy allows only OpenAI and
// Google Gemini as AI providers; a request for any other domain is denied. The
// Python pipeline still builds the corpus with Groq, which runs locally and is
// not subject to that policy.
//
// Devvit has no npm SDK available inside the sandbox, so this is plain fetch
// against Gemini's OpenAI-compatible REST endpoint, which keeps the request and
// response shapes identical to the Groq client this was ported from.
// generativelanguage.googleapis.com is requested in devvit.json.

import { settings } from '@devvit/web/server';
import { MODELS } from './config.js';

const ENDPOINT = 'https://generativelanguage.googleapis.com/v1beta/openai/chat/completions';

// Gemini 3 models always think, and thinking tokens are spent out of
// max_tokens. Without headroom a 512-token JSON reply gets cut off mid-object.
const THINKING_HEADROOM_TOKENS = 1024;

const ATTEMPTS = 3;
const FENCE = /```(?:json)?\s*([\s\S]*?)\s*```/;

export type ModelKind = 'fast' | 'strong';

let cachedKey: string | undefined;

async function apiKey(): Promise<string> {
  if (cachedKey) return cachedKey;
  const value = await settings.get<string>('geminiApiKey');
  if (!value) {
    throw new Error(
      'geminiApiKey is not configured. Set it with: npx devvit settings set geminiApiKey'
    );
  }
  cachedKey = value;
  return value;
}

const sleep = (ms: number): Promise<void> => new Promise((r) => setTimeout(r, ms));

interface ChatOptions {
  kind?: ModelKind;
  temperature?: number;
  maxTokens?: number;
  jsonMode?: boolean;
  fallback?: boolean;
}

async function callModel(
  model: string,
  system: string,
  user: string,
  options: ChatOptions
): Promise<string> {
  const body: Record<string, unknown> = {
    model,
    messages: [
      { role: 'system', content: system },
      { role: 'user', content: user },
    ],
    temperature: options.temperature ?? 0.2,
    max_tokens: (options.maxTokens ?? 1024) + THINKING_HEADROOM_TOKENS,
    reasoning_effort: 'low',
  };
  if (options.jsonMode) body['response_format'] = { type: 'json_object' };

  const key = await apiKey();

  // Three attempts, one and two seconds apart. The Python client retries five
  // times over a minute, but a trigger here has 30 seconds for the whole reply:
  // five attempts on an exhausted quota used all of it before the fallback
  // model got a turn. Only 429 and 5xx are worth retrying; a 400 will never fix
  // itself and a 401 means the key is wrong.
  let lastError: unknown;
  for (let attempt = 1; attempt <= ATTEMPTS; attempt++) {
    try {
      const response = await fetch(ENDPOINT, {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${key}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(body),
      });

      if (response.ok) {
        const data = (await response.json()) as {
          choices?: { message?: { content?: string } }[];
        };
        return data.choices?.[0]?.message?.content ?? '';
      }

      const detail = await response.text().catch(() => '');
      if (response.status !== 429 && response.status < 500) {
        throw new Error(`Gemini ${response.status}: ${detail.slice(0, 700)}`);
      }
      lastError = new Error(`Gemini ${response.status}: ${detail.slice(0, 700)}`);
    } catch (error) {
      lastError = error;
    }

    if (attempt < ATTEMPTS) await sleep(1000 * 2 ** (attempt - 1));
  }
  throw lastError instanceof Error ? lastError : new Error(String(lastError));
}

/** One chat turn. `kind` selects a model. */
export async function chat(
  system: string,
  user: string,
  options: ChatOptions = {}
): Promise<string> {
  const kind = options.kind ?? 'fast';
  const models: string[] = [MODELS[kind]];
  if (options.fallback) models.push(MODELS.strongFallback);

  let lastError: unknown;
  for (const model of models) {
    try {
      return await callModel(model, system, user, options);
    } catch (error) {
      console.warn(`Gemini call failed on ${model}: ${String(error)}`);
      lastError = error;
    }
  }
  throw new Error(`All Gemini models failed: ${String(lastError)}`);
}

/** Chat turn that must return a JSON object. Resolves to `fallbackValue` if it doesn't. */
export async function chatJson<T>(
  system: string,
  user: string,
  fallbackValue: T,
  options: ChatOptions = {}
): Promise<T> {
  let raw: string;
  try {
    raw = await chat(system, user, {
      temperature: 0,
      maxTokens: 2048,
      ...options,
      jsonMode: true,
    });
  } catch (error) {
    console.warn(`Gemini JSON call failed: ${String(error)}`);
    return fallbackValue;
  }

  const parsed = parseJson(raw);
  if (parsed === undefined) {
    console.warn(`Could not parse JSON from model output: ${raw.slice(0, 200)}`);
    return fallbackValue;
  }
  return parsed as T;
}

/** Best-effort JSON extraction from a model response. Exported for tests. */
export function parseJson(raw: string): unknown {
  if (!raw) return undefined;
  const text = raw.trim();

  try {
    return JSON.parse(text);
  } catch {
    /* fall through */
  }

  const fenced = FENCE.exec(text);
  if (fenced?.[1]) {
    try {
      return JSON.parse(fenced[1]);
    } catch {
      /* fall through */
    }
  }

  // Reasoning models sometimes prefix an explanation. Take the outermost
  // brace-balanced span and try that.
  for (const [open, close] of [
    ['{', '}'],
    ['[', ']'],
  ] as const) {
    const start = text.indexOf(open);
    const end = text.lastIndexOf(close);
    if (start !== -1 && end > start) {
      try {
        return JSON.parse(text.slice(start, end + 1));
      } catch {
        continue;
      }
    }
  }
  return undefined;
}
