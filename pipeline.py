"""Bangla news digest: fetch -> extract -> collect (no AI summary, see
docs/adr/0004) -> EPUB + HTML site + email. Run twice a day by GitHub
Actions.

Deterministic, boring code throughout -- knobs live in config.py.
"""
import json
import logging
import os
import re
import smtplib
import sys
import time
import unicodedata
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import format_datetime
from html import escape as h_esc
from pathlib import Path
from urllib.parse import urlparse
from xml.sax.saxutils import escape as xml_escape

import feedparser
import trafilatura
from ebooklib import epub
from trafilatura.metadata import extract_metadata

from config import (
    EXCERPT_CHARS, LOCAL_TZ_OFFSET_HOURS, LOOKBACK_HOURS, MAX_ARTICLE_CHARS,
    RETRY_ATTEMPTS, RETRY_BACKOFF_SECONDS, RSS_ITEM_CAP, SECTIONS,
    SEEN_URLS_KEEP, SITE_URL, SOURCES, TEASER_CHARS,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("digest")


def retry(fn, what, attempts=RETRY_ATTEMPTS, backoff=RETRY_BACKOFF_SECONDS):
    """Retry a flaky network call with linear backoff. Raises the last
    exception if every attempt fails."""
    last_exc = None
    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except Exception as e:
            last_exc = e
            log.warning("%s failed (attempt %d/%d): %s", what, attempt, attempts, e)
            if attempt < attempts:
                time.sleep(backoff * attempt)
    raise last_exc


ROOT = Path(__file__).parent
STATE_PATH = ROOT / "state.json"
SITE_DIR = ROOT / "site"
RUNS_MANIFEST = SITE_DIR / "runs.json"

# --- date formatting (Bangla, twice-daily edition-aware) --------------------
# ponytail: fixed 06:00/18:00 cadence per README -- hour<12 is always the
# morning run in practice, no timezone-of-reader handling needed for a
# single-author digest site.

_BN_DIGITS = str.maketrans("0123456789", "০১২৩৪৫৬৭৮৯")
_BN_MONTHS = ["জানুয়ারি", "ফেব্রুয়ারি", "মার্চ", "এপ্রিল", "মে", "জুন", "জুলাই",
              "আগস্ট", "সেপ্টেম্বর", "অক্টোবর", "নভেম্বর", "ডিসেম্বর"]
_BN_WEEKDAYS = ["সোমবার", "মঙ্গলবার", "বুধবার", "বৃহস্পতিবার", "শুক্রবার", "শনিবার", "রবিবার"]
BD_TZ = timezone(timedelta(hours=LOCAL_TZ_OFFSET_HOURS))


def to_bd(dt):
    """Editions/dates are always shown in Bangladesh local time -- run_dt is
    UTC (datetime.now(timezone.utc)), so every display/labeling call site
    converts through here first."""
    return dt.astimezone(BD_TZ)


def bn_date(dt):
    return f"{dt.day} {_BN_MONTHS[dt.month - 1]}, {dt.year}".translate(_BN_DIGITS)


def bn_weekday(dt):
    return _BN_WEEKDAYS[dt.weekday()]


def bn_time(dt):
    period = ("রাত" if dt.hour < 4 else "ভোর" if dt.hour < 6 else "সকাল" if dt.hour < 12
              else "দুপুর" if dt.hour < 16 else "বিকাল" if dt.hour < 18 else "সন্ধ্যা" if dt.hour < 20
              else "রাত")
    h12 = dt.hour % 12 or 12
    return f"{period} {h12}:{dt.minute:02d}".translate(_BN_DIGITS)


def edition(dt):
    """(label, css-class) for the twice-daily run cadence."""
    return ("প্রভাতী সংস্করণ", "dawn") if dt.hour < 12 else ("সান্ধ্য সংস্করণ", "dusk")


def bn_num(n):
    return str(n).translate(_BN_DIGITS)


# SECTIONS are English because they're dict keys/state; readers get Bangla.
SECTION_BN = {
    "Local": "দেশ",
    "International": "আন্তর্জাতিক",
    "Entertainment": "বিনোদন",
    "Tech": "প্রযুক্তি",
    "Sports": "খেলা",
}


# Loaded from <head> rather than @import-ed here: an @import inside a linked
# stylesheet serializes the round trips (html -> style.css -> fonts api ->
# font files) instead of starting the font fetch alongside the CSS.
FONT_LINKS = (
    '<link rel=preconnect href="https://fonts.googleapis.com">'
    '<link rel=preconnect href="https://fonts.gstatic.com" crossorigin>'
    '<link rel=stylesheet href="https://fonts.googleapis.com/css2'
    "?family=Noto+Serif+Bengali:wght@500;700;800"
    "&amp;family=Noto+Sans+Bengali:wght@400;500;600;700"
    '&amp;display=swap">'
)

# Palette + type + signature: see docs/adr/0007 (superseded on type by the
# follow-up in 0008: Noto Serif/Sans Bengali have the most complete glyph
# and conjunct coverage of the options tried, which matters more for
# Bengali body text than a characterful-but-thinner-coverage display face).
# .horizon is the signature -- a gradient strip that's literally the sky
# colour of whichever edition is showing, amber dawn / indigo dusk, driven
# by :has() off the same tab radios used for panel switching (docs/adr/0006).
STYLE_CSS = """\
:root{
  --paper:#ECEAE4; --paper-deep:#E3E0D6; --ink:#16181D;
  --iris:#453E78; --iris-soft:#E4E1F0;
  --dawn:#E2963C; --dusk:#2C2653;
  --rule:#D6D2C6; --faded:#5F5A49;
  --headline:'Noto Serif Bengali',Georgia,serif;
  --ui:'Noto Sans Bengali',system-ui,-apple-system,sans-serif;
}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%;scroll-behavior:smooth}
body{max-width:56rem;margin:0 auto;padding:1.75rem 1.15rem 4rem;
  font-family:var(--ui);font-size:1.02rem;line-height:1.7;
  color:var(--ink);background:var(--paper)}
a{color:var(--iris);text-decoration:none}
a:hover{text-decoration:underline;text-underline-offset:.18em}
a:focus-visible{outline:2px solid var(--iris);outline-offset:3px}
@media(prefers-reduced-motion:no-preference){
  body{animation:rise .5s ease-out both}
}
@keyframes rise{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:translateY(0)}}
/* Jumping to a category via a chip is a real navigation, not just a
   scroll -- a brief highlight on arrival confirms which one you landed on. */
.cat:target{animation:landed 1.1s ease-out}
@keyframes landed{from{background:var(--iris-soft)}to{background:transparent}}
@media(prefers-reduced-motion:reduce){
  html{scroll-behavior:auto}
  .cat:target{animation:none}
}

/* --- masthead + signature horizon ------------------------------------ */
.masthead{margin:0 0 1.6rem}
.masthead .eyebrow{font-family:var(--ui);font-weight:600;
  font-size:.82rem;letter-spacing:.02em;color:var(--iris);margin:0 0 .25rem}
.masthead .date{font-family:var(--display);font-weight:400;
  font-size:clamp(2.3rem,9vw,3.4rem);line-height:1;margin:0 0 .5rem;
  display:flex;flex-wrap:wrap;align-items:baseline;gap:.7rem}
.masthead .weekday{font-family:var(--ui);font-weight:500;
  font-size:.95rem;color:var(--faded)}
.masthead .feeds{margin:0 0 .9rem;display:flex;gap:.4rem}
.feeds a{font-family:var(--ui);font-weight:600;
  font-size:.72rem;letter-spacing:.06em;padding:.16rem .6rem;
  border:1.5px solid var(--rule);color:var(--faded);border-radius:1rem}
.feeds a:hover{border-color:var(--iris);color:var(--iris);text-decoration:none}
.back{display:inline-block;margin:0 0 1.1rem;font-family:var(--ui);
  font-weight:500;font-size:.82rem;color:var(--faded)}
.back:hover{color:var(--iris)}
/* The one bold move on the page: a strip that's the actual sky colour of
   the edition being read. Static ed_cls class on the standalone run page,
   :has() off the tab radios on the interactive index. */
.horizon{height:.5rem;border-radius:.25rem;margin:0 0 1.5rem;background-size:200% 100%;
  background-image:linear-gradient(100deg,#F6D9A8,var(--dawn) 45%,#B9542F 85%)}
.horizon.dusk,body:has(#ed1:checked) .horizon{
  background-image:linear-gradient(100deg,var(--dusk),#5B4B8A 55%,#8A7BB8 100%)}
@media(prefers-reduced-motion:no-preference){
  .horizon{animation:drift 16s ease-in-out infinite alternate}
}
@keyframes drift{from{background-position:0% 0}to{background-position:100% 0}}

/* --- visually-hidden radios (CSS-only tabs + column toggle) ---------- */
/* No JS for either control: :checked drives the panel/grid it targets via
   :has(), which also means these controls work with JS disabled. Not
   display:none -- kept focusable, and popped visible on keyboard focus. */
.vh{position:absolute;appearance:none;opacity:0;width:1px;height:1px;margin:-1px;overflow:hidden;border:none;background:transparent}
.vh:focus-visible{opacity:1;width:auto;height:auto;position:static;margin:0 .4rem 0 0;outline:2px solid var(--iris)}

/* --- edition tabs ------------------------------------------------------ */
.tabs{display:flex;gap:.3rem;margin:0 0 1.1rem;border-bottom:1px solid var(--rule)}
.tab{font-family:var(--headline);font-style:italic;font-size:1.05rem;cursor:pointer;
  padding:.55rem 1rem .5rem;color:var(--faded);border-bottom:2px solid transparent;
  margin-bottom:-1px;user-select:none;transition:color .15s}
.tab .tab-sub{display:block;font-family:var(--ui);font-style:normal;
  font-weight:500;font-size:.72rem;color:var(--faded)}
main:has(#ed0:checked) label.tab[for=ed0],
main:has(#ed1:checked) label.tab[for=ed1]{color:var(--iris);border-bottom-color:var(--iris)}

/* --- column toggle ------------------------------------------------------ */
.colsbar{display:flex;justify-content:flex-end;gap:.3rem;margin:0 0 1.2rem}
.colsbar label{font-family:var(--ui);font-weight:600;
  font-size:.76rem;padding:.28rem .65rem;border:1.5px solid var(--rule);
  color:var(--faded);cursor:pointer;border-radius:1.2rem;transition:color .15s,border-color .15s}
main:has(#c1:checked) label[for=c1],
main:has(#c2:checked) label[for=c2]{color:var(--iris);border-color:var(--iris)}

/* --- panels + category chips ------------------------------------------- */
.panel{display:none}
main:has(#ed0:checked) #p0{display:block}
main:has(#ed1:checked) #p1{display:block}
.chips{display:flex;flex-wrap:wrap;gap:.5rem;margin:0 0 1.7rem}
.chip{font-family:var(--ui);font-weight:600;
  font-size:.82rem;padding:.32rem .55rem .28rem .75rem;border:1.5px solid var(--rule);
  border-radius:1.2rem;color:var(--ink);display:flex;align-items:center;gap:.4rem;
  transition:border-color .15s,color .15s}
.chip:hover{border-color:var(--iris);color:var(--iris);text-decoration:none}
.chip-n{font-family:var(--headline);font-style:italic;color:var(--iris);font-size:.85rem}

/* Column flow, not a 2-cell grid: a grid would pin one category per cell,
   so a 55-headline দেশ next to a 1-headline প্রযুক্তি leaves one column
   towering over an almost-empty other. column-count lets categories
   reflow across columns so the total text height balances instead. */
.catgrid{column-count:1;column-gap:3rem}
@media(min-width:640px){
  main:has(#c2:checked) .catgrid{column-count:2}
}
.cat{min-width:0}
.cat-head{break-after:avoid-column}
.rows>li{break-inside:avoid-column}
@media(prefers-reduced-motion:no-preference){
  .cat{animation:rise .45s ease-out both}
  .cat:nth-of-type(1){animation-delay:.03s} .cat:nth-of-type(2){animation-delay:.09s}
  .cat:nth-of-type(3){animation-delay:.15s} .cat:nth-of-type(4){animation-delay:.21s}
  .cat:nth-of-type(5){animation-delay:.27s}
}
.cat-head{display:flex;align-items:baseline;gap:.6rem;margin:0 0 .6rem;
  padding-bottom:.4rem;border-bottom:1px solid var(--rule);
  font-family:var(--headline);font-weight:400;font-size:1.2rem}
.cat-head .cat-n{font-family:var(--ui);font-weight:600;
  font-size:.78rem;color:var(--iris);margin-left:auto}
.rows{list-style:none;margin:0;padding:0}
.rows>li{border-bottom:1px solid var(--rule)}
.rows>li:last-child{border-bottom:none}
.row{display:block;padding:.7rem .15rem;color:var(--ink);border-radius:.3rem;transition:background .15s}
.row:hover{background:var(--iris-soft);text-decoration:none}
.row-hl{display:block;font-family:var(--headline);font-weight:400;
  font-size:1.06rem;line-height:1.5}
.row-meta{display:block;font-family:var(--ui);font-weight:500;
  font-size:.76rem;color:var(--faded);margin-top:.2rem}
.empty{color:var(--faded)}

/* --- modal / bottom sheet ------------------------------------------------ */
/* Open: @starting-style gives the browser a real "from" state for an
   element that's display:none the frame before, so the fade-in actually
   plays instead of just appearing. Close: dialog has no closing event of
   its own to animate against, so the .closing class (toggled by the modal
   script, see MODAL_SCRIPT) holds the same off-state while [open] is still
   true, and JS calls .close() only once that transition finishes. */
dialog.modal{position:fixed;top:50%;left:50%;transform:translate(-50%,-50%) scale(1);
  margin:0;width:min(34rem,92vw);max-height:85vh;overflow:auto;border:none;
  border-radius:.6rem;padding:0;background:var(--paper);color:var(--ink);
  box-shadow:0 24px 60px -12px rgba(22,24,29,.35);opacity:1;
  transition:opacity .18s ease,transform .18s ease}
dialog.modal.closing{opacity:0;transform:translate(-50%,-50%) scale(.97)}
@starting-style{
  dialog.modal[open]{opacity:0;transform:translate(-50%,-50%) scale(.97)}
}
dialog.modal::backdrop{background:rgba(22,24,29,.5);transition:background .18s ease}
@starting-style{ dialog.modal[open]::backdrop{background:rgba(22,24,29,0)} }
.m-img{display:block;width:100%;max-height:15rem;object-fit:cover;background:var(--paper-deep)}
.modal-close{position:absolute;top:.6rem;right:.6rem;width:2.1rem;height:2.1rem;border:none;border-radius:50%;
  background:var(--ink);color:var(--paper);font-size:1.1rem;line-height:1;cursor:pointer}
.modal-body{padding:1.4rem 1.5rem 1.7rem}
.m-hl{font-family:var(--headline);font-weight:400;font-size:1.4rem;line-height:1.4;margin:0 0 .6rem}
.modal-meta{display:flex;flex-wrap:wrap;gap:.5rem;margin:0 0 .9rem;
  font-family:var(--ui);font-weight:500;font-size:.8rem;color:var(--faded)}
.modal-meta>*+*::before{content:'·';margin-right:.5rem;color:var(--rule)}
.m-excerpt{margin:0 0 1.2rem;color:var(--faded);line-height:1.65}
.m-link{display:inline-block;background:var(--iris);color:var(--paper);
  font-family:var(--ui);font-weight:600;
  font-size:.85rem;padding:.55rem 1rem;border-radius:2rem;transition:background .15s}
.m-link:hover{text-decoration:none;background:var(--ink)}
@media(max-width:640px){
  dialog.modal{top:auto;left:0;bottom:0;transform:translateY(0);width:100%;max-width:none;
    border-radius:1rem 1rem 0 0;max-height:88vh;opacity:1;transition:transform .22s ease-out}
  dialog.modal.closing{opacity:1;transform:translateY(100%)}
  @starting-style{ dialog.modal[open]{transform:translateY(100%)} }
}
@media(prefers-reduced-motion:reduce){
  dialog.modal,dialog.modal::backdrop,.horizon,.cat,body{animation:none!important;transition:none!important}
}

.colophon{margin:2.6rem 0 0;padding-top:1rem;border-top:1px solid var(--rule);
  font-family:var(--ui);font-size:.82rem;color:var(--faded)}
.colophon p{margin:.35rem 0}

@media print{
  body{background:#fff;max-width:none;animation:none}
  .back,.feeds,.tabs,.colsbar,.horizon,dialog{display:none}
}
"""


# --- state -----------------------------------------------------------------

def load_state():
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text())
    return {}


def save_state(state):
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2))


# --- fetch + extract ---------------------------------------------------------

def extract_meta(url):
    """Fetch a URL once and return {text, author, image} or None. Author/image
    come from the page's own metadata (og:*, byline) -- no extra request,
    same download trafilatura.extract() already needed for the body."""
    try:
        downloaded = trafilatura.fetch_url(url)
        if not downloaded:
            return None
        text = trafilatura.extract(downloaded)
        if not text:
            return None
        meta = extract_metadata(downloaded, default_url=url)
        return {
            "text": text,
            "author": (getattr(meta, "author", None) or "").strip(),
            "image": (getattr(meta, "image", None) or "").strip(),
        }
    except Exception as e:
        log.warning("extraction failed for %s: %s", url, e)
        return None


def fetch_new_entries(source, state, now, seen_this_run):
    """Return new articles (dicts) from one source's feed. Never raises --
    a dead source is logged and skipped, the run continues.

    seen_this_run is shared across every source in the same call to main()
    -- some outlets (BBC Bangla) are listed both as a topic-specific feed
    (World/Entertainment) and as their general mixed feed; SOURCES lists
    the specific ones first, so an article both feeds carry only gets
    captured once, with the more specific section."""
    src_state = state.setdefault(source["name"], {"seen_urls": []})
    seen = set(src_state["seen_urls"])
    cutoff = now - timedelta(hours=LOOKBACK_HOURS)

    try:
        feed = feedparser.parse(source["url"])
        if feed.bozo and not feed.entries:
            raise ValueError(f"unparseable feed: {feed.bozo_exception}")
    except Exception as e:
        log.warning("skipping source %s: fetch failed (%s)", source["name"], e)
        return []

    new_articles = []
    for entry in feed.entries:
        link = entry.get("link")
        if not link or link in seen or link in seen_this_run:
            continue

        pub_dt = None
        published = entry.get("published_parsed") or entry.get("updated_parsed")
        if published:
            pub_dt = datetime(*published[:6], tzinfo=timezone.utc)
            if pub_dt < cutoff:
                continue

        meta = extract_meta(link)
        if not meta:
            log.warning("skipping article, no extractable text: %s", link)
            continue

        new_articles.append({
            "source": source["name"],
            "section_hint": source["section"],
            "title": entry.get("title", "").strip(),
            "link": link,
            "text": meta["text"][:MAX_ARTICLE_CHARS],
            "author": meta["author"],
            "image": meta["image"],
            "published": pub_dt.isoformat() if pub_dt else None,
        })
        seen.add(link)
        seen_this_run.add(link)

    src_state["seen_urls"] = list(seen)[-SEEN_URLS_KEEP:]
    return new_articles


# First URL path segment -> section, for feeds that mix categories but whose
# own site structure (e.g. prothomalo.com/sports/..., /technology/...)
# already encodes one. No AI: just reading the outlet's own URLs. Outlets
# with opaque/ID-only paths (Banglanews24's /news/<id>, BBC's hashed
# /articles/<id>) don't match anything here and fall back to Local same as
# before -- see BBC's topic-specific sources in config.py instead.
_PATH_SECTION = {
    "sports": "Sports", "sport": "Sports", "cricket": "Sports",
    "entertainment": "Entertainment", "showbiz": "Entertainment", "glitz": "Entertainment",
    "technology": "Tech", "tech": "Tech", "science": "Tech",
    "world": "International", "international": "International",
}


def classify_by_link(link):
    path = urlparse(link or "").path.strip("/").split("/")
    return _PATH_SECTION.get(path[0].lower()) if path and path[0] else None


def _strip_repeated_headline(text, title):
    """Most Bangla outlets open the article body with the headline again --
    sometimes twice, once as a kicker. Left in, every excerpt is just its own
    headline restated.

    Compared in NFD because the feed title and the extracted body disagree on
    how they spell য়/ড়/ঢ় (composition exclusions -- NFC does not reconcile
    them, so a plain startswith silently misses).
    """
    nfd = lambda s: unicodedata.normalize("NFD", s)  # noqa: E731
    target = nfd(title.strip())
    if not target:
        return text
    for _ in range(3):
        body = text.lstrip()
        if not nfd(body).startswith(target):
            break
        cut = next((i for i in range(1, min(len(body), len(target)) + 1)
                    if nfd(body[:i]) == target), None)
        if cut is None:
            break
        text = body[cut:].lstrip(" \t\n\r:—-।")
    return text


def collect_results(articles):
    """No AI: each article's own title as headline, a plain-text excerpt of
    its extracted body. Section defaults to Local when the source doesn't
    map cleanly (see SOURCES in config.py) -- no classifier to do better."""
    results = []
    for i, a in enumerate(articles):
        title = (a["title"] or "").strip()
        text = _strip_repeated_headline(a["text"].strip(), title)
        text = text or a["text"].strip()  # body was nothing but the headline

        excerpt = text[:EXCERPT_CHARS].strip()
        if len(text) > EXCERPT_CHARS:
            excerpt = excerpt.rsplit(" ", 1)[0] + "…"
        results.append({
            "index": i,
            "headline": a["title"] or "(শিরোনামহীন)",
            "summary": excerpt,
            "section": a["section_hint"] or classify_by_link(a.get("link")) or "Local",
        })
    return results


# --- assemble ----------------------------------------------------------------

def make_teaser(text, max_chars=TEASER_CHARS):
    """First sentence (Bengali or Latin punctuation) of a longer excerpt,
    capped -- used only for the email's one-line preview."""
    text = text.strip()
    for sep in ("\u0964", ".", "!", "?"):  # । = Bengali sentence-ending mark
        idx = text.find(sep)
        if 0 < idx <= max_chars:
            return text[:idx + 1].strip()
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rsplit(" ", 1)[0] + "…"


def group_by_section(articles, results):
    """Section -> list of articles, each carrying everything a headline row
    or the detail modal needs (no anchors: nothing links within-page
    anymore, see docs/adr/0006)."""
    grouped = {s: [] for s in SECTIONS}
    by_index = {r["index"]: r for r in results}
    for i, a in enumerate(articles):
        r = by_index.get(i)
        if not r:
            continue
        section = a["section_hint"] or r.get("section")
        if section not in grouped:
            log.warning("unknown section %r, dropping article", section)
            continue
        time_label = ""
        if a.get("published"):
            try:
                time_label = bn_time(to_bd(datetime.fromisoformat(a["published"])))
            except ValueError:
                pass
        grouped[section].append({
            "headline": r["headline"],
            "excerpt": r["summary"],
            "source": a["source"],
            "link": safe_url(a["link"]),  # untrusted: feeds can send javascript: URLs
            "author": (a.get("author") or "").strip(),
            "image": safe_url(a.get("image")),
            "time": time_label,
        })
    return grouped


# --- epub --------------------------------------------------------------------

EPUB_CSS = """\
body{font-family:serif;line-height:1.65;margin:0 6%}
h1{font-size:1.5em;font-weight:700;margin:1em 0 .2em}
h1.part{font-size:.9em;font-weight:400;color:#b82219;
  border-bottom:2px solid #b82219;padding-bottom:.35em}
h2.sec{font-size:1.15em;color:#b82219;border-bottom:1px solid #c2a96f;
  padding-bottom:.2em;margin:1.6em 0 .5em}
h2.sec .n{float:right;font-size:.8em;font-weight:400}
ol.rows{list-style:none;margin:0;padding:0}
ol.rows li{margin:0 0 .9em}
ol.rows .hl{font-weight:700}
.src{font-size:.8em;color:#6f5f42}
article{margin:0 0 1.4em}
article h3{font-size:1.05em;font-weight:700;margin:0 0 .3em}
.meta{font-size:.8em;color:#6f5f42;margin:.4em 0 0}
"""


def build_epub(grouped, run_dt, out_path):
    bd = to_bd(run_dt)
    ed_label, _ = edition(bd)
    title = f"{ed_label} \u00b7 {bn_date(bd)}, {bn_time(bd)}"

    book = epub.EpubBook()
    book.set_identifier(f"bn-news-digest-{run_dt.isoformat()}")
    book.set_title(title)
    book.set_language("bn")

    css = epub.EpubItem(uid="style", file_name="style/panjika.css",
                        media_type="text/css", content=EPUB_CSS)
    book.add_item(css)

    def _sec(section, n):
        return (f'<h2 class="sec">{SECTION_BN[section]}'
                f'<span class="n">{bn_num(n)}</span></h2>')

    digest_html = f'<h1>{esc(title)}</h1>'
    for section in SECTIONS:
        items = grouped.get(section, [])
        if not items:
            continue
        fname = f"{section.lower()}.xhtml"
        digest_html += _sec(section, len(items)) + '<ol class="rows">'
        for n, a in enumerate(items):
            digest_html += (
                f'<li><a class="hl" href="{fname}#a{n}">{esc(a["headline"])}</a>'
                f' <span class="src">{esc(a["source"])}</span></li>'
            )
        digest_html += "</ol>"
    digest_ch = epub.EpubHtml(title="সূচি", file_name="digest.xhtml", lang="bn")
    digest_ch.content = digest_html
    digest_ch.add_item(css)
    book.add_item(digest_ch)

    chapters = [digest_ch]
    for section in SECTIONS:
        items = grouped.get(section, [])
        if not items:
            continue
        html = f'<h1>{SECTION_BN[section]}</h1>'
        for n, a in enumerate(items):
            link = a.get("link")
            origin = (f' \u2014 <a href="{esc(link)}">\u09ae\u09c2\u09b2 \u09aa\u09cd\u09b0\u09a4\u09bf\u09ac\u09c7\u09a6\u09a8</a>'
                      if link else "")
            byline = f' \u2014 {esc(a["author"])}' if a.get("author") else ""
            html += (
                f'<article id="a{n}"><h3>{esc(a["headline"])}</h3>'
                f'<p>{esc(a["excerpt"])}</p>'
                f'<p class="meta">{esc(a["source"])}{byline}{origin}</p></article>'
            )
        ch = epub.EpubHtml(title=SECTION_BN[section], file_name=f"{section.lower()}.xhtml", lang="bn")
        ch.content = html
        ch.add_item(css)
        book.add_item(ch)
        chapters.append(ch)

    book.toc = chapters
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav"] + chapters
    epub.write_epub(str(out_path), book)


# --- site (GitHub Pages archive) --------------------------------------------

def esc(t):
    """Feed titles/excerpts are plain text (feedparser decodes entities,
    trafilatura returns text) -- so they need escaping on the way into HTML,
    not passing through raw."""
    return h_esc(str(t or ""), quote=True)


def safe_url(url):
    """Feed-provided links/images get interpolated into href=/src=... on the
    published site, in EPUB chapters and in subscriber email. Escaping alone
    does not defuse a `javascript:`/`data:`/`vbscript:` URL -- those stay
    live -- so anything that isn't plain http(s) is dropped. Applied at each
    sink that emits one, not only once upstream, so it holds however the
    article dict was built. Sources are third-party RSS, i.e. untrusted.
    """
    url = (url or "").strip()
    return url if url.lower().startswith(("http://", "https://")) else ""


def _row_html(a):
    """One headline. A real <a href> to the source (works with JS off), plus
    data-* the modal script reads to show the full detail without a second
    request."""
    href = esc(a["link"] or "#")
    meta = esc(a["source"])
    if a["time"]:
        meta += f" · {esc(a['time'])}"
    return (
        f'<li><a class=row href="{href}" data-headline="{esc(a["headline"])}" '
        f'data-source="{esc(a["source"])}" data-time="{esc(a["time"])}" '
        f'data-author="{esc(a["author"])}" data-image="{esc(a["image"])}" '
        f'data-link="{esc(a["link"])}" data-excerpt="{esc(a["excerpt"])}">'
        f'<span class=row-hl>{esc(a["headline"])}</span>'
        f'<span class=row-meta>{meta}</span></a></li>'
    )


def _panel_html(grouped, idx):
    """Category chips (quick nav) + the categories themselves, each a plain
    headline list -- no descriptions here by design (see docs/adr/0006);
    full detail is only ever in the modal."""
    present = [s for s in SECTIONS if grouped.get(s)]
    if not present:
        return '<p class=empty>এই সংস্করণে এখনও কোনো খবর নেই।</p>'
    chips = "".join(
        f'<a class=chip href="#p{idx}-{s}">{SECTION_BN[s]}'
        f'<span class=chip-n>{bn_num(len(grouped[s]))}</span></a>'
        for s in present
    )
    cats = "".join(
        f'<section class=cat id="p{idx}-{s}"><h3 class=cat-head><span>{SECTION_BN[s]}</span>'
        f'<span class=cat-n>{bn_num(len(grouped[s]))}</span></h3>'
        f'<ul class=rows>{"".join(_row_html(a) for a in grouped[s])}</ul></section>'
        for s in present
    )
    return f'<nav class=chips>{chips}</nav><div class=catgrid>{cats}</div>'


MODAL_HTML = (
    '<dialog id=modal class=modal>'
    '<button type=button class=modal-close aria-label="বন্ধ করুন">\u00d7</button>'
    '<img class=m-img alt="" hidden>'
    '<div class=modal-body>'
    '<h3 class=m-hl></h3>'
    '<p class=modal-meta><span class=m-src></span><span class=m-author hidden></span>'
    '<span class=m-time></span></p>'
    '<p class=m-excerpt></p>'
    '<a class=m-link href="#" target=_blank rel="noopener noreferrer" hidden>মূল প্রতিবেদন পড়ুন \u2192</a>'
    '</div></dialog>'
)

# Vanilla, ~35 lines. Reads the clicked row's data-* into the one modal and
# opens it -- CSS (@starting-style, see STYLE_CSS) handles the open fade/scale
# on its own. Closing needs this script either way: a <dialog> has no built-in
# "about to close" moment to animate against, so close() is deferred until a
# .closing transition finishes (or skipped straight to close() if the visitor
# prefers reduced motion).
MODAL_SCRIPT = """\
<script>
(function(){
  var modal = document.getElementById('modal');
  if (!modal) return;
  var reduceMotion = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  function closeModal(){
    if (!modal.open || modal.classList.contains('closing')) return;
    if (reduceMotion) { modal.close(); return; }
    modal.classList.add('closing');
    modal.addEventListener('transitionend', function onEnd(e){
      if (e.target !== modal) return;
      modal.removeEventListener('transitionend', onEnd);
      modal.classList.remove('closing');
      modal.close();
    }, { once: true });
  }

  document.addEventListener('click', function(e){
    if (e.target.closest('.modal-close')) { closeModal(); return; }
    var row = e.target.closest('.row');
    if (!row) return;
    e.preventDefault();
    modal.querySelector('.m-hl').textContent = row.dataset.headline;
    modal.querySelector('.m-src').textContent = row.dataset.source;
    modal.querySelector('.m-time').textContent = row.dataset.time || '';
    modal.querySelector('.m-excerpt').textContent = row.dataset.excerpt || '';
    var author = modal.querySelector('.m-author');
    author.textContent = row.dataset.author || '';
    author.hidden = !row.dataset.author;
    var img = modal.querySelector('.m-img');
    if (row.dataset.image) { img.src = row.dataset.image; img.hidden = false; }
    else { img.hidden = true; img.removeAttribute('src'); }
    var link = modal.querySelector('.m-link');
    if (row.dataset.link) { link.href = row.dataset.link; link.hidden = false; }
    else { link.hidden = true; }
    modal.showModal();
  });
  modal.addEventListener('click', function(e){ if (e.target === modal) closeModal(); });
  modal.addEventListener('cancel', function(e){ e.preventDefault(); closeModal(); });
})();
</script>
"""


MIXPANEL_SCRIPT = r"""<script type="text/javascript">
  (function(e,c){if(!c.__SV){var l,h;window.mixpanel=c;c._i=[];c.init=function(q,r,f){function t(d,a){var g=a.split(".");2==g.length&&(d=d[g[0]],a=g[1]);d[a]=function(){d.push([a].concat(Array.prototype.slice.call(arguments,0)))}}var b=c;"undefined"!==typeof f?b=c[f]=[]:f="mixpanel";b.people=b.people||[];b.toString=function(d){var a="mixpanel";"mixpanel"!==f&&(a+="."+f);d||(a+=" (stub)");return a};b.people.toString=function(){return b.toString(1)+".people (stub)"};l="disable time_event track track_pageview track_links track_forms track_with_groups add_group set_group remove_group register register_once alias unregister identify name_tag set_config reset opt_in_tracking opt_out_tracking has_opted_in_tracking has_opted_out_tracking clear_opt_in_out_tracking start_batch_senders start_session_recording stop_session_recording people.set people.set_once people.unset people.increment people.append people.union people.track_charge people.clear_charges people.delete_user people.remove".split(" ");
  for(h=0;h<l.length;h++)t(b,l[h]);var n="set set_once union unset remove delete".split(" ");b.get_group=function(){function d(p){a[p]=function(){b.push([g,[p].concat(Array.prototype.slice.call(arguments,0))])}}for(var a={},g=["get_group"].concat(Array.prototype.slice.call(arguments,0)),m=0;m<n.length;m++)d(n[m]);return a};c._i.push([q,r,f])};c.__SV=1.2;var k=e.createElement("script");k.type="text/javascript";k.async=!0;k.src="undefined"!==typeof MIXPANEL_CUSTOM_LIB_URL?MIXPANEL_CUSTOM_LIB_URL:"file:"===
  e.location.protocol&&"//cdn.mxpnl.com/libs/mixpanel-2-latest.min.js".match(/^\/\//)?"https://cdn.mxpnl.com/libs/mixpanel-2-latest.min.js":"//cdn.mxpnl.com/libs/mixpanel-2-latest.min.js";e=e.getElementsByTagName("script")[0];e.parentNode.insertBefore(k,e)}})(document,window.mixpanel||[])

  mixpanel.init('a4b8153b14694027e13629c952c58fdb', {
    autocapture: true,
    record_sessions_percent: 100,
  })
</script>
"""


def _doc(title, body_html, extra_head=""):
    return (
        "<!doctype html><html lang=bn><head><meta charset=utf-8>"
        '<meta name=viewport content="width=device-width,initial-scale=1">'
        "<meta name=color-scheme content=light>"
        f"<title>{title}</title>{FONT_LINKS}{extra_head}{MIXPANEL_SCRIPT}"
        "</head><body>"
        f"{body_html}"
        "</body></html>"
    )


def render_run_html(grouped, run_dt):
    """Standalone permalink for one edition -- used by RSS/OPDS and as a
    direct link. Headlines link straight to the source (no modal needed on
    a page that's only ever read, not interacted with)."""
    bd = to_bd(run_dt)
    ed_label, ed_cls = edition(bd)
    title = f"{ed_label} \u00b7 {bn_date(bd)}"
    body = (
        '<link rel=stylesheet href="../style.css">'
        '<a class=back href="../index.html">\u2190 \u0986\u099c\u0995\u09c7\u09b0 \u09b8\u09ac \u09b8\u0982\u09b8\u09cd\u0995\u09b0\u09a3</a>'
        f'<header class=masthead><p class=eyebrow>{ed_label}</p>'
        f'<h1 class=date>{bn_date(bd)}<span class=weekday>{bn_weekday(bd)}, {bn_time(bd)}</span></h1>'
        f'<div class="horizon {ed_cls}"></div></header>'
        f'<main>{_panel_html(grouped, "r")}</main>'
    )
    return _doc(
        f"{ed_label} \u00b7 {bn_date(bd)} \u2014 \u09ac\u09be\u0982\u09b2\u09be \u09b8\u0982\u09ac\u09be\u09a6 \u09b8\u0982\u0995\u09cd\u09b7\u09c7\u09aa",
        body,
    )


def render_index(manifest):
    """Today's editions as tabs (CSS-only, driven by radio :checked ->
    :has(); default-checked tab is manifest[0] = the latest, so opening the
    link always lands on the current edition), a 1/2-column toggle for the
    category grid, and a shared modal for detail. See docs/adr/0006."""
    editions = manifest[:2]  # a news-day is at most one dawn + one dusk run
    if not editions:
        body = (
            "<header class=masthead>"
            "<p class=eyebrow>বাংলা সংবাদ সংক্ষেপ</p>"
            "</header>"
            "<p class=colophon>আজকের কোনো সংস্করণ এখনো প্রকাশ হয়নি।</p>"
        )
        return _doc("বাংলা সংবাদ সংক্ষেপ", body, "<link rel=stylesheet href=style.css>")

    bd0 = to_bd(datetime.fromisoformat(editions[0]["dt"]))
    ed_label0, _ = edition(bd0)

    radios, tabs, panels = "", "", ""
    for i, r in enumerate(editions):
        bd = to_bd(datetime.fromisoformat(r["dt"]))
        ed_label, _ = edition(bd)
        checked = " checked" if i == 0 else ""
        radios += f'<input type=radio name=ed id=ed{i} class=vh{checked}>'
        tabs += f'<label class=tab for=ed{i}>{ed_label}<span class=tab-sub>{bn_time(bd)}</span></label>'
        panels += f'<section class=panel id=p{i}>{_panel_html(r.get("grouped", {}), i)}</section>'

    tabs_html = f'<div class=tabs role=tablist>{tabs}</div>' if len(editions) > 1 else ""

    body = (
        "<header class=masthead>"
        "<p class=eyebrow>বাংলা সংবাদ সংক্ষেপ</p>"
        f'<h1 class=date>{bn_date(bd0)}<span class=weekday>{bn_weekday(bd0)}</span></h1>'
        "<p class=feeds><a href=feed.xml>RSS</a><a href=opds.xml>OPDS</a></p>"
        "<div class=horizon></div></header>"
        f"<main>{radios}{tabs_html}"
        '<div class=colsbar aria-label="কলাম">'
        '<input type=radio name=cols id=c1 class=vh checked><label for=c1>১ কলাম</label>'
        '<input type=radio name=cols id=c2 class=vh><label for=c2>২ কলাম</label>'
        "</div>"
        f"<div class=panels>{panels}</div></main>"
        f"{MODAL_HTML}"
        "<footer class=colophon><p>আজকের সংস্করণ -- পরবর্তী সংস্করণ ভোর/সন্ধ্যা ৬টায়।</p></footer>"
        f"{MODAL_SCRIPT}"
    )
    return _doc(
        f"{ed_label0} \u00b7 {bn_date(bd0)} \u2014 \u09ac\u09be\u0982\u09b2\u09be \u09b8\u0982\u09ac\u09be\u09a6 \u09b8\u0982\u0995\u09cd\u09b7\u09c7\u09aa",
        body,
        "<link rel=stylesheet href=style.css>"
        '<link rel=alternate type=application/rss+xml title="\u09ac\u09be\u0982\u09b2\u09be \u09b8\u0982\u09ac\u09be\u09a6 \u09b8\u0982\u0995\u09cd\u09b7\u09c7\u09aa RSS" href=feed.xml>',
    )


def build_rss(manifest):
    """RSS 2.0 feed of runs, newest first -- one <item> per edition, the
    headline list (grouped, straight from the manifest -- no re-reading
    already-written HTML off disk) inlined as <description>."""
    items = []
    for r in manifest[:RSS_ITEM_CAP]:
        dt = datetime.fromisoformat(r["dt"])
        bd = to_bd(dt)
        ed_label, _ = edition(bd)
        title = f"{ed_label} — {bn_date(bd)}, {bn_time(bd)}"
        link = SITE_URL + r["file"]
        items.append(
            "<item>"
            f"<title>{xml_escape(title)}</title>"
            f"<link>{xml_escape(link)}</link>"
            f"<guid>{xml_escape(link)}</guid>"
            f"<pubDate>{format_datetime(dt)}</pubDate>"
            f"<description>{xml_escape(_panel_html(r.get('grouped', {}), 'r'))}</description>"
            "</item>"
        )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<rss version="2.0"><channel>'
        "<title>বাংলা সংবাদ সংক্ষেপ</title>"
        f"<link>{SITE_URL}</link>"
        "<description>প্রতিদিন ০৬টা ও ১৮টায় নতুন বাংলা সংবাদ সংক্ষেপ</description>"
        "<language>bn</language>"
        + "".join(items) +
        "</channel></rss>"
    )


def build_opds(manifest):
    """Minimal OPDS 1.2 acquisition feed (Atom + acquisition links) -- only
    entries with an archived EPUB get a download link."""
    entries = []
    for r in manifest[:RSS_ITEM_CAP]:
        epub_name = Path(r["file"]).stem + ".epub"
        if not (SITE_DIR / "epubs" / epub_name).exists():
            continue
        dt = datetime.fromisoformat(r["dt"])
        bd = to_bd(dt)
        ed_label, _ = edition(bd)
        title = f"{ed_label} — {bn_date(bd)}, {bn_time(bd)}"
        html_link = SITE_URL + r["file"]
        epub_link = f"{SITE_URL}epubs/{epub_name}"
        desc = ", ".join(f"{SECTION_BN.get(k, k)} {bn_num(v)}" for k, v in r["counts"].items())
        entries.append(
            "<entry>"
            f"<title>{xml_escape(title)}</title>"
            f"<id>{xml_escape(html_link)}</id>"
            f"<updated>{dt.isoformat()}</updated>"
            f'<content type="text">{xml_escape(desc)}</content>'
            f'<link rel="http://opds-spec.org/acquisition" href="{xml_escape(epub_link)}" type="application/epub+zip"/>'
            f'<link rel="alternate" href="{xml_escape(html_link)}" type="text/html"/>'
            "</entry>"
        )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<feed xmlns="http://www.w3.org/2005/Atom" xmlns:opds="http://opds-spec.org/2010/catalog">'
        f"<id>{SITE_URL}opds.xml</id>"
        "<title>বাংলা সংবাদ সংক্ষেপ</title>"
        f"<updated>{datetime.now(timezone.utc).isoformat()}</updated>"
        f'<link rel="self" href="{SITE_URL}opds.xml" type="application/atom+xml;profile=opds-catalog;kind=acquisition"/>'
        + "".join(entries) +
        "</feed>"
    )


def _prune_before(manifest, cutoff_date):
    """Drop (and delete the archived .html/.epub for) every run older than
    cutoff_date (a BD-local date()). Called on the first edition of a new
    day, so the site/feed only ever hold "today so far"."""
    kept, dropped = [], []
    for r in manifest:
        target = kept if to_bd(datetime.fromisoformat(r["dt"])).date() >= cutoff_date else dropped
        target.append(r)
    for r in dropped:
        (SITE_DIR / r["file"]).unlink(missing_ok=True)
        (SITE_DIR / "epubs" / (Path(r["file"]).stem + ".epub")).unlink(missing_ok=True)
    return kept


def update_site(grouped, run_dt, epub_path=None):
    SITE_DIR.mkdir(exist_ok=True)
    (SITE_DIR / "runs").mkdir(exist_ok=True)
    (SITE_DIR / "epubs").mkdir(exist_ok=True)

    bd_now = to_bd(run_dt)
    _, ed_cls = edition(bd_now)
    manifest = json.loads(RUNS_MANIFEST.read_text()) if RUNS_MANIFEST.exists() else []
    if ed_cls == "dawn":  # morning edition: drop everything from before today
        manifest = _prune_before(manifest, bd_now.date())

    fname = f"runs/{run_dt.strftime('%Y-%m-%d-%H%M')}.html"
    (SITE_DIR / fname).write_text(render_run_html(grouped, run_dt))
    if epub_path and epub_path.exists():
        (SITE_DIR / "epubs" / (Path(fname).stem + ".epub")).write_bytes(epub_path.read_bytes())

    counts = {s: len(grouped.get(s, [])) for s in SECTIONS if grouped.get(s)}
    # Full article data lives here now, not just counts -- index/RSS/OPDS
    # read it straight from the manifest instead of re-parsing rendered HTML
    # (see docs/adr/0006). Bounded: pruning above keeps this at <= 2 runs.
    manifest.insert(0, {"dt": run_dt.isoformat(), "file": fname, "counts": counts, "grouped": grouped})
    RUNS_MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2))

    (SITE_DIR / "index.html").write_text(render_index(manifest))
    (SITE_DIR / "style.css").write_text(STYLE_CSS)
    (SITE_DIR / "feed.xml").write_text(build_rss(manifest))
    (SITE_DIR / "opds.xml").write_text(build_opds(manifest))


# --- email -------------------------------------------------------------------

def parse_recipients(raw):
    """EMAIL_TO secret holds a comma/newline/semicolon-separated list --
    grows into a subscriber list without touching code or committing PII
    to this (public) repo."""
    return [e.strip() for e in re.split(r"[,\n;]+", raw) if e.strip()]


def render_email_html(grouped, run_dt):
    """Digest-only, inline styles, no webfonts -- mail clients strip <style>
    and @import. Same two inks as the site; links go to the source article,
    the full excerpts are in the attached EPUB."""
    bd = to_bd(run_dt)
    ed_label, ed_cls = edition(bd)
    head_bg, head_fg = ("#e7d5a8", "#191410") if ed_cls == "dawn" else ("#191410", "#f1e4c3")
    accent = "#b82219" if ed_cls == "dawn" else "#f0674c"

    rows = ""
    for section in SECTIONS:
        items = grouped.get(section, [])
        if not items:
            continue
        rows += (
            f'<tr><td style="padding:26px 0 6px"><table width="100%" cellpadding="0" cellspacing="0"><tr>'
            f'<td style="font:700 17px Georgia,serif;color:#b82219;white-space:nowrap">{SECTION_BN[section]}</td>'
            '<td width="100%" style="border-bottom:2px solid #b82219;'
            'border-top:1px solid #191410;height:5px;font-size:0;line-height:0">&nbsp;</td>'
            f'<td style="font:600 13px Arial,sans-serif;color:#b82219;padding-left:10px">{bn_num(len(items))}</td>'
            f"</tr></table></td></tr>"
        )
        for a in items:
            link = a.get("link")
            hl_style = "font:700 16px Georgia,serif;color:#191410;text-decoration:none;line-height:1.45"
            headline = (
                f'<a href="{esc(link)}" style="{hl_style}">{esc(a["headline"])}</a>'
                if link else f'<span style="{hl_style}">{esc(a["headline"])}</span>'
            )
            rows += (
                '<tr><td style="padding:11px 0;border-bottom:1px solid #c2a96f">'
                f"{headline}"
                f'<div style="font:12px Arial,sans-serif;color:#6f5f42;padding-top:3px">{esc(a["source"])}</div>'
                f'<div style="font:14px Georgia,serif;color:#6f5f42;line-height:1.55;'
                f'padding-top:4px">{esc(make_teaser(a["excerpt"]))}</div>'
                "</td></tr>"
            )

    total = sum(len(v) for v in grouped.values())
    return (
        '<!doctype html><html lang="bn"><body style="margin:0;padding:0;'
        'background:#f1e4c3"><table width="100%" cellpadding="0" cellspacing="0" '
        'style="background:#f1e4c3"><tr><td align="center" style="padding:22px 14px 40px">'
        '<table cellpadding="0" cellspacing="0" width="560" style="max-width:560px;width:100%">'
        f'<tr><td style="background:{head_bg};color:{head_fg};border:2px solid #191410;padding:14px 16px">'
        f'<div style="font:600 13px Arial,sans-serif;color:{accent};'
        f'padding-bottom:4px">{ed_label} \u00b7 {bn_weekday(bd)}</div>'
        f'<div style="font:700 26px Georgia,serif;line-height:1.2">{bn_date(bd)}'
        f'<span style="font:400 15px Arial,sans-serif;color:{accent};'
        f'padding-left:10px">{bn_time(bd)}</span></div>'
        f'<div style="font:600 13px Arial,sans-serif;color:{accent};'
        f'border-top:1px solid #c2a96f;margin-top:12px;padding-top:8px">'
        f'{bn_num(total)}\u099f\u09bf \u0996\u09ac\u09b0</div>'
        "</td></tr>"
        f"{rows}"
        '<tr><td style="padding:22px 0 0;border-top:3px solid #191410;margin-top:20px;'
        'font:13px Arial,sans-serif;color:#6f5f42;line-height:1.6">'
        '\u09aa\u09c1\u09b0\u09cb \u09b2\u09c7\u0996\u09be\u0982\u09b6 \u09b8\u0982\u09af\u09c1\u0995\u09cd\u09a4 EPUB \u09ab\u09be\u0987\u09b2\u09c7\u0964 '
        f'<a href="{esc(SITE_URL)}" style="color:#b82219">\u0993\u09df\u09c7\u09ac\u09c7 \u09a6\u09c7\u0996\u09c1\u09a8</a>'
        "</td></tr></table></td></tr></table></body></html>"
    )


def send_email(epub_path, run_dt, grouped):
    to_addrs = parse_recipients(os.environ["EMAIL_TO"])
    if not to_addrs:
        raise RuntimeError("EMAIL_TO has no valid addresses")
    smtp_host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.environ.get("SMTP_PORT", "465"))
    smtp_user = os.environ["SMTP_USER"]
    smtp_pass = os.environ["SMTP_PASS"]

    bd = to_bd(run_dt)
    ed_label, _ = edition(bd)
    counts = ", ".join(
        f"{SECTION_BN[s]} {bn_num(len(grouped.get(s, [])))}" for s in SECTIONS if grouped.get(s)
    )
    msg = EmailMessage()
    msg["Subject"] = f"{ed_label} \u00b7 {bn_date(bd)}, {bn_time(bd)}"
    msg["From"] = smtp_user
    msg["To"] = smtp_user  # subscribers are Bcc'd -- they shouldn't see each other's addresses
    msg.set_content(
        f"{ed_label} \u2014 {bn_date(bd)}, {bn_time(bd)}\n{counts}\n\n"
        f"\u09aa\u09c1\u09b0\u09cb \u09b8\u0982\u0995\u09cd\u09b7\u09c7\u09aa \u09b8\u0982\u09af\u09c1\u0995\u09cd\u09a4 EPUB \u09ab\u09be\u0987\u09b2\u09c7\u0964 {SITE_URL}"
    )
    msg.add_alternative(render_email_html(grouped, run_dt), subtype="html")
    msg.add_attachment(
        epub_path.read_bytes(), maintype="application", subtype="epub+zip",
        filename=epub_path.name,
    )

    with smtplib.SMTP_SSL(smtp_host, smtp_port) as smtp:
        smtp.login(smtp_user, smtp_pass)
        refused = smtp.sendmail(smtp_user, to_addrs, msg.as_string())
    if refused:
        log.warning("some recipients refused: %s", refused)


# --- main --------------------------------------------------------------------

def main():
    now = datetime.now(timezone.utc)
    state = load_state()

    articles = []
    seen_this_run = set()
    for source in SOURCES:
        articles.extend(fetch_new_entries(source, state, now, seen_this_run))

    if not articles:
        log.info("no new articles this run, skipping digest")
        save_state(state)
        return

    log.info("collecting %d articles (no AI summary)", len(articles))
    results = collect_results(articles)
    grouped = group_by_section(articles, results)

    epub_path = ROOT / f"digest-{now.strftime('%Y%m%d-%H%M')}.epub"
    build_epub(grouped, now, epub_path)
    update_site(grouped, now, epub_path=epub_path)
    save_state(state)

    if parse_recipients(os.environ.get("EMAIL_TO", "")):
        try:
            retry(lambda: send_email(epub_path, now, grouped), what="email send")
        except Exception:
            log.exception("email send failed after retries -- digest is still on the site archive")
    else:
        log.info("EMAIL_TO not set -- skipping email, digest is still on the site archive")
    epub_path.unlink(missing_ok=True)  # not archived in git either way

    log.info("run complete")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log.exception("run failed")
        sys.exit(1)
