# Modal image loader + prev/next, segmented category cards

Follow-up to docs/adr/0008 after more feedback: the modal's image caused a layout
jump on first open and briefly kept showing the previous article's picture on the
next one; there was no way to move between articles without closing and
reopening; categories didn't read as distinct enough at a glance.

## Image: reserved space + a shimmer, cleared before the swap

Two separate bugs, one root cause -- the `<img>` had no reserved size and no
"in-between" state:

- **First-open jump**: the image element took `height:auto`, so before it
  finished loading the browser didn't know its height and the modal's layout
  shifted once the image decoded and claimed its real space.
- **Stale image on next article**: setting `img.src` to a new URL doesn't clear
  what's currently painted -- browsers keep showing the old bitmap until the new
  one finishes decoding, so flipping to the next headline showed the *previous*
  article's photo for a moment.

Fixed with a wrapper (`.m-img-wrap`) at a fixed `aspect-ratio`, so the space is
correct before any image data has arrived at all -- confirmed with Playwright
that the wrapper's box is already final at the moment `showModal()` runs, not
after the image loads. A shimmer (`::before` on the wrapper, `background-size:
200%` sweeping) fills that reserved space until the `<img>` gets a `.loaded`
class from a `load` listener. `MODAL_SCRIPT.openRow()` strips `.loaded` (back to
the shimmer) *before* setting the new `src`, so the previous picture is never on
screen for a different article -- the visible state during a swap is always
"loading," never "wrong."

## Prev / Next

Two small buttons in the modal body, plus ArrowLeft/ArrowRight while the dialog
has focus. The list they walk is computed fresh on every open --
`Array.from(document.querySelectorAll('.row')).filter(r => r.offsetParent !==
null)` -- i.e. whatever's actually rendered right now, in DOM order. That's
deliberately decoupled from the tab mechanism (docs/adr/0006): the script never
has to know a tab switch happened, hidden panels just don't produce visible
`.row`s. Disabled (not wrapped/hidden) at both ends -- skimming to the edge of a
category shouldn't silently loop back to the start.

## Categories as segmented, coloured cards

Each section (`SECTION_ACCENT` in pipeline.py) now renders as its own card:
tinted background, a coloured left rule, a matching dot by the heading, and a
coloured count-badge pill -- instead of a plain heading and a hairline. The five
accent colours are decorative only (never a text colour), so they can't create a
contrast problem; the one place a light colour sits *as a background* (the count
badge) was checked to clear 4.5:1 with `--paper` text on top.

`box-decoration-break:clone` matters here specifically because categories now
flow across the multicol layout (docs/adr/0008) -- without it, a category long
enough to split across the column gap would render as one card sliced in half
(square-cornered at the break); with it, each column's portion gets the full
rounded/bordered treatment, reading as two complete cards instead of a cut one.
