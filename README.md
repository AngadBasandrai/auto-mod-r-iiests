# auto-mod-r-iiests

A FAQ answering bot for [r/iiests](https://www.reddit.com/r/iiests/). It answers
newcomers' questions from the subreddit's own knowledge plus a curated student
WhatsApp group, in **English, Hindi, or romanized Hinglish** — whichever the
question was asked in.

Its most important behaviour is knowing when to shut up. A wrong answer on your
own subreddit is worse than no answer, so every reply passes a retrieval
confidence gate and a separate model-side "can I actually answer this?" check.
Failing either means silence.

---

## How it works

```
WhatsApp export ─┐
                 ├─► parse ─► sessionize ─► LLM triage & extract ─► scrub PII ─► dedupe ─┐
r/iiests ────────┘  wiki · pinned posts · top threads                                    │
                                                                                         ▼
                                                                          data/corpus/qa.jsonl
                                                                                         │
                                                                       ┌─────────────────┴────────┐
                                                                       ▼                          ▼
                                                                 BM25 index              dense vectors
                                                                       └──────────┬───────────────┘
                                                                                  ▼
     new post / mention ─► normalize language ─► hybrid search ─► RRF ─► LLM rerank
                                                                                  ▼
                                                             confidence gate ──► stay silent
                                                                                  ▼
                                                            grounded reply in the asker's language
```

**The WhatsApp chat is never a retrieval corpus.** 29k messages of a real group
chat are mostly banter, meetup planning and memes. Indexing that and hoping
retrieval avoids the noise does not work. Instead a cheap model reads each
conversation window and emits only durable Q&A facts; everything else returns an
empty list and is discarded before it ever reaches the index. Most windows
correctly yield nothing.

### Design notes

| Choice | Reason |
|---|---|
| Groq for all LLM work | `llama-3.1-8b-instant` is cheap enough to run over ~1,300 chat windows; `llama-3.3-70b-versatile` writes noticeably better Hinglish |
| `fastembed` for vectors | Groq has no embeddings endpoint. fastembed runs `paraphrase-multilingual-MiniLM-L12-v2` (0.22 GB) through ONNX Runtime — no PyTorch, and identical locally and on a CI runner that reloads it every 10 minutes. Bigger multilingual models are listed in `config.yaml` if you move to an always-on host |
| Hybrid BM25 + dense | Dense alone fumbles proper nouns ("Sanaka", "Part-II", branch codes); BM25 alone fumbles transliteration — "hostel fees kitni hai" shares almost no tokens with "What does accommodation cost?" |
| numpy, not a vector DB | A few thousand rows. A dot product is exact and instant; anything heavier is ceremony |
| Pseudonyms before extraction | Real names never reach the model — the biggest PII leak is closed by construction, not by filtering |
| GitHub Actions cron | Genuinely free 24/7 on a public repo, no server to maintain |

---

## Setup

### 1. Install

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
copy .env.example .env      # then fill it in
```

### 2. Create the Reddit bot account

1. Make a **dedicated account** (e.g. `u/iiests_faq_bot`) and verify its email.
   Don't use your personal account.
2. Logged in **as the bot**, go to <https://www.reddit.com/prefs/apps> →
   *create another app…*
   - type: **script** — this is what enables the password grant PRAW uses
   - redirect uri: `http://localhost:8080` (unused, but required)
3. The **client_id** is the short string under the app name; the **secret** is
   labelled. Put both in `.env`.
4. **Keep 2FA off on the bot account.** With 2FA the password must be
   `password:TOTPCODE`, which cannot work unattended. Use a long unique password
   instead.
5. You own r/iiests, so **add the bot as a moderator** (Mod Tools → Moderators →
   Invite) with `posts`, `flair` and `wiki` permissions, and accept from the bot
   account. This bypasses karma gating and the spam filter, and grants wiki read
   access.
6. **Announce it in a pinned post.** A bot replying to people with no
   explanation reads as spam even in your own sub.

Rate limits: the free tier allows 100 queries/minute per OAuth client for
non-commercial use. A 10-minute poll uses a handful.

### 3. Build the knowledge base

```powershell
# The export is already at data/raw/whatsapp/ and is gitignored -- it never
# leaves this machine.

# Preview first: 20 sampled windows, prints pairs, writes nothing. Cheap.
python scripts/ingest_whatsapp.py --limit 20 --dry-run

# Happy with the quality? Run the lot.
python scripts/ingest_whatsapp.py
python scripts/ingest_reddit.py

python scripts/build_corpus.py
python scripts/build_corpus.py --check    # PII audit -- must pass before committing
python scripts/build_index.py
```

Extraction results are cached by conversation-window hash, so re-running after a
prompt tweak only pays for what actually changed.

### 4. Try it

```powershell
python scripts/ask.py "hostel fees kitni hai" --show-hits
python scripts/ask.py "What is the hostel fee?"
python scripts/ask.py "who won the world cup"     # must refuse
```

The first two should surface the same records — that's the transliteration test.
The third must stay silent.

### 5. Run the bot

```powershell
python scripts/run_bot.py            # dry run: logs what it would post
python scripts/run_bot.py --live     # actually comments
```

### 6. Deploy

Push to GitHub, then add these repository secrets (Settings → Secrets and
variables → Actions): `GROQ_API_KEY`, `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET`,
`REDDIT_USERNAME`, `REDDIT_PASSWORD`, `REDDIT_USER_AGENT`.

`.github/workflows/bot.yml` then polls every 10 minutes. Run it manually first
(Actions → bot → Run workflow, leave *dry run* ticked) and read the log before
letting the schedule go live.

> **The repo should be public.** Unlimited Actions minutes only apply to public
> repos; private gets 2,000/month and a 10-minute cron burns ~4,300. This is safe
> because `data/raw/` is gitignored and only the scrubbed, distilled corpus is
> committed — but run `python scripts/build_corpus.py --check` before every
> corpus commit. If you'd rather keep it private, drop the cron to `*/30`.

---

## Safety rails

These fire in order, and every one of them defaults to *don't post*:

1. **`DRY_RUN=true` by default** — logs the exact comment, posts nothing.
2. **`max_post_age_minutes`** (120) — the bot never touches backlog, so first run
   can't spam a hundred old threads.
3. **Duplicate check** — `seen.json` is a fast path; the authoritative check asks
   Reddit whether the bot already commented in that thread, and fails closed.
4. **Confidence gate** — needs a reranked top score ≥ 0.7 *and* a second
   supporting record (or one mod-curated wiki entry scoring ≥ 0.9).
5. **Reply caps** — 3 per run, 8 per hour.
6. **`!badbot`** — any reply containing it, or a comment score below −3, makes
   the bot delete its own comment and log the case to `data/feedback.jsonl`.

All of these live in `config.yaml`.

---

## Tuning

Everything worth changing is in `config.yaml`:

- `bot.trigger_flairs` — which flairs auto-trigger a reply
- `bot.auto_reply_unflaired` — whether to answer unflaired new posts at all
- `answer.min_confidence` / `min_supporting` — raise these if it's too chatty
- `curate.min_confidence` — how strict the corpus filter is
- `models.*` — swap Groq models

If the bot answers something badly, the fix is usually the corpus, not the
prompt. Find the offending row in `data/corpus/qa.jsonl`, delete or correct it,
and re-run `scripts/build_index.py`.

---

## Layout

```
src/automod/
  config.py          settings, paths, config.yaml access
  groq_client.py     retries, JSON-mode parsing, model routing
  lang.py            offline script/language detection + LLM query normalization
  ingest/            whatsapp.py (both export dialects), reddit_faq.py
  curate/            sessionize.py, extract.py, scrub.py, build_corpus.py
  index/             store.py (embeddings + hybrid index), build.py
  retrieve.py        BM25 + dense -> RRF -> LLM rerank -> confidence
  answer.py          grounded generation, language mirroring, refusal
  bot/               reddit_client.py, state.py, poll.py
scripts/             ingest_whatsapp · ingest_reddit · build_corpus · build_index · ask · run_bot
tests/               parser, windowing, PII scrubbing, language detection (all offline)
```

## Tests

```powershell
.venv\Scripts\python.exe -m pytest tests -q
```

No API keys required — the suite covers the parts that must not silently break.
