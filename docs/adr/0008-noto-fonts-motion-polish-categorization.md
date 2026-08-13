# Noto fonts, closable motion, column-flow, URL-path categorization

Follow-up to docs/adr/0007 after user feedback: the Galada/Tiro Bangla pairing read
poorly, the modal only animated open (not closed), the 2-column layout gridded
categories into uneven cells instead of balancing them, and most articles were
landing in Local regardless of actual topic.

## Fonts: Noto Serif/Sans Bengali

Galada and Tiro Bangla were chosen for character, but Bengali needs complete
conjunct/matra coverage more than it needs a display face's personality --
incomplete coverage shows up as visibly wrong glyph shaping, which reads as
"bad font" even when the palette/layout around it is fine. Noto Serif Bengali
(headlines, 500/700/800) + Noto Sans Bengali (everything else, 400-700) have the
deepest Bengali coverage of the widely-available options and both carry real bold
weights (unlike Tiro Bangla), so hierarchy no longer has to be done by size alone.
Kalpurush (also suggested) isn't on Google Fonts -- would mean self-hosting a font
file, which is a fair option later but out of scope for a one-line CSS swap.

Not built: a font-picker toggle. Nothing here indicates readers actually want to
choose their own typeface for a five-minute digest; add it if that changes.

## Modal: close is now animated too

A `<dialog>` has no "about to close" moment to hook a CSS transition to --
`.close()` just removes it. Fixed by animating a `.closing` class instead: the
close button/backdrop click/Escape all now call a `closeModal()` that adds
`.closing` (which holds the same faded-out styles the open transition starts
from), waits for `transitionend`, then calls the real `.close()`. Falls straight
through to `.close()` if `prefers-reduced-motion: reduce` is set, since in that
case no transition will ever fire to wait for.

The *open* fade uses `@starting-style` -- the standard way (Chrome 117+, Safari
17.4+, Firefox 129+) to give a freshly-shown element a "from" state to transition
out of. Without it, the previous version's opacity/transform transition never
actually ran, because there's no previous rendered frame for the browser to
interpolate from when something goes from `display:none` to shown in one tick.

## Anchor jump: smooth-scroll + landing flash

`html{scroll-behavior:smooth}` (native, no JS) for the chip-to-category jump, plus
a `.cat:target{animation:landed}` -- a brief background flash on whichever
category you land on, since a category jump is real navigation between five
possible destinations and deserves a "you're here" confirmation, not just a scroll.
Both fall back to instant/none under `prefers-reduced-motion: reduce`.

## Column layout: CSS multicol, not a 2-cell grid

The previous 2-column mode was `grid-template-columns:1fr 1fr` with one category
per cell. With Local sitting at 55 headlines and Tech/Sports at 1-4, that's one
column towering over an almost-empty other -- not "two columns," two badly
mismatched piles. Switched to `column-count:2` (CSS multicol): categories now flow
into whichever column has room, and the browser's own column-balancing algorithm
divides total content height roughly evenly, splitting a long category across the
column break same as this would happen in a printed multi-column page.
`break-after:avoid-column` on `.cat-head` and `break-inside:avoid-column` on each
`.rows>li` keep the breaks at sane places (never separating a heading from every
row under it, never splitting a single headline+meta pair). Default is single
column now (was 2) -- the toggle exists for whoever wants the denser view, but a
five-minute skim reads better as one flow by default.

## Categorization: read the outlet's own URLs, still no AI

The dominant miscategorization was Prothom Alo (and any other source with
`section=None`) dumping ~95% of articles into Local. Its own site already encodes
the section in the URL path -- `/sports/cricket/...`, `/technology/...`,
`/entertainment/...`, `/world/...` -- so `classify_by_link()` reads that first path
segment and maps it to a `SECTIONS` entry when it recognizes one, before falling
back to Local. Confirmed against a real feed pull: same-run Local share dropped
from ~95% to ~72%, with the rest landing in International/Entertainment/Tech/Sports
instead of silently disappearing into Local.

BBC Bangla's own URLs are opaque hashed IDs (`/bengali/articles/<id>`) -- no path
signal to read. It does publish topic-specific feeds though
(`/bengali/world/rss.xml`, `/bengali/topics/entertainment/rss.xml`), so those are
now separate sources in `config.py`, listed ahead of the general `bengali/rss.xml`
feed. Since both feeds can carry the same article, `fetch_new_entries` now takes a
`seen_this_run` set shared across every source in one `main()` call -- SOURCES
order decides which section wins when an article shows up in more than one feed
this run.

Banglanews24 was left alone: its article pages 403 outright (bot-protection, not a
categorization problem), which is a separate, deeper issue than this ADR's scope.
