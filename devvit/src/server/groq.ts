// Thin wrapper over the Groq chat API, ported from src/automod/groq_client.py.
//
// Same three jobs: retry with backoff on rate limits, parse JSON tolerantly
// (models wrap JSON in prose or code fences even in JSON mode), and fall back
// from the strong model to a second one.
//
// Devvit has no npm SDK available inside the sandbox, so this is plain fetch
// against the REST endpoint. api.groq.com is allowlisted in devvit.json.

import { settings } from '@devvit/web/server';
import { MODELS } from './config.js';

const ENDPOINT = 'https://api.groq.com/openai/v1/chat/completions';
const FENCE = /```(?:json)?\s*([\s\S]*?)\s*```/;

export type ModelKind = 'fast' | 'strong';

let cachedKey: string | undefined;

async function apiKey(): Promise<string> {
  if (cachedKey) return cachedKey;
  const value = await settings.get<string>('groqApiKey');
  if (!value) {
    throw new Error(
      'groqApiKey is not configured. Set it in the app settings on developers.reddit.com.'
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
    max_tokens: options.maxTokens ?? 1024,
  };
  if (options.jsonMode) body['response_format'] = { type: 'json_object' };

  const key = await apiKey();

  // Five attempts with exponential backoff, matching the tenacity policy in the
  // Python client. Only 429 and 5xx are worth retrying; a 400 will never fix
  // itself and a 401 means the key is wrong.
  let lastError: unknown;
  for (let attempt = 1; attempt <= 5; attempt++) {
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
        throw new Error(`Groq ${response.status}: ${detail.slice(0, 300)}`);
      }
      lastError = new Error(`Groq ${response.status}: ${detail.slice(0, 300)}`);
    } catch (error) {
      lastError = error;
    }

    if (attempt < 5) await sleep(Math.min(60_000, 2000 * 2 ** (attempt - 1)));
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
      console.warn(`Groq call failed on ${model}: ${String(error)}`);
      lastError = error;
    }
  }
  throw new Error(`All Groq models failed: ${String(lastError)}`);
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
    console.warn(`Groq JSON call failed: ${String(error)}`);
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
