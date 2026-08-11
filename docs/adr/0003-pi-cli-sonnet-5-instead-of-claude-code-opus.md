# pi CLI (Claude Sonnet 5) instead of claude CLI (Opus)

Superseded the tool/model choice from ADR-0001 (the batched, non-agentic scope itself is unchanged). Switched `summarize_batch()` from invoking `claude` (Opus, needing a separate `ANTHROPIC_API_KEY`) to invoking `pi` (Sonnet 5) via its existing subscription auth on the local machine -- no separate per-token API billing for local/manual runs.

Open question this doesn't resolve: scheduled GitHub Actions runs have no access to that local OAuth session. Either the workflow keeps using `claude`+`ANTHROPIC_API_KEY` for scheduled runs while `pi` is used for local/manual runs, or a portable auth token gets exported as a CI secret -- not decided yet, flagged rather than guessed.
