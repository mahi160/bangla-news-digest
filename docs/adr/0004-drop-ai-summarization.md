# Drop AI summarization -- plain collection instead

Superseded ADR-0001/0003 (batched Claude summarization via `pi` CLI). Two reasons:

1. **Licensing risk.** `pi`'s subscription auth (ADR-0003) is a personal-use grant, not
   metered API billing -- fine for a hobby run, not something to build on top of if this
   ever became more than personal tooling. Separately, republishing an "elaborate 3-6
   sentence summary of substance" of other publishers' articles (permanently archived,
   emailed, now in RSS/OPDS) is a heavier redistribution than the short snippet+link a
   feed reader does, and several sources' RSS is not licensed for that.
2. Removing it also removes the CI auth gap that made ADR-0003 drop the scheduled
   workflow entirely -- collection has no external AI dependency, so the schedule (see
   `.github/workflows/digest.yml`) now does a full run, not a degraded one.

`collect_results()` replaces `summarize_batch()`: each article's own title as headline,
a plain-text excerpt of the extracted body as "summary," section from the source's own
mapping (or `Local` if the source mixes categories -- no classifier to do better).

Revisit if a specific licensing deal or a switch to metered API billing ever makes
AI summarization worth the risk again.
