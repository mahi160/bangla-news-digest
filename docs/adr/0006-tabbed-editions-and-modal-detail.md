# Tabbed editions + modal detail, headline-only index

Reverses the "stacked editions, no tabs" call in docs/adr/0005 #4, and drops the
inline detail/excerpt sections in favour of a click-to-open modal (bottom sheet on
mobile). Two inks + type from 0005 are untouched.

## Why reverse the stacking decision

0005 dropped a radio-input tab hack because retention was "a handful of same-day
runs." In practice retention is exactly ≤2 (`_prune_before` runs on every dawn edition,
so the manifest never holds more than that day's dawn + dusk). Two editions is exactly
what tabs are for; stacking two same-length sections back to back just doubles the
scroll for no reason. Landing on the *latest* edition by default (dawn radio not yet
run at 3am -> the newest entry is still yesterday's dusk run, which is what should
show) falls out for free: `render_index` always checks `manifest[0]`, and pruning
already guarantees that's "today's news" per the 06:00 cutoff.

## CSS-only tabs and column toggle, JS only for the modal

Both the edition tabs and the 1/2-column layout toggle are `<input type=radio>` +
`:checked` + `:has()` -- no JS, works with scripting disabled, and the default
`checked` radio is rendered server-side so there's no flash-of-wrong-tab. `:has()`
is what makes this simpler than the old-school sibling-combinator radio hack: the
radios don't need to be adjacent to (or an ancestor of) what they control, so the
tab labels can live in their own `.tabs` wrapper instead of being interleaved into
the markup they toggle.

The one place JS is unavoidable is the modal: which article's data to show is
inherently dynamic. It's ~25 lines reading `data-*` off the clicked `.row` into the
one `<dialog>` on the page, then `showModal()`. Backdrop dimming, Esc-to-close and
focus handling are the browser's, not this script's.

## Headline-only rows; a real `<a>`, not a `<button>`

Every row is still a plain link to the source article (`href` first, `data-*`
second) -- with JS disabled it behaves exactly like the pre-modal design. With JS on,
the click handler `preventDefault()`s and opens the modal instead. No excerpt, no
teaser, no author line inline: "no details or desc, just headlines, segmented by
category" was the explicit ask, and the modal is where all of that (image, author,
time, excerpt, the source link) now lives.

## Manifest carries full article data now, not just counts

`runs.json` entries gained a `"grouped"` key (the same dict `render_run_html` and the
EPUB build already work with) alongside the pre-existing `"counts"`. `render_index`,
`build_rss`, and `build_opds` all read it directly -- nothing re-parses
already-written HTML off disk to reconstruct a fragment anymore (`_run_fragment` /
`_DIGEST_RE` are gone). Bounded the same way the site always was: at most two runs
survive pruning, so this is a couple hundred short article records, not an archive.

## Per-article author/image

`extract_meta()` replaces `extract_text()`: same single `fetch_url()` call, but now
also runs `trafilatura.metadata.extract_metadata()` against the already-downloaded
page for `author`/`image` (og:image, byline) -- no second request per article.
`image` goes through the same `safe_url()` scheme allowlist as the article link
before it ever reaches a `src=`/`data-image=`.
