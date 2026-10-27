# Privacy Policy — iiest-faq-bot

_Last updated: 9 October 2026_

iiest-faq-bot is a Reddit Developer Platform (Devvit) app that replies to
questions on subreddits where a moderator has installed it. This page says what
it reads, what it keeps, and where data goes.

## What the app reads

When the app is installed on a subreddit, Reddit sends it:

- new posts on that subreddit (title, body, flair, post ID);
- new comments on that subreddit, which it checks only for a removal request
  (`!badbot`) under one of its own replies;
- comments that mention the app, which it treats as a request to answer the
  thread's question.

It does not read private messages, chat, votes, or anything outside the
subreddits it is installed on.

## What is sent to third parties

To decide whether a post is a question and to write a reply, the app sends the
**text of the post or comment** (title and body) to the Google Gemini API
(`generativelanguage.googleapis.com`), together with matching entries from the app's own knowledge
base. Usernames are not included by the app, but anything a person writes in the
text itself is sent as written.

To learn from the subreddit, the app also sends Gemini the text of threads that
are at least a day old: the post and its upvoted comments, without usernames.
Gemini returns general question-and-answer facts drawn from them.

Google processes this under the Gemini API terms:
<https://ai.google.dev/gemini-api/terms>. No Reddit data is used by the app to
train or fine-tune any model.

No data is sent to any other third party. Nothing is sold or used for
advertising.

## What the app stores

The app stores the following in Reddit-hosted storage (Devvit Redis), scoped to
the subreddit it is installed on:

- the ID of each post it has answered and the ID of its reply, for 30 days, so
  it does not answer the same post twice;
- the IDs of its own comments, for 30 days, so it can honour removal requests;
- a count of replies posted in the current hour, for up to 2 hours, to enforce a
  rate limit;
- the IDs of threads it has learned from, for 28 days, so each is read once;
- question-and-answer entries learned from threads, each with a link to the
  thread it came from. These are written by the model as general facts, and an
  entry is discarded if it contains a phone number, email address, link or
  username. They are kept until the app is uninstalled.

It does not store the text of posts or comments as written, usernames, or
profiles. Short excerpts
of processed text may appear in the app's operational logs, which are held by
Reddit and visible only to the app developer.

## The knowledge base

Replies are drawn from a knowledge base bundled with the app, built from a
public student wiki and from student group-chat discussions that were distilled
into question-and-answer pairs and scrubbed of names, phone numbers and other
personal identifiers before being included, and from the entries it learns from
r/iiests threads as described above. If you believe an entry identifies
you or is about you, contact us (below) and it will be removed.

## Your choices

- The subreddit's owner can reply `!badbot` to any of the app's comments and it
  deletes that comment. If you want one of its replies removed, ask the
  moderators.
- Subreddit moderators can change the app's settings or uninstall it at any
  time; uninstalling removes the app's stored data for that subreddit.
- Deleting your post or comment on Reddit removes it from Reddit; the app keeps
  no copy of its text. A fact it already learned from a thread stays in its
  knowledge base; ask the moderators or contact us to have it removed.

## Contact

Open an issue at <https://github.com/AngadBasandrai/auto-mod-r-iiests/issues>
or message u/auto-mod-r-iiests on Reddit.

## Changes

Changes to this policy are published at this URL with a new "Last updated" date.
