# Asking questions about your notes

Page can answer questions from your notes using a language model, with numbered
citations back to the passages it used. Gemini is the supported provider; Page Core
itself depends only on a small provider-neutral interface.

## How a question is answered

1. **Retrieve.** Page Core brings the semantic index up to date with your saved notes
   and [knowledge sources](knowledge-sources.md) (PDFs, code, text), and finds the 10 most
   similar passages ([semantic search](semantic-search.md)).
2. **Optimize.** The [context optimizer](context-optimization.md) packs the most relevant of them into numbered,
   source-attributed context that fits your budget. It ranks by embedding similarity
   without the learned reranker, which [evaluation](evaluation.md) showed does not
   generalize.
3. **Answer.** The model receives only that context and the question. It is told to
   answer only from the sources, cite them as `[n]`, and say when the notes don't
   cover the question.
4. **Cite.** Page parses the `[n]` citations and returns them with every source's
   note, line range and text. Numbers that don't match a source are ignored.

If no passage is relevant, no model is called and Page says it found nothing.

## Setup

In the app, click the key button in the ask box, paste the key and choose
**Save Key**. Page keeps it in a private file in its settings folder and restarts Page Core to use it.

When running from a terminal, you can instead set it in the environment:

```sh
export GEMINI_API_KEY=...                       # required
export PAGE_GEMINI_MODEL=gemini-3.1-flash-lite  # optional; default gemini-3.5-flash-lite
npm run tauri:dev
```

A key saved in the app takes precedence over `GEMINI_API_KEY`. Page Core reads the key
when it starts; saving or removing a key restarts it. Without a key, everything else
works and the ask box shows where to add one.

## Using it

Type a question in the rounded ask box at the bottom of the note (Cmd/Ctrl+K focuses
it), pick a context budget (500, 1,500 or 4,000 tokens) and press Enter. Answers appear
in a card above the box, with follow-up questions kept in the same thread. Each answer
shows:
- the answer, with clickable `[n]` citations that open the cited note;
- the sources, with path, line range, whether the text was trimmed to an excerpt, and
  whether the answer cited it;
- context tokens used out of the budget (Page's `utf8-bytes/3` estimate), and the input
  and output tokens Gemini reports.

The top of the answer card shows what Page's trimming saved on the latest answer, for
example "214 sent vs 1.2K in the matching passages · 82% less". The second number is
the passages Page found for the question (10 by default), sent whole and untrimmed, in
the same format, so the two compare like for like. Measured on October 11, 2026, it was
modest: a median of 21% on the 40 benchmark questions (from 9% to 76%) and 23% on the
demo vault, the same at budgets of 500, 1,500 and 4,000 tokens. The saving comes from
dropping weakly related and duplicate passages, not from the budget. When nothing is
dropped, the card says every matching passage fit. The percentage is rounded down and capped at 99%.

The whole vault's size is in the tooltip, for scale only. Comparing with the whole
vault would show close to 99% in any large vault, because the context is capped by the
budget, so it says more about vault size than about Page. None of these numbers
measure answer quality. Per-file counts are cached by revision.

Page's mascot sits on top of the chat: on the answer card when it's open, otherwise
on the ask box, with its legs tucked behind the edge. It sways gently, shows a thought
bubble while Page finds passages and waits for Gemini, and dances with music notes and
sparkles for a moment when an answer arrives (not after an error). Its motion stops when the system
asks for reduced motion.

## Privacy and security

- Only the passages selected for a question, and the question itself, are sent to
  Google. Your whole vault is not. Unsaved drafts are never included.
- Google's Gemini API terms govern what is sent. Don't ask about notes you don't want
  to leave your machine.
- The key is sent in the `x-goog-api-key` header over HTTPS, never in a URL. Page never
  logs it, stores it, or includes it in errors.

## Errors

| Code | HTTP | Meaning |
|---|---|---|
| `llm_not_configured` | 503 | `GEMINI_API_KEY` was not set when Core started |
| `llm_auth_failed` | 502 | Gemini rejected the key |
| `llm_rate_limited` | 429 | Gemini rate limit or quota reached |
| `llm_blocked` | 422 | Gemini refused the request or answer for safety reasons |
| `llm_unavailable` | 503 | Gemini could not be reached or failed |
| `llm_failed` | 502 | Gemini rejected the request (e.g. unknown model) or answered unusably |

## API

`POST /api/v1/vaults/{vault_id}/ask` with `{"question": "...", "budget": 1500}`
(budget 50–20,000 tokens). The response has `answer`, `answered_by_model`,
`finish_reason`, numbered `sources`, the `cited` numbers, and `usage`
(`context_tokens`, `budget`, `counter`, `input_tokens`, `output_tokens`). The model
call runs off the storage worker, so note editing isn't blocked while it waits.

## Using another provider

`page_core.llm.ChatModel` is a protocol with a `name` and
`generate(system, prompt, *, max_output_tokens) -> Generation`. Pass any
implementation to `create_app(chat_model=...)` or `answering.answer_question`.

## Limits

- One question at a time; there is no conversation memory yet.
- Answer quality depends on retrieval: a fact in a passage outside the top 10 can't be
  cited.
- Gemini's answers are not checked against the sources beyond citation numbers.
- No automated test calls the real Gemini API; the adapter is tested against recorded
  response shapes.
