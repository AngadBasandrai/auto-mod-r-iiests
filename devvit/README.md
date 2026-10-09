# iiest-faq-bot

A Reddit Developer Platform (Devvit) app that answers frequently asked questions
on r/iiests, the subreddit for IIEST Shibpur students and applicants.

## What it does

- **Answers new posts.** When a post is submitted, the app checks whether it is
  a genuine question, searches a bundled knowledge base of question-and-answer
  pairs, and replies with a short answer if it is confident. If it is not
  confident, it stays silent.
- **Answers when mentioned.** Mentioning the app in a comment asks it to answer
  the thread's question, under the same confidence gate.
- **Removes its own replies on request.** Replying `!badbot` to one of the app's
  comments makes it delete that comment.

Every reply ends with a footer saying it is a bot, that it can be wrong, and how
to remove the reply.

## How it works

1. The post text is normalized (including Hindi and Hinglish) by a language
   model.
2. BM25 search over the bundled knowledge base finds candidate entries, which
   the model reranks.
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
| Answer unflaired posts | Off | When off, only posts flaired Ask, Question, Admissions or Doubt are answered. |
| Minimum confidence | 0.7 | Score a post must clear before the app replies. |
| Max replies per hour | 8 | Hard cap on replies. |
| Max post age (minutes) | 120 | Older posts are never touched. |

## Data

The app stores only the IDs of posts it answered and of its own comments (30
days) and an hourly reply counter. It does not store post text or usernames.

- [Privacy policy](https://github.com/AngadBasandrai/auto-mod-r-iiests/blob/main/devvit/PRIVACY.md)
- [Terms & conditions](https://github.com/AngadBasandrai/auto-mod-r-iiests/blob/main/devvit/TERMS.md)

## Source

<https://github.com/AngadBasandrai/auto-mod-r-iiests>
