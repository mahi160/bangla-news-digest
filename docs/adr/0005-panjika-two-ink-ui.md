# Panjika two-ink UI, digest-first index

Ground-up replacement of the previous cream/serif + dawn-gold/dusk-blue theme and its
radio-hack tab index. Four decisions worth not re-litigating by accident:

## 1. Two inks only, on saffron newsprint

The whole visual identity is a Bengali almanac (পঞ্জিকা): saffron paper stock, black
letterpress ink, and vermilion as the one second ink. **Links are vermilion, not blue,
and there is no third hue anywhere.** That constraint is the design -- the moment a
hyperlink blue or a status green gets added, the page stops reading as a printed object
and becomes a website with a beige background.

The palette values in `STYLE_CSS` are set by contrast, not by eye: `--red` and `--block`
are pinned where the vermilion clears 4.5:1 on *both* the paper and the tint block. Don't
"warm up" `--block` without re-checking, the accent-on-tint pair is the tight one.

## 2. The evening edition is a reversed plate, not a second palette

`প্রভাতী` renders as an outlined block on paper; `সান্ধ্য` inverts to solid ink with the
stock colour as text. Same two inks, no paper behind them -- which is why `--red-rev`
exists (the vermilion at `--red` fails contrast on black, and it's the same ink, just
without paper showing through). This is how the twice-daily cadence stays legible without
spending a third colour on it.

## 3. No letter-spacing on Bangla

Tracking is a Latin small-caps device. Applied to Bengali it pulls the parts of an akshara
apart (`বিস্তারিত` renders as `বি স্তা রি ত`). Label hierarchy is carried by weight, size
and the second ink instead. The only `letter-spacing` in the stylesheet is on `.feeds`,
where the text is Latin (RSS/OPDS).

## 4. The index is digest-first

The index used to inline every article's full excerpt for all 2-3 of the day's editions,
duplicating each body into `index.html` *and* `feed.xml`. It was ~154 KB of mostly
unscrolled text. The index now carries only the সূচি (headline + source + one-line
teaser) and links into each edition's own page for `বিস্তারিত`; that dropped it to ~54 KB
with no loss of reachable content.

Consequences:

- Today's editions **stack** on the index instead of hiding behind CSS tabs. Retention
  caps this at a handful of same-day runs, and an almanac is a bound sequence of day-pages
  anyway. The radio-input tab hack is gone, along with its `nth-of-type` fragility.
- `_run_fragment()` now takes a `part`: `"all"` (everything after the edition header, for
  the RSS description) and `"digest"` (just the সূচি, for the index). It tolerates
  `class=quick-digest` from pre-redesign archived pages so the day this shipped didn't
  blank out earlier editions.
- Stacking means three digests in one document, so `render_index` namespaces the extracted
  fragment's section ids (`s-Local` -> `s0-Local`) and re-points its `#aN` row links at the
  run page, where those detail anchors actually exist.

## Signature element

The **tally rule** under each edition header: one segment per section, flex-sized by
article count, doubling as the section nav. It encodes something true (where the run's
weight actually landed) rather than decorating -- which is also why there is no `01 / 02 /
03` numbering on the digest rows. Feed arrival order is not a sequence, so numbering it
would be a lie; the row marker is the source name instead, which is information a skimmer
wants. `flex-basis` on the segments is a legibility floor: every section keeps a readable
label, and only the space above that floor is shared out proportionally.

## Also folded in

`_strip_repeated_headline()`: most Bangla outlets open the article body with the headline
again, sometimes twice, so every teaser used to be its own headline restated. Compared in
NFD because feed titles and extracted bodies disagree on precomposed য়/ড়/ঢ় (U+09DF etc.)
vs. base + nukta -- those three are Unicode *composition exclusions*, so NFC does not
reconcile them and a plain `startswith` silently misses.

`esc()`: headlines, sources and links are now HTML-escaped on the way out. They were being
interpolated raw, so an `&` or `<` in a feed title produced broken markup.

`safe_url()`: feed-provided links go into `href="..."` on the published site, in EPUB
chapters and in subscriber email. Escaping does *not* defuse a `javascript:`/`data:` URL --
it stays a live link -- so anything that isn't plain http(s) is dropped and the source is
credited without a link. Applied at **each sink**, not once upstream, so it holds however
the article dict was built; feeds are third-party and untrusted.

One thing deliberately *not* changed: `build_rss` runs `xml_escape()` over an
already-HTML-escaped fragment, which looks like double-escaping (`&amp;` -> `&amp;amp;` in
the raw XML) but is correct. XML-parse yields `&amp;`, then HTML-parse yields `&`. It
round-trips; don't "fix" it into CDATA.

Email gained an HTML alternative (digest-only, inline styles, no webfonts -- clients strip
`<style>` and `@import`) alongside the existing plain-text part and EPUB attachment.
