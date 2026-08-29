# 🧭 Ceylon Compass — AI Sri Lanka Travel Guide

A full-stack AI chatbot that answers travel questions about Sri Lanka
and, on request, renders an itinerary/route diagram — built entirely
with free APIs (Groq for text, Mermaid.js for diagrams).

## What this project is (and isn't)

This is a **prompt-engineering and reliability-engineering exercise
wrapped in a small full-stack app** — not a heavy AI/ML infrastructure
project. There's no vector database, no retrieval, no agent loop, and
no persistence. It's two LLM calls behind a Flask route, done carefully:
the text answer is dependable and well-formatted; the diagram is a
best-effort secondary feature (see below). If you're looking for the
infra-heavy side of my work — embeddings, retrieval, tool-use — that's
a separate project (an agentic RAG assistant for research papers).

## Architecture

```
Browser (HTML/CSS/JS, Mermaid.js)
      │  POST /api/ask { topic }
      ▼
Flask backend (app.py)
      │
      ├─► Groq API (LLM #1) ──► structured travel answer (text)
      │
      └─► [only if the message asks for a visual/itinerary]
           Groq API (LLM #2) ──► Mermaid.js flowchart syntax
           (up to 3 attempts if Groq returns an empty completion)
      │
      ▼
JSON response { explanation, diagram, diagram_error }
      ──► text rendered in chat UI
      ──► diagram (if present) rendered client-side by Mermaid.js as SVG
      ──► diagram_error (if present) shown as a small inline note,
          text answer still displays either way
```

## Key design decisions

- **Two LLM calls, each with one job.** The first call is tuned for a
  clear, traveler-friendly answer. The second call (only triggered when
  needed) turns that answer into Mermaid flowchart syntax — LLMs handle
  each of these narrow tasks better than one call trying to do both.
- **Diagrams only generate when asked.** `wants_diagram()` combines a
  keyword list ("draw", "itinerary", "route", "map out", etc.) with a
  regex for natural "N-day" / "three-day" trip phrasing, so a request
  like "3-day trip to Ella" is caught even without the word "itinerary."
  Plain questions get a fast, text-only answer, like a normal chatbot.
- **Diagram generation is best-effort, and that's a deliberate choice,
  not an oversight.** Groq occasionally returns an empty completion for
  the diagram call specifically (observed directly in testing — the
  identical call succeeds on a retry). Rather than chase 100%
  reliability on a free-tier model, the app retries up to 3 times, then
  fails visibly (`diagram_error` shown to the user) instead of silently
  showing nothing. The text answer is unaffected either way — it's
  never blocked on the diagram succeeding.
- **Mermaid.js instead of image generation.** An earlier version used
  a free image-generation API (Pollinations.ai), but diffusion image
  models proved unreliable at rendering readable labels and structured
  boxes/arrows in testing — garbled text, inaccurate diagrams. Mermaid.js
  renders deterministically from text syntax instead, so when a diagram
  does render, it's always legible and structurally correct.
- **The prompt template defers to the user's own instructions.** If
  someone asks for "one sentence" or "just the highlights," the model
  is told to follow that over the default bullet-point format — an
  earlier version ignored these requests because the format rules were
  unconditional.
- **Small talk short-circuits the pipeline.** Greetings like "hi" are
  caught before any Groq call, returning an instant canned reply.
- **Flask over Next.js** — this is a small, backend-heavy app (one or
  two outbound API calls + simple templating), so a single Python file
  avoids the API-route boilerplate a Next.js app would need.

## Setup

1. Clone the project, then create a virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate   # Windows: venv\Scripts\activate
   pip install -r requirements.txt
   ```

2. Get a free Groq API key from https://console.groq.com/keys

3. Copy `.env.example` to `.env` and add your key:
   ```bash
   cp .env.example .env
   # then edit .env: GROQ_API_KEY=gsk_...
   ```

4. Run it:
   ```bash
   python app.py
   ```
   Visit http://localhost:5000

**Note on model choice:** Groq periodically deprecates older models.
This project uses `openai/gpt-oss-120b`. If you get a `404` or
`model_decommissioned` error, check
https://console.groq.com/docs/deprecations and swap `GROQ_MODEL` in
`app.py` for whatever's current.

## Try it

- `best places to visit in Kandy` → text-only travel answer
- `plan a 3-day trip from Colombo to Ella` → text answer **+** a
  Mermaid itinerary diagram (usually — see note on reliability above)
- `explain it in one sentence` → tests that explicit length requests
  override the default format
- `hi` → instant canned reply, no API call

## Error handling covered

- Empty input / overly long input (>4000 chars) → 400 with a clear message
- Groq API timeout → 504
- Groq API failure (bad key, rate limit, etc.) → 502/500 with the
  underlying error surfaced
- Groq returning a truncated response (hit the token limit mid-sentence)
  → detected via `finish_reason` and automatically retried with a
  doubled token budget
- Diagram generation failing (empty response or invalid Mermaid syntax,
  after 3 attempts) → the text answer still displays; a small inline
  note explains the diagram didn't render, instead of failing silently
- Frontend: network failure, disabled send button while a request is
  in flight (prevents double-submits), edit/regenerate per message

## Known limitations

- **Diagram generation is not 100% reliable** (see above) — this is a
  free-tier LLM flakiness issue, not something fixable purely through
  better code. Documented as a conscious trade-off rather than a bug.
- **No fact-checking.** Prices, opening hours, and similar specifics
  come from the model's training data, not a live source — they can be
  outdated or invented. Fine for a demo; a production version would
  need retrieval from a real, current data source.
- **Stateless.** No conversation memory across messages, no persistence
  between sessions.

## Possible extensions
- Streaming the Groq response token-by-token (Groq supports SSE streaming)
- Conversation history / follow-up questions with message context
- Retrieval over real Sri Lanka Tourism Board data instead of relying
  purely on the model's trained knowledge
- Deploying to a free host (Render/Railway) for a live demo link