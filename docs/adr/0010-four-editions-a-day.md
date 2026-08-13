# Four editions a day (06/12/18/24 BD), not two

Cadence changed from twice daily (06:00/18:00) to four times a day (06:00, 12:00,
18:00, 00:00 BD). Generalizes the dawn/dusk system (docs/adr/0006, 0007) that was
hardcoded to exactly two.

## Bucketing, not exact-hour matching

`edition()` used to be a single `hour < 12` check. Four runs need four buckets, so
`_EDITIONS` centres one on each scheduled hour (06/12/18/00) with a ±3h margin --
a run firing a few minutes early or late from GitHub Actions' scheduling jitter
still lands in the bucket it was meant for, rather than flipping to a neighbour.

## The "night" edition is each date's *first*, not its last

Non-obvious enough to get its own note: the 00:00 BD run is the earliest of a
given calendar date's four editions (00:00 comes before that same date's 06:00,
12:00, 18:00) -- not the previous date's last one. The retention prune, which
resets "today so far" and used to fire on the `"dawn"` (06:00) run, now has to
fire on `"night"` (00:00) instead; firing on morning would leave the manifest
holding the *previous* date's three leftover runs for six extra hours every day.
Got this backwards on the first pass and caught it with a test
(`test_update_site_prunes_on_the_night_edition_not_morning`) before it shipped.

## `_todays_editions()`: filter by date, not `manifest[:2]`

The index used to just take the first two manifest entries, safe only because
pruning guaranteed at most two ever existed. With four a day and pruning tied to
one specific edition, `_todays_editions()` now explicitly filters to runs sharing
the newest run's calendar date (capped at 4) rather than trusting the slice --
belt-and-suspenders against the exact class of bug above happening again, and
against any manually-triggered out-of-schedule run leaving stragglers.

## Signature colour per tab, now generated per page

The four editions don't map to fixed tab positions -- which four actually exist on
a given day, and in what order, is just whatever's in the manifest. So the
`.horizon` colour can't be a handful of static `:has(#ed1:checked)` rules anymore
(that assumed exactly two, and that index 1 was always dusk). `render_index` now
emits one `body:has(#edN:checked) .horizon{...}` rule per tab, each pointing at
the correct gradient for *that tab's actual* edition class
(`_HORIZON_GRADIENT`, mirrored from the static `.horizon.<cls>` rules in
`STYLE_CSS` used by the standalone run page). Four short gradient strings kept in
sync by hand in two places -- not worth building a shared-templating path for.

## Left as a two-way split: email, `LOOKBACK_HOURS`

Email's light/dark header treatment stays binary (`morning`/`noon` vs
`evening`/`night`) rather than growing four variants -- mail clients strip enough
styling that four near-identical treatments wouldn't read as different anyway.
`LOOKBACK_HOURS` tightened from 13 to 7 (still a bit over the new 6h gap between
runs, same margin logic as before, just against the new cadence) so a normal run
isn't re-checking articles from two cycles back against `seen_urls` for no reason.
