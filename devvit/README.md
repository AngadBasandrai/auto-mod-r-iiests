# iiest-faq-bot

A Reddit Developer Platform (Devvit) app that answers frequently asked questions
on r/iiests, the subreddit for IIEST Shibpur students and applicants.

## What it does

- **Answers new posts.** When a post is submitted, the app checks whether it is
  a genuine question, searches a bundled knowledge base of question-and-answer
  pairs, and replies with a short answer if it is confident.
  If it is not confident, it says nothing.
- **Learns from the subreddit.** Every two hours it reads a few threads that are
  at least a day old, takes the comments people upvoted, and has the language
  model extract the facts those comments establish as new question-and-answer
  entries. Those entries are searched alongside the bundled knowledge base, so a
  question answered well in one thread can be answered by the app the next time
  it is asked. The app never learns from its own comments, and drops any entry
  that carries a phone number, email, link or username.
- **Catches up.** When it is first installed, and after a release that changes
  how it replies, it replies once to the four newest posts it can answer
  confidently, replacing any earlier reply of its own on them.
- **Answers when mentioned.** Mentioning the app in a comment asks it to answer
  the thread's question, under the same confidence gate.
- **Removes its own replies when the subreddit owner asks.** The owner (the
  longest-standing moderator) replying `!badbot` to one of the app's comments
  makes it delete that comment. Nobody else can trigger this.

Every reply ends with a footer saying it is a bot and that it can be wrong.

## How it works

1. The post text is normalized (including Hindi and Hinglish) by a language
   model.
2. BM25 search over the bundled knowledge base finds candidate entries, which
   the model reranks.
   Learned entries from r/iiests threads are part of the same index.
3. If the top score clears the moderator-set threshold, the model writes an
   answer using only the retrieved entries.

The language model is Google Gemini, called through
`generativelanguage.googleapis.com`. Only the text of the post or comment and
the matching knowledge-base entries are sent. No Reddit data is used to train
or fine-tune any model.

The knowledge base is fixed at build time. It comes from a public student wiki
and from student discussions distilled into question-and-answer pairs with
names, phone numbers and other personal identifiers removed.

## Moderator settings

| Setting | Default | Meaning |
| --- | --- | --- |
| Dry run | On | Log the reply the app would post without posting it. |
| Question flairs only | Off | When on, only posts flaired Ask, Question, Admissions or Doubt are considered. When off, every post is considered and the confidence gate decides. |
| Minimum confidence | 0.7 | Score a post must clear before the app replies. |
| Max replies per hour | 8 | Hard cap on replies. |
| Max post age (minutes) | 120 | Older posts are never touched. |

## Data

The app stores the IDs of posts it answered and of its own comments (30 days),
an hourly reply counter, the IDs of threads it has learned from, and the
question-and-answer entries it learned. Learned entries are written by the
model as general facts, without usernames or contact details. It does not store
the text of posts or comments, or usernames.

- [Privacy policy](https://github.com/AngadBasandrai/auto-mod-r-iiests/blob/main/devvit/PRIVACY.md)
- [Terms & conditions](https://github.com/AngadBasandrai/auto-mod-r-iiests/blob/main/devvit/TERMS.md)

## Source

<https://github.com/AngadBasandrai/auto-mod-r-iiests>
