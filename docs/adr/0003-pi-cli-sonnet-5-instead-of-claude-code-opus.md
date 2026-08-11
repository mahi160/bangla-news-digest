# pi CLI (Claude Sonnet 5) instead of claude CLI (Opus)

Superseded the tool/model choice from ADR-0001 (the batched, non-agentic scope itself is unchanged). Switched `summarize_batch()` from invoking `claude` (Opus, needing a separate `ANTHROPIC_API_KEY`) to invoking `pi` (Sonnet 5) via its existing subscription auth on the local machine -- no separate per-token API billing for local/manual runs.

Resolved the CI-auth gap by dropping the scheduled workflow entirely: scheduled GitHub Actions runs have no access to the local OAuth session pi uses, and exporting a portable token as a long-lived CI secret was judged not worth the security trade-off for a hobby digest. The digest is now run manually/locally (`python pipeline.py`, then `git push`); GitHub Actions only deploys the pushed `site/` folder to Pages (`.github/workflows/pages.yml`), it no longer runs the pipeline at all.
