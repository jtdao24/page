# Stage 12: asking questions about your notes

Page can answer questions from your notes using a language model, with numbered
citations back to the passages it used. Gemini is the supported provider; Page Core
itself depends only on a small provider-neutral interface.

## How a question is answered

1. **Retrieve.** Page Core brings the semantic index up to date with your saved notes
   and finds the 10 most similar passages (Stage 8).
2. **Optimize.** Stage 10's optimizer packs the most relevant of them into numbered,
   source-attributed context that fits your budget. It ranks by embedding similarity
   without the Stage 9 reranker, which [evaluation](evaluation.md) showed does not
   generalize.
3. **Answer.** The model receives only that context and the question. It is told to
   answer only from the sources, cite them as `[n]`, and say when the notes don't
   cover the question.
4. **Cite.** Page parses the `[n]` citations and returns them with every source's
   note, line range and text. Numbers that don't match a source are ignored.

If no passage is relevant, no model is called and Page says it found nothing.

## Setup

Set your key in the terminal that starts Page:

```sh
export GEMINI_API_KEY=...                       # required
export PAGE_GEMINI_MODEL=gemini-3.1-flash-lite  # optional; default gemini-3.5-flash-lite
npm run tauri:dev
```

Page Core reads the key once at startup. To change it, restart Page. Without a key,
everything else works and the Ask panel explains how to set one.

An app launched from Finder doesn't inherit terminal variables. Configuring a key for
the packaged app is part of Stage 14.

## Using it

Open **Ask your notes** from the ribbon, type a question, pick a context budget (500,
1,500 or 4,000 tokens) and press **Ask**. The panel shows:
- the answer, with clickable `[n]` citations that open the cited note;
- the sources, with path, line range, whether the text was trimmed to an excerpt, and
  whether the answer cited it;
- context tokens used out of the budget (Page's `utf8-bytes/3` estimate), and the input
  and output tokens Gemini reports.

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
