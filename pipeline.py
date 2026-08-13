"""Bangla news digest: fetch -> extract -> collect (no AI summary, see
docs/adr/0004) -> EPUB + HTML archive page -> email. Run twice a day by
GitHub Actions.

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
from xml.sax.saxutils import escape as xml_escape

import feedparser
import trafilatura
from ebooklib import epub

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
    """(label, css-class) for the twice-daily run cadence -- the one piece
    of structure in this UI that actually encodes something (which of the
    two daily runs this is), so it gets its own visual treatment."""
    return ("প্রভাতী সংস্করণ", "dawn") if dt.hour < 12 else ("সান্ধ্য সংস্করণ", "dusk")


def bn_num(n):
    return str(n).translate(_BN_DIGITS)


PART_TOC = "সূচি"        # the headline list -- "contents"
PART_FULL = "বিস্তারিত"   # the excerpts


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
    "?family=Anek+Bangla:wdth,wght@75..100,400..700"
    "&amp;family=Mina:wght@400;700"
    "&amp;family=Noto+Serif+Bengali:wght@500;700;800"
    '&amp;display=swap">'
)

STYLE_CSS = """\
/* Two-ink panjika: black + vermilion on saffron newsprint. No third colour
   anywhere -- links are vermilion, the evening edition is a reversed plate
   (ink-filled block) rather than a new hue. That constraint is the design. */
/* Tints are set by contrast, not by eye: the vermilion has to clear 4.5:1 on
   both the paper and the tint block, which is what fixes --block and --red
   at these values. --red-rev is the same ink with no paper behind it. */
:root{
  --stock:#f1e4c3; --block:#f0e2be; --ink:#191410;
  --red:#b82219;  --red-rev:#f0674c; --rule:#c2a96f; --faded:#6f5f42;
  --display:'Noto Serif Bengali',Georgia,serif;
  --body:'Mina','Noto Sans Bengali',system-ui,-apple-system,sans-serif;
  --util:'Anek Bangla','Noto Sans Bengali',system-ui,-apple-system,sans-serif;
  --grain:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='140' height='140'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='.85' numOctaves='3'/%3E%3C/filter%3E%3Crect width='140' height='140' filter='url(%23n)' opacity='.05'/%3E%3C/svg%3E");
}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{max-width:41rem;margin:0 auto;padding:1.75rem 1.15rem 4rem;
  font-family:var(--body);font-size:1.02rem;line-height:1.7;
  color:var(--ink);background:var(--stock) var(--grain) repeat}
a{color:var(--red);text-decoration:none}
a:hover{text-decoration:underline;text-underline-offset:.18em}
a:focus-visible{outline:2px solid var(--red);outline-offset:3px}

/* --- printed rules --------------------------------------------------- */
.rule2{border:0;height:3px;margin:0;
  border-top:3px solid var(--ink);border-bottom:2px solid var(--red)}

/* --- masthead -------------------------------------------------------- */
.masthead{margin:0 0 2.5rem}
.masthead h1{font-family:var(--display);font-weight:800;font-size:clamp(1.7rem,7vw,2.5rem);
  line-height:1.25;margin:.85rem 0 .3rem}
.masthead .cadence{font-family:var(--util);font-variation-settings:'wdth' 88;
  font-size:.95rem;color:var(--faded);margin:0 0 .9rem}
.masthead .feeds{margin:0 0 .85rem;display:flex;gap:.4rem}
.feeds a{font-family:var(--util);font-variation-settings:'wdth' 82,'wght' 600;
  font-size:.72rem;letter-spacing:.1em;padding:.16rem .6rem;
  border:1.5px solid var(--rule);color:var(--faded)}
.feeds a:hover{border-color:var(--red);color:var(--red);text-decoration:none}
.back{display:inline-block;margin:0 0 1.1rem;font-family:var(--util);
  font-variation-settings:'wdth' 85;font-size:.82rem;color:var(--faded)}
.back:hover{color:var(--red)}

/* --- edition block (the panjika day-page head) ----------------------- */
.edition{background:var(--block);border:2px solid var(--ink);
  padding:.85rem 1.05rem .95rem;margin:0 0 2rem}
/* No letter-spacing on Bangla anywhere: tracking pulls the parts of an
   akshara apart, so the Latin small-caps label trick doesn't transfer.
   Weight, size and the second ink carry the label hierarchy instead.
   .feeds is the one exception -- RSS/OPDS are Latin. */
.edition .prahar{display:flex;justify-content:space-between;align-items:baseline;
  gap:1rem;margin:0 0 .2rem;font-family:var(--util);
  font-variation-settings:'wdth' 86,'wght' 600;
  font-size:.86rem;color:var(--red)}
.edition .weekday{font-variation-settings:'wdth' 86,'wght' 500;color:var(--faded)}
.edition .date{font-family:var(--display);font-weight:800;
  font-size:clamp(1.45rem,5.5vw,2rem);line-height:1.2;margin:0;
  display:flex;flex-wrap:wrap;align-items:baseline;gap:.6rem}
.edition .clock{font-family:var(--util);font-variation-settings:'wdth' 86,'wght' 500;
  font-size:.98rem;font-weight:400;color:var(--red)}
/* reversed plate: same two inks, no paper behind them */
.edition.dusk{background:var(--ink);color:var(--stock);border-color:var(--ink)}
.edition.dusk .prahar,.edition.dusk .clock,.edition.dusk .seg-n{color:var(--red-rev)}
.edition.dusk .weekday{color:#a89778}
.edition.dusk .seg{border-color:var(--red-rev)}
.edition.dusk .seg + .seg{box-shadow:inset 1px 0 0 #4a3f31}
.edition.dusk .seg a{color:var(--stock)}

/* --- SIGNATURE: the tally rule -------------------------------------- */
/* One segment per section, width proportional to how many articles landed
   in it. Shows where the day's weight actually sits, and is the section nav. */
.tally{display:flex;list-style:none;margin:.95rem 0 0;padding:0;
  border-top:1px solid var(--rule)}
.edition.dusk .tally{border-top-color:#4a3f31}
/* flex-basis is a legibility floor: every section keeps a readable label,
   and only the space above that floor is shared out by article count. */
.seg{flex:var(--n) 1 4.6rem;min-width:0;overflow:hidden;
  border-top:3px solid var(--red);
  transform-origin:left center;animation:ink .5s cubic-bezier(.2,.7,.3,1) both;
  animation-delay:calc(var(--i) * 70ms)}
.seg + .seg{box-shadow:inset 1px 0 0 var(--rule)}
.seg a{display:block;padding:.4rem .5rem .1rem;color:var(--ink)}
.seg a:hover{text-decoration:none;background:rgba(184,34,25,.12)}
.seg-name{display:block;font-family:var(--util);
  font-variation-settings:'wdth' 80,'wght' 600;font-size:.8rem;
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.seg-n{display:block;font-family:var(--display);font-weight:700;
  font-size:1.05rem;line-height:1.2;color:var(--red)}
@keyframes ink{from{transform:scaleX(0);opacity:0}to{transform:scaleX(1);opacity:1}}

/* --- part headings (\u09b8\u09c2\u099a\u09bf / \u09ac\u09bf\u09b8\u09cd\u09a4\u09be\u09b0\u09bf\u09a4) -------------------------------- */
.part{font-family:var(--util);font-variation-settings:'wdth' 84,'wght' 600;
  font-size:.88rem;color:var(--red);margin:0 0 1.1rem;font-weight:400}
.detail{margin-top:3rem}
.detail .part{padding-top:1.1rem;border-top:3px solid var(--ink)}

/* --- section heading with two-ink leader ---------------------------- */
.sec{display:flex;align-items:center;gap:.7rem;margin:1.9rem 0 .55rem;
  font-family:var(--display);font-weight:700;font-size:1.15rem;line-height:1.3}
.digest .sec:first-of-type,.detail .sec:first-of-type{margin-top:0}
.sec-fill{flex:1;height:5px;border-top:1px solid var(--ink);border-bottom:2px solid var(--red)}
.sec-n{font-family:var(--util);font-variation-settings:'wdth' 84,'wght' 600;
  font-size:.85rem;color:var(--red)}

/* --- digest rows ---------------------------------------------------- */
.rows{list-style:none;margin:0;padding:0}
.rows > li{padding:.62rem 0;border-bottom:1px solid var(--rule)}
.rows > li:last-child{border-bottom:none}
.row{display:flex;align-items:flex-end;gap:.3rem}
.row .hl{flex:1 1 auto;min-width:0;font-family:var(--display);font-weight:700;
  font-size:1.02rem;line-height:1.45;color:var(--ink)}
.row .hl:hover{color:var(--red);text-decoration:none}
.row .dots{flex:1 0 1.5rem;height:0;margin-bottom:.42em;
  border-bottom:2px dotted var(--rule)}
.row .src{flex:0 0 auto;font-family:var(--util);
  font-variation-settings:'wdth' 82;font-size:.76rem;
  color:var(--faded);white-space:nowrap}
.teaser{margin:.18rem 0 0;font-size:.92rem;line-height:1.6;color:var(--faded)}

/* --- detail articles ------------------------------------------------ */
.detail article{margin:0 0 1.6rem;padding:0 0 1.6rem;border-bottom:1px solid var(--rule)}
.detail article:last-child{border-bottom:none}
.detail h4{font-family:var(--display);font-weight:700;font-size:1.16rem;
  line-height:1.42;margin:0 0 .45rem}
.detail p{margin:0 0 .5rem}
.meta{display:flex;flex-wrap:wrap;gap:.6rem;margin:.55rem 0 0;
  font-family:var(--util);font-variation-settings:'wdth' 84;font-size:.78rem;
  color:var(--faded)}
.meta .src{color:var(--faded)}

/* --- index sheets --------------------------------------------------- */
.sheet{margin:0 0 3.25rem}
.sheet:last-child{margin-bottom:1.5rem}
.more{margin:1.4rem 0 0;font-family:var(--util);
  font-variation-settings:'wdth' 84,'wght' 600;font-size:.88rem}
.colophon{margin:2.5rem 0 0;padding-top:.9rem;border-top:3px solid var(--ink);
  font-family:var(--util);font-variation-settings:'wdth' 86;
  font-size:.8rem;color:var(--faded)}
.colophon p{margin:.35rem 0}

/* degrade gracefully for pre-redesign archived fragments */
.digest ul:not(.rows):not(.tally){padding-left:1.1rem}

@media(max-width:34rem){
  .row{flex-wrap:wrap}
  .row .dots{display:none}
  .row .src{margin-left:auto;margin-top:.1rem}
  .seg{flex-basis:3.5rem}
  .seg a{padding:.35rem .35rem .1rem}
  .seg-name{font-size:.68rem}
}
@media(prefers-reduced-motion:reduce){
  .seg{animation:none}
}
@media print{
  body{background:#fff;max-width:none}
  .back,.feeds,.more{display:none}
  .edition.dusk{background:#fff;color:#000}
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

def fetch_new_entries(source, state, now):
    """Return new articles (dicts) from one source's feed. Never raises --
    a dead source is logged and skipped, the run continues."""
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
        if not link or link in seen:
            continue

        published = entry.get("published_parsed") or entry.get("updated_parsed")
        if published:
            pub_dt = datetime(*published[:6], tzinfo=timezone.utc)
            if pub_dt < cutoff:
                continue

        text = extract_text(link)
        if not text:
            log.warning("skipping article, no extractable text: %s", link)
            continue

        new_articles.append({
            "source": source["name"],
            "section_hint": source["section"],
            "title": entry.get("title", "").strip(),
            "link": link,
            "text": text[:MAX_ARTICLE_CHARS],
        })
        seen.add(link)

    src_state["seen_urls"] = list(seen)[-SEEN_URLS_KEEP:]
    return new_articles


def extract_text(url):
    try:
        downloaded = trafilatura.fetch_url(url)
        if not downloaded:
            return None
        return trafilatura.extract(downloaded)
    except Exception as e:
        log.warning("extraction failed for %s: %s", url, e)
        return None


def _strip_repeated_headline(text, title):
    """Most Bangla outlets open the article body with the headline again --
    sometimes twice, once as a kicker. Left in, every teaser is just its own
    headline restated.

    Compared in NFD because the feed title and the extracted body disagree on
    how they spell য়/ড়/ঢ়: one uses the precomposed য় (U+09DF), the other য +
    nukta. Those three letters are Unicode composition exclusions, so NFC
    won't reconcile them and a plain == or startswith silently misses.
    """
    nfd = lambda s: unicodedata.normalize("NFD", s)  # noqa: E731
    target = nfd(title.strip())
    if not target:
        return text
    for _ in range(3):
        body = text.lstrip()
        if not nfd(body).startswith(target):
            break
        # NFD only ever expands, so the cut in the original text is at most
        # len(target) characters in.
        cut = next((i for i in range(1, min(len(body), len(target)) + 1)
                    if nfd(body[:i]) == target), None)
        if cut is None:
            break
        text = body[cut:].lstrip(" \t\n\r:—-।")
    return text


def collect_results(articles):
    """No AI: each article's own title as headline, a plain-text excerpt of
    its extracted body as "summary". Section defaults to Local when the
    source doesn't map cleanly (see SOURCES in config.py) -- no classifier
    to do better than that."""
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
            "section": a["section_hint"] or "Local",
        })
    return results


# --- assemble ----------------------------------------------------------------

def make_teaser(text, max_chars=TEASER_CHARS):
    """First sentence (Bengali or Latin punctuation) of the full summary, capped.
    This is the one-line version readers see in the 5-7 min quick digest --
    the full multi-sentence text is only shown in the details section."""
    text = text.strip()
    for sep in ("\u0964", ".", "!", "?"):  # । = Bengali sentence-ending mark
        idx = text.find(sep)
        if 0 < idx <= max_chars:
            return text[:idx + 1].strip()
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rsplit(" ", 1)[0] + "…"


def group_by_section(articles, results):
    grouped = {s: [] for s in SECTIONS}
    by_index = {r["index"]: r for r in results}
    anchor_n = 0
    for i, a in enumerate(articles):
        r = by_index.get(i)
        if not r:
            continue
        section = a["section_hint"] or r.get("section")
        if section not in grouped:
            log.warning("unknown section %r, dropping article", section)
            continue
        grouped[section].append({
            "anchor": f"a{anchor_n}",
            "headline": r["headline"],
            "summary": r["summary"],
            "teaser": make_teaser(r["summary"]),
            "source": a["source"],
            "link": safe_url(a["link"]),  # untrusted: feeds can send javascript: URLs
        })
        anchor_n += 1
    return grouped


# --- epub --------------------------------------------------------------------

# E-readers strip most CSS, so this only carries the two-ink hierarchy where
# it survives: heavy display headings, vermilion section rules, quiet sources.
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
.teaser{margin:.15em 0 0;font-size:.92em;color:#3a3128}
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

    # Chapter 1: the \u09b8\u09c2\u099a\u09bf -- every headline with its source and a one-line
    # teaser, each linking into the matching detail chapter below.
    digest_html = f'<h1>{esc(title)}</h1><h1 class="part">{PART_TOC}</h1>'
    for section in SECTIONS:
        items = grouped.get(section, [])
        if not items:
            continue
        fname = f"{section.lower()}.xhtml"
        digest_html += _sec(section, len(items)) + '<ol class="rows">'
        for a in items:
            digest_html += (
                f'<li><a class="hl" href="{fname}#{a["anchor"]}">{esc(a["headline"])}</a>'
                f' <span class="src">{esc(a["source"])}</span>'
                f'<p class="teaser">{esc(a["teaser"])}</p></li>'
            )
        digest_html += "</ol>"
    digest_ch = epub.EpubHtml(title=PART_TOC, file_name="digest.xhtml", lang="bn")
    digest_ch.content = digest_html
    digest_ch.add_item(css)
    book.add_item(digest_ch)

    chapters = [digest_ch]
    for section in SECTIONS:
        items = grouped.get(section, [])
        if not items:
            continue
        html = f'<h1>{SECTION_BN[section]}</h1><h1 class="part">{PART_FULL}</h1>'
        for a in items:
            link = safe_url(a.get("link"))
            origin = (f' \u2014 <a href="{esc(link)}">\u09ae\u09c2\u09b2 \u09aa\u09cd\u09b0\u09a4\u09bf\u09ac\u09c7\u09a6\u09a8</a>'
                      if link else "")
            html += (
                f'<article id="{a["anchor"]}"><h3>{esc(a["headline"])}</h3>'
                f'<p>{esc(a["summary"])}</p>'
                f'<p class="meta">{esc(a["source"])}{origin}</p></article>'
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
    return h_esc(str(t), quote=True)


def safe_url(url):
    """Feed-provided links get interpolated into href="..." on the published
    site, in EPUB chapters and in subscriber email. Escaping alone does not
    defuse a `javascript:`/`data:`/`vbscript:` URL -- those stay live links --
    so anything that isn't plain http(s) is dropped and the source is rendered
    without a link instead. Sources are third-party RSS, i.e. untrusted.

    Applied at each sink that emits an href, not only once upstream, so it
    holds however the article dict was built.
    """
    url = (url or "").strip()
    return url if url.lower().startswith(("http://", "https://")) else ""


def _tally_html(counts, id_prefix):
    """SIGNATURE: one segment per section, flex-sized by article count, so the
    bar shows where the run's weight actually landed -- and doubles as the
    section nav. Not decoration: remove it and you lose real information."""
    live = [s for s in SECTIONS if counts.get(s)]
    segs = "".join(
        f'<li class=seg style="--n:{counts[s]};--i:{i}">'
        f'<a href="#{id_prefix}-{s}"><span class=seg-name>{SECTION_BN[s]}</span>'
        f'<span class=seg-n>{bn_num(counts[s])}</span></a></li>'
        for i, s in enumerate(live)
    )
    return f"<ul class=tally>{segs}</ul>" if segs else ""


def _edition_header(bd, counts, id_prefix, level=1):
    """The panjika day-page head: prahar + weekday, the date set large, and
    the tally rule beneath. `level` so the run page's date is its <h1> but on
    the index the site name keeps that role."""
    ed_label, ed_cls = edition(bd)
    return (
        f'<header class="edition {ed_cls}">'
        f"<p class=prahar>{ed_label}<span class=weekday>{bn_weekday(bd)}</span></p>"
        f'<h{level} class=date>{bn_date(bd)}<span class=clock>{bn_time(bd)}</span></h{level}>'
        f"{_tally_html(counts, id_prefix)}</header>"
    )


def _sec_head(section, n, id_prefix=None):
    """Section name, a two-ink leader filling the gap, then the count. The
    count is the point -- it's what the tally segment above links to."""
    sid = f" id={id_prefix}-{section}" if id_prefix else ""
    return (
        f"<h3 class=sec{sid}><span>{SECTION_BN[section]}</span>"
        f"<span class=sec-fill></span><span class=sec-n>{bn_num(n)}</span></h3>"
    )


def render_run_html(grouped, run_dt):
    counts = {s: len(grouped.get(s, [])) for s in SECTIONS}
    digest = f"<section class=digest><h2 class=part>{PART_TOC}</h2>"
    details = f"<section class=detail><h2 class=part>{PART_FULL}</h2>"
    for section in SECTIONS:
        items = grouped.get(section, [])
        if not items:
            continue
        digest += _sec_head(section, len(items), id_prefix="s") + "<ol class=rows>"
        for a in items:
            digest += (
                f'<li><span class=row><a class=hl href="#{a["anchor"]}">{esc(a["headline"])}</a>'
                f"<span class=dots></span><span class=src>{esc(a['source'])}</span></span>"
                f"<p class=teaser>{esc(a['teaser'])}</p></li>"
            )
        digest += "</ol>"
        details += _sec_head(section, len(items))
        for a in items:
            link = safe_url(a.get("link"))
            details += (
                f'<article id="{a["anchor"]}"><h4>{esc(a["headline"])}</h4>'
                f"<p>{esc(a['summary'])}</p>"
                f"<p class=meta><span class=src>{esc(a['source'])}</span>"
                + (f'<a href="{esc(link)}">\u09ae\u09c2\u09b2 \u09aa\u09cd\u09b0\u09a4\u09bf\u09ac\u09c7\u09a6\u09a8</a>' if link else "")
                + "</p></article>"
            )
    digest += "</section>"
    details += "</section>"

    bd = to_bd(run_dt)
    ed_label, _ = edition(bd)
    date_str = bn_date(bd)
    return (
        "<!doctype html><html lang=bn><head><meta charset=utf-8>"
        '<meta name=viewport content="width=device-width,initial-scale=1">'
        "<meta name=color-scheme content=light>"
        f"<title>{ed_label} \u00b7 {date_str} \u2014 \u09ac\u09be\u0982\u09b2\u09be \u09b8\u0982\u09ac\u09be\u09a6 \u09b8\u0982\u0995\u09cd\u09b7\u09c7\u09aa</title>"
        f"{FONT_LINKS}"
        '<link rel=stylesheet href="../style.css"></head><body>'
        '<a class=back href="../index.html">\u2190 \u0986\u099c\u0995\u09c7\u09b0 \u09b8\u09ac \u09b8\u0982\u09b8\u09cd\u0995\u09b0\u09a3</a>'
        f"{_edition_header(bd, counts, 's', level=1)}"
        f"<main>{digest}{details}</main></body></html>"
    )


_DIGEST_RE = re.compile(r"<section class=(?:quick-)?digest>.*?</section>", re.S)


def _run_fragment(fname, part="all"):
    """Pull a piece of an already-written run page back out.

    part="all"    -> everything after the edition header (RSS description).
    part="digest" -> just the \u09b8\u09c2\u099a\u09bf section (the index, which is digest-only).
    Tolerates pre-redesign archived pages (class=quick-digest) so the day a
    redesign ships doesn't blank out earlier editions.
    """
    html = (SITE_DIR / fname).read_text()
    if part == "digest":
        m = _DIGEST_RE.search(html)
        return m.group(0) if m else ""
    m = re.search(r"</header>(.*)</body>", html, re.S)
    return m.group(1) if m else ""


def build_rss(manifest):
    """RSS 2.0 feed of runs, newest first (manifest is already in that
    order) -- one <item> per edition, full digest+details content inlined
    into <description> so feed readers show the actual news, not a stub."""
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
            f"<description>{xml_escape(_run_fragment(r['file']))}</description>"
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
    entries with an archived EPUB get a download link (pre-this-feature
    entries won't have one)."""
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
    day, so the site/feed only ever hold \"today so far\" -- what keeps
    site/epubs/ bounded enough for OPDS to make sense."""
    kept, dropped = [], []
    for r in manifest:
        target = kept if to_bd(datetime.fromisoformat(r["dt"])).date() >= cutoff_date else dropped
        target.append(r)
    for r in dropped:
        (SITE_DIR / r["file"]).unlink(missing_ok=True)
        (SITE_DIR / "epubs" / (Path(r["file"]).stem + ".epub")).unlink(missing_ok=True)
    return kept


def render_index(manifest):
    """Today's editions stacked newest-first, digest only. The full excerpts
    live on each edition's own page -- inlining them here duplicated every
    article body two or three times and made index.html tens of kilobytes of
    text nobody scrolled to."""
    sheets = []
    for i, r in enumerate(manifest[:3]):
        bd = to_bd(datetime.fromisoformat(r["dt"]))
        # Re-point the extracted digest at the edition page (the detail
        # anchors it links to only exist there) and namespace its section ids
        # so three stacked editions don't collide.
        frag = _run_fragment(r["file"], part="digest")
        frag = (frag
                .replace(f"<h2 class=part>{PART_TOC}</h2>", "")  # the sheet header already says it
                .replace("id=s-", f"id=s{i}-")
                .replace('href="#', f'href="{r["file"]}#'))
        sheets.append(
            "<article class=sheet>"
            f"{_edition_header(bd, r['counts'], f's{i}', level=2)}"
            f"{frag}"
            f'<p class=more><a href="{r["file"]}">\u098f\u0987 \u09b8\u0982\u09b8\u09cd\u0995\u09b0\u09a3 \u09ac\u09bf\u09b8\u09cd\u09a4\u09be\u09b0\u09bf\u09a4 \u09aa\u09dc\u09c1\u09a8 \u2192</a></p>'
            "</article>"
        )
    body = "".join(sheets) or (
        "<p class=colophon>\u0986\u099c\u0995\u09c7\u09b0 \u0995\u09cb\u09a8\u09cb \u09b8\u0982\u09b8\u09cd\u0995\u09b0\u09a3 \u098f\u0996\u09a8\u09cb \u09aa\u09cd\u09b0\u0995\u09be\u09b6 \u09b9\u09df\u09a8\u09bf\u0964 "
        "\u09aa\u09b0\u09ac\u09b0\u09cd\u09a4\u09c0 \u09b8\u0982\u09b8\u09cd\u0995\u09b0\u09a3 \u09ad\u09cb\u09b0 \u09ec\u099f\u09be\u09df\u0964</p>"
    )
    return (
        "<!doctype html><html lang=bn><head><meta charset=utf-8>"
        '<meta name=viewport content="width=device-width,initial-scale=1">'
        "<meta name=color-scheme content=light>"
        "<title>\u09ac\u09be\u0982\u09b2\u09be \u09b8\u0982\u09ac\u09be\u09a6 \u09b8\u0982\u0995\u09cd\u09b7\u09c7\u09aa</title>"
        f"{FONT_LINKS}"
        "<link rel=stylesheet href=style.css>"
        '<link rel=alternate type=application/rss+xml title="\u09ac\u09be\u0982\u09b2\u09be \u09b8\u0982\u09ac\u09be\u09a6 \u09b8\u0982\u0995\u09cd\u09b7\u09c7\u09aa RSS" href=feed.xml>'
        "</head><body>"
        "<header class=masthead><hr class=rule2>"
        "<h1>\u09ac\u09be\u0982\u09b2\u09be \u09b8\u0982\u09ac\u09be\u09a6 \u09b8\u0982\u0995\u09cd\u09b7\u09c7\u09aa</h1>"
        "<p class=cadence>\u09aa\u09cd\u09b0\u09a4\u09bf\u09a6\u09bf\u09a8 \u09ad\u09cb\u09b0 \u09ec\u099f\u09be \u0993 \u09b8\u09a8\u09cd\u09a7\u09cd\u09af\u09be \u09ec\u099f\u09be\u09df \u2014 \u09ac\u09be\u0982\u09b2\u09be\u09a6\u09c7\u09b6 \u09b8\u09ae\u09df</p>"
        "<p class=feeds><a href=feed.xml>RSS</a><a href=opds.xml>OPDS</a></p>"
        "<hr class=rule2></header>"
        f"<main>{body}</main>"
        "<footer class=colophon>"
        "<p>\u098f\u0987 \u09aa\u09be\u09a4\u09be\u09df \u09b6\u09c1\u09a7\u09c1 \u0986\u099c\u0995\u09c7\u09b0 \u09b8\u0982\u09b8\u09cd\u0995\u09b0\u09a3 \u09a5\u09be\u0995\u09c7 \u2014 \u09aa\u09b0\u09a6\u09bf\u09a8 \u09ad\u09cb\u09b0\u09c7 \u0986\u0997\u09c7\u09b0\u0997\u09c1\u09b2\u09cb \u09b8\u09b0\u09c7 \u09af\u09be\u09df\u0964</p>"
        "<p>\u09aa\u09cd\u09b0\u09a4\u09bf\u099f\u09bf \u09b8\u0982\u09b8\u09cd\u0995\u09b0\u09a3 EPUB \u09b9\u09bf\u09b8\u09c7\u09ac\u09c7 \u09a8\u09be\u09ae\u09be\u09a8\u09cb \u09af\u09be\u09df OPDS \u09ab\u09bf\u09a1 \u09a5\u09c7\u0995\u09c7\u0964</p>"
        "</footer></body></html>"
    )


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
    manifest.insert(0, {"dt": run_dt.isoformat(), "file": fname, "counts": counts})
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
            link = safe_url(a.get("link"))
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
                f'padding-top:4px">{esc(a["teaser"])}</div>'
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
        # sendmail() only raises if EVERY recipient is refused; a partial
        # failure (one bad address) still delivers to the rest and returns
        # the refused ones here instead of blowing up the whole send.
        refused = smtp.sendmail(smtp_user, to_addrs, msg.as_string())
    if refused:
        log.warning("some recipients refused: %s", refused)



# --- main --------------------------------------------------------------------

def main():
    now = datetime.now(timezone.utc)
    state = load_state()

    articles = []
    for source in SOURCES:
        articles.extend(fetch_new_entries(source, state, now))

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
    # Content is on the site archive now -- mark seen regardless of whether
    # email succeeds below, so a flaky SMTP send doesn't resurface/duplicate
    # the same articles next run.
    save_state(state)

    try:
        retry(lambda: send_email(epub_path, now, grouped), what="email send")
    except Exception:
        log.exception("email send failed after retries -- digest is still on the site archive")
    finally:
        epub_path.unlink(missing_ok=True)  # not archived in git either way

    log.info("run complete")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log.exception("run failed")
        sys.exit(1)
