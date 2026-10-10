// Devvit server entry. Routes the triggers declared in devvit.json.
//
// This replaces scripts/run_bot.py and the GitHub Actions cron. Triggers are
// pushed by Reddit the moment a post is submitted, so there is no polling
// window, no backlog to guard against, and no state file to commit — which
// removes three of the failure modes the Python bot had to defend against.

import { createServer, getServerPort } from '@devvit/web/server';
import type { IncomingMessage, ServerResponse } from 'node:http';

import { onAppInstalled } from './handlers/catchUp.js';
import { onPostSubmit } from './handlers/postSubmit.js';
import { onCommentCreate, onMention } from './handlers/moderation.js';

type Handler = (payload: unknown) => Promise<unknown>;

const ROUTES: ReadonlyMap<string, Handler> = new Map<string, Handler>([
  ['/internal/triggers/post-submit', onPostSubmit as Handler],
  ['/internal/triggers/comment-create', onCommentCreate as Handler],
  ['/internal/triggers/mention', onMention as Handler],
  ['/internal/triggers/app-install', onAppInstalled as Handler],
  ['/internal/triggers/app-upgrade', onAppInstalled as Handler],
]);

async function readJson(request: IncomingMessage): Promise<unknown> {
  const chunks: Buffer[] = [];
  for await (const chunk of request) chunks.push(chunk as Buffer);
  if (chunks.length === 0) return {};
  try {
    return JSON.parse(Buffer.concat(chunks).toString('utf8'));
  } catch {
    return {};
  }
}

function send(response: ServerResponse, status: number, body: unknown): void {
  const payload = JSON.stringify(body ?? {});
  response.writeHead(status, {
    'Content-Type': 'application/json',
    'Content-Length': Buffer.byteLength(payload),
  });
  response.end(payload);
}

const server = createServer(async (request, response) => {
  const path = (request.url ?? '').split('?')[0] ?? '';
  const handler = ROUTES.get(path);

  if (!handler) {
    send(response, 404, { error: `No handler for ${path}` });
    return;
  }

  try {
    const result = await handler(await readJson(request));
    send(response, 200, result ?? { status: 'ok' });
  } catch (error) {
    // A trigger that throws gets retried by the platform. Retrying a failed
    // answer attempt risks a double post, so failures are swallowed into a 200
    // and logged instead.
    console.error(`${path} failed: ${String(error)}`);
    if (error instanceof Error && error.stack) console.error(error.stack);
    send(response, 200, { status: 'error', message: String(error) });
  }
});

server.listen(getServerPort());
