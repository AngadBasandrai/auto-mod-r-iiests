# iiest-faq-bot

A Reddit Developer Platform (Devvit) app that answers frequently asked questions
on r/iiests, the subreddit for IIEST Shibpur students and applicants.

## What it does

- **Answers new posts.** When a post is submitted, the app checks whether it is
  a genuine question, searches a bundled knowledge base of question-and-answer
  pairs, and replies with a short answer if it is confident.
- **Joins in when it has no answer.** With "Reply to every post" on (the
  default), a question the knowledge base does not cover gets a reply that
  opens "I don't know, but being an LLM I can hallucinate:" followed by the
  deliberately absurd, obviously made-up answer, written for humour. That
  opening is fixed in the code, so a made-up answer is always labelled as one,
  and the footer repeats it. The answer is absurd on purpose so that nobody
  mistakes it for advice. A post that is not a question gets a short comment in
  the same spirit.
  The app stays silent on posts about distress, harassment, emergencies and
  similar topics where an unverified or light reply would be out of place. With
  the setting off, the app is silent whenever it has no answer.
- **Catches up.** When it is first installed, and after a release that changes
  how it replies, it replies once to the four newest posts, replacing any
  earlier reply of its own on them.
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
| Reply to every post | On | Reply to every new post whatever its flair, with a labelled unverified answer or a friendly comment when the knowledge base has no answer. |
| Answer unflaired posts | Off | Only used when "Reply to every post" is off. When off, only posts flaired Ask, Question, Admissions or Doubt are answered. |
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
