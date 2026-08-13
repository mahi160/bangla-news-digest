# Horizon redesign: dawn/dusk palette + type, replaces the two-ink panjika look

Supersedes docs/adr/0005's palette and type choices (its structural calls in docs/adr/0006
about tabs/modal/manifest data are untouched). Built with the `frontend-design` skill
(anthropics/skills) after the site was called out as generic-looking with weak type and
no motion.

## Why the two-ink panjika palette had to go

0005's `--stock:#f1e4c3` + `--ink:#191410` + `--red:#b82219` -- warm cream paper, near-black
serif, terracotta/vermilion accent -- is, measured against current AI-generated-design
defaults, a close match for the single most common one: warm cream background
(~`#F4F1EA`) + high-contrast serif + terracotta accent. The panjika rationale (0005) is
real, but the execution landed on the cliché anyway. Fixing "the fonts are bad, no
animation" without changing the palette would have kept that problem.

## Ground truth: dawn and dusk are real colours, not metaphors

প্রভাতী (dawn) and সান্ধ্য (dusk) name actual times of day this digest is read. The
signature element, `.horizon` -- a gradient strip under the masthead -- is literally the
sky colour of whichever edition is showing: amber/apricot for dawn, indigo/plum for dusk.
On the index it's driven by the same tab radios `:has()` already switches panels with (no
extra JS); on a standalone run permalink (no tabs to react to) it's just a `.dawn`/`.dusk`
class, since that page is always exactly one edition.

Token system (docs/adr/0005's "why" for keeping a small named set still applies):

- `--paper #ECEAE4` / `--paper-deep #E3E0D6` -- desaturated warm stone, not cream. Low
  saturation is what keeps it from reading as the cliché's `#F4F1EA` at a glance.
- `--ink #16181D` -- cool near-black (blue-black), not the old warm brown-black.
- `--iris #453E78` / `--iris-soft #E4E1F0` -- the one accent, on everything interactive
  (links, active tab, chips, CTA). Never terracotta/vermilion. 7.9:1 on `--paper`.
- `--dawn #E2963C`, `--dusk #2C2653` -- decorative only (the horizon strip, plus the run
  page's header background split). Never used as text colour on paper -- `--dawn` on
  `--paper` is 2:1, nowhere near AA.
- `--rule #D6D2C6`, `--faded #5F5A49` -- hairlines and secondary text; `--faded` is tuned
  to still clear 4.5:1 on `--paper-deep`, the darker of the two backgrounds it appears on.

## Type: three roles, not one family doing everything

- **Galada** (display, one weight) -- the masthead date only. Spent once, per the skill's
  restraint principle ("spend your boldness in one place").
- **Tiro Bangla** (headline serif) -- every article headline and category label. No bold
  weight exists for it, so hierarchy comes from size/color instead of synthetic
  (browser-faked) bold, which renders badly for Bengali.
- **Hind Siliguri** (UI sans, 400-700) -- everything else: chips, tabs, meta lines, modal
  body, buttons. Replaces `Mina`, which is the flattest-looking of the previous three.

## Motion, spent deliberately

Three moments, each with a job, all `prefers-reduced-motion`-aware:

1. Page load: a single `rise` fade+lift on `body`, plus each `.cat` block staggering in
   (capped at 5 -- one per section, not per row; with 55 headlines in one section,
   animating every `<li>` would mean a visibly cascading wait).
2. The horizon strip drifts its gradient slowly (16s, ambient, easy to miss) -- the one
   place "atmosphere" motion made sense rather than a scattered hover effect.
3. The modal fades/scales in on open (native `<dialog>` + a CSS transition on `[open]`);
   the mobile sheet keeps its slide-up.

## Left alone

Email HTML and the EPUB stylesheet still use the old two-ink inline styles/hex codes --
out of scope (the ask was "the UI," i.e. the site), and email clients strip external
fonts/`<style>` anyway so the type system doesn't carry over regardless. Worth
revisiting only if the mismatch between site and email actually bothers someone.
