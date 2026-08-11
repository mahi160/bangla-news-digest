# Claude Code scoped to batched, non-agentic summarization

The pipeline (RSS fetch, article scraping, EPUB build, email send) is deterministic and cheap to do with plain libraries. We decided Claude Code (Opus) is invoked for exactly one job: turn already-fetched plain article text into a Bengali headline + summary + section, with no tool-use/web-fetching by Claude itself. All articles for a Run are sent in a single batched call (one call per Run, not per article) to avoid paying fixed per-call overhead N times.

Trade-off accepted: a single bad article in the batch could complicate parsing/retry of that one call, versus the token savings of not re-sending instructions per article. Revisit per-article calls if batch parsing/retry proves unreliable in practice.
