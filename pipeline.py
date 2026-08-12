"""Bangla news digest: fetch -> extract -> summarize (pi CLI / Claude Sonnet 5) ->
EPUB + HTML archive page -> email. Run twice a day by GitHub Actions.

Everything except summarize_batch() is deterministic, boring code on purpose
(see docs/adr/0001, 0002, 0003) -- the model only turns article text into a
Bengali headline+summary+section, no tool use, one batched call per run.
"""
import json
import logging
import os
import re
import smtplib
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import format_datetime
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

import feedparser
import trafilatura
from ebooklib import epub

from config import (
    LOOKBACK_HOURS, MAX_ARTICLE_CHARS, RETRY_ATTEMPTS, RETRY_BACKOFF_SECONDS,
    SECTIONS, SEEN_URLS_KEEP, SOURCES,
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
SITE_URL = "https://mahi160.github.io/bangla-news-digest/"
RSS_ITEM_CAP = 30  # ponytail: fixed cap, plenty for a twice-daily feed -- add paging if this site outlives that

DEGRADED_NOTICE = (
    "AI সারাংশ পরিষেবা অনুপলব্ধ ছিল — সারাংশের বদলে মূল শিরোনাম ও অংশ দেখানো হলো।"
)

# --- date formatting (Bangla, twice-daily edition-aware) --------------------
# ponytail: fixed 06:00/18:00 cadence per README -- hour<12 is always the
# morning run in practice, no timezone-of-reader handling needed for a
# single-author digest site.

_BN_DIGITS = str.maketrans("0123456789", "০১২৩৪৫৬৭৮৯")
_BN_MONTHS = ["জানুয়ারি", "ফেব্রুয়ারি", "মার্চ", "এপ্রিল", "মে", "জুন", "জুলাই",
              "আগস্ট", "সেপ্টেম্বর", "অক্টোবর", "নভেম্বর", "ডিসেম্বর"]
_BN_WEEKDAYS = ["সোমবার", "মঙ্গলবার", "বুধবার", "বৃহস্পতিবার", "শুক্রবার", "শনিবার", "রবিবার"]
BD_TZ = timezone(timedelta(hours=6))


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


STYLE_CSS = """\
@import url('https://fonts.googleapis.com/css2?family=Tiro+Bangla&family=Hind+Siliguri:wght@400;600&family=IBM+Plex+Mono:wght@400;500&display=swap');
:root{
  --ink:#211f1a;--muted:#6d7266;--paper:#eef0e6;--paper-raised:#e6e9da;--line:#d5d8c8;
  --dawn:#d99a2b;--dusk:#46527a;--warn-bg:#f5e6d8;--warn-fg:#8a4a1f;
  --font-display:'Tiro Bangla',Georgia,serif;
  --font-body:'Hind Siliguri','Noto Sans Bengali',system-ui,-apple-system,sans-serif;
  --font-mono:'IBM Plex Mono',ui-monospace,SFMono-Regular,Menlo,monospace;
}
*{box-sizing:border-box}
body{max-width:42em;margin:0 auto;padding:2.5rem 1.25rem 4rem;font-family:var(--font-body);
  line-height:1.75;color:var(--ink);background:var(--paper)}
a{color:var(--dusk);text-decoration:none}
a:hover{text-decoration:underline}
a:focus-visible,button:focus-visible{outline:2px solid var(--dusk);outline-offset:2px}
.back{display:inline-block;margin-bottom:.5rem;font-family:var(--font-mono);font-size:.78rem;
  letter-spacing:.04em;color:var(--muted)}
.back:hover{color:var(--dusk)}
.hint{color:var(--muted);font-size:.9rem;margin:0 0 2rem}
.hint .feed{font-family:var(--font-mono);font-size:.78rem;letter-spacing:.04em;color:var(--muted);border:1px solid var(--line);border-radius:999px;padding:.1rem .55rem}
.hint .feed:hover{color:var(--dusk);border-color:var(--dusk)}
.masthead h1{font-family:var(--font-display);font-size:2rem;margin:0 0 .5rem;font-weight:600}
.masthead .arc{height:3px;border:0;border-radius:2px;margin:0 0 1.1rem;
  background:linear-gradient(90deg,var(--dawn),var(--paper-raised) 50%,var(--dusk))}
.run-head{border-left:4px solid var(--line);padding-left:1rem;margin:0 0 2.25rem}
.run-head.dawn{border-color:var(--dawn)}
.run-head.dusk{border-color:var(--dusk)}
.run-head .eyebrow{font-family:var(--font-mono);font-size:.72rem;letter-spacing:.12em;
  text-transform:uppercase;color:var(--muted);margin:0 0 .35rem}
.run-head.dawn .eyebrow{color:var(--dawn)}
.run-head.dusk .eyebrow{color:var(--dusk)}
.run-head h1{font-family:var(--font-display);font-size:1.85rem;margin:0;font-weight:600}
.run-head h1 .time{font-family:var(--font-body);font-weight:400;color:var(--muted);font-size:1.1rem;margin-left:.5rem}
h2{font-family:var(--font-display);font-size:1.2rem;margin:2.25rem 0 .9rem;padding-bottom:.35rem;
  border-bottom:1px solid var(--line);font-weight:600}
h3{font-family:var(--font-mono);font-size:.72rem;letter-spacing:.12em;text-transform:uppercase;
  color:var(--dusk);margin:1.75rem 0 .6rem;font-weight:500}
article h4{font-family:var(--font-display);font-size:1.08rem;margin:0 0 .4rem;line-height:1.5;font-weight:600}
.teaser-list strong{font-family:var(--font-display);font-weight:600}
.notice{background:var(--warn-bg);color:var(--warn-fg);border:1px solid #e3c39a;border-radius:8px;
  padding:.65rem .95rem;font-size:.9rem;margin-bottom:1.75rem}
.quick-digest{background:var(--paper-raised);border:1px solid var(--line);border-radius:14px;
  padding:.3rem 1.35rem 1.35rem;margin-bottom:2.75rem}
.teaser-list{list-style:none;margin:0;padding:0}
.teaser-list li{padding:.6rem 0;border-bottom:1px solid var(--line)}
.teaser-list li:last-child{border-bottom:none}
article{margin-bottom:1.85rem;padding-bottom:1.85rem;border-bottom:1px solid var(--line)}
article:last-child{border-bottom:none}
article p{margin:.5rem 0}
.meta{font-family:var(--font-mono);color:var(--muted);font-size:.78rem}
.meta a{color:var(--muted)}
.meta a:hover{color:var(--dusk)}
.tabs{margin-top:1.5rem}
.tabs input{position:absolute;width:1px;height:1px;opacity:0}
.tabs input:focus-visible + label{outline:2px solid var(--dusk);outline-offset:2px}
.tabs label{display:inline-block;font-family:var(--font-mono);font-size:.78rem;letter-spacing:.06em;
  text-transform:uppercase;padding:.45rem 1.1rem;border:1px solid var(--line);border-radius:999px;
  margin:0 .5rem .6rem 0;cursor:pointer;color:var(--muted);background:var(--paper-raised)}
.tabs label.dawn{color:var(--dawn)}
.tabs label.dusk{color:var(--dusk)}
.tabs input:checked + label{background:var(--ink);color:var(--paper);border-color:var(--ink)}
.tabs .panel{display:none}
.tabs input:nth-of-type(1):checked ~ .panel:nth-of-type(1),
.tabs input:nth-of-type(2):checked ~ .panel:nth-of-type(2),
.tabs input:nth-of-type(3):checked ~ .panel:nth-of-type(3){display:block}
.permalink{margin-top:1.5rem;font-family:var(--font-mono);font-size:.78rem}
.permalink a{color:var(--muted)}
@media(max-width:30em){
  .masthead h1{font-size:1.6rem}
  .run-head h1{font-size:1.45rem}
  .run-head h1 .time{display:block;margin-left:0}
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
            "lang": source["lang"],
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


# --- summarize via pi CLI (Claude Sonnet 5) ---------------------------------

SUMMARY_SYSTEM_PROMPT = (
    "You are a news summarization engine. You will be given a JSON array of "
    "articles (fields: index, source, lang, section_hint, title, text). For "
    "each article, produce a Bengali (Bangla script) headline and an "
    "elaborate 3-6 sentence Bengali summary of its substance, regardless of "
    "the article's original language. If section_hint is one of "
    f"{SECTIONS}, copy it verbatim as \"section\". If section_hint is null, "
    f"classify the article into exactly one of {SECTIONS} yourself.\n\n"
    "Respond with ONLY a JSON array, no prose, no markdown fences: "
    '[{"index": 0, "headline": "...", "summary": "...", "section": "..."}, ...]'
)


def summarize_batch(articles):
    """One batched, non-agentic pi CLI call for the whole run (Claude Sonnet 5
    via pi's existing subscription auth -- no separate ANTHROPIC_API_KEY).
    Returns list of {index, headline, summary, section}."""
    if not articles:
        return []

    payload = [
        {
            "index": i,
            "source": a["source"],
            "lang": a["lang"],
            "section_hint": a["section_hint"],
            "title": a["title"],
            "text": a["text"],
        }
        for i, a in enumerate(articles)
    ]
    prompt = json.dumps(payload, ensure_ascii=False)

    result = subprocess.run(
        [
            "pi", "--print", "--mode", "text",
            "--model", "anthropic/claude-sonnet-5",
            "--system-prompt", SUMMARY_SYSTEM_PROMPT,
            "--no-tools", "--no-session", "--no-extensions", "--no-skills",
            "--no-prompt-templates", "--no-themes", "--no-context-files",
        ],
        input=prompt, capture_output=True, text=True, timeout=600,
    )
    if result.returncode != 0:
        raise RuntimeError(f"pi CLI failed: {result.stderr[:2000]}")

    text = result.stdout.strip()
    text = re.sub(r"^```(json)?|```$", "", text, flags=re.MULTILINE).strip()
    return json.loads(text)


def fallback_results(articles):
    """No-AI fallback: raw title + plain-text excerpt, no translation/summary.
    Section defaults to Local when there's no section_hint, since real
    classification needs the AI we don't have right now -- best-effort, not
    accurate, but subscribers still get every headline instead of nothing.
    """
    results = []
    for i, a in enumerate(articles):
        excerpt = a["text"][:400].strip()
        if len(a["text"]) > 400:
            excerpt = excerpt.rsplit(" ", 1)[0] + "…"
        results.append({
            "index": i,
            "headline": a["title"] or "(শিরোনামহীন)",
            "summary": excerpt,
            "section": a["section_hint"] or "Local",
        })
    return results


# --- assemble ----------------------------------------------------------------

def make_teaser(text, max_chars=120):
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


def group_by_section(articles, ai_results):
    grouped = {s: [] for s in SECTIONS}
    by_index = {r["index"]: r for r in ai_results}
    anchor_n = 0
    for i, a in enumerate(articles):
        r = by_index.get(i)
        if not r:
            continue
        section = a["section_hint"] or r.get("section")
        if section not in grouped:
            log.warning("unknown section %r from AI, dropping article", section)
            continue
        grouped[section].append({
            "anchor": f"a{anchor_n}",
            "headline": r["headline"],
            "summary": r["summary"],
            "teaser": make_teaser(r["summary"]),
            "source": a["source"],
            "link": a["link"],
        })
        anchor_n += 1
    return grouped


# --- epub --------------------------------------------------------------------

def build_epub(grouped, run_dt, out_path, degraded=False):
    book = epub.EpubBook()
    book.set_identifier(f"bn-news-digest-{run_dt.isoformat()}")
    book.set_title(f"বাংলা সংবাদ সংক্ষেপ - {run_dt.strftime('%Y-%m-%d %H:%M')}")
    book.set_language("bn")

    # Chapter 1: quick digest -- headline + one-line teaser for every article,
    # a ~5-7 min read. Each links into the matching detail chapter below for
    # readers who want the full elaborate summary.
    digest_html = "<h1>সংক্ষিপ্ত সারাংশ (৫-৭ মিনিট)</h1>"
    if degraded:
        digest_html += f"<p><i>{DEGRADED_NOTICE}</i></p>"
    for section in SECTIONS:
        items = grouped.get(section, [])
        if not items:
            continue
        fname = f"{section.lower()}.xhtml"
        digest_html += f"<h2>{section}</h2><ul>"
        for a in items:
            digest_html += f'<li><a href="{fname}#{a["anchor"]}"><b>{a["headline"]}</b></a> — {a["teaser"]}</li>'
        digest_html += "</ul>"
    digest_ch = epub.EpubHtml(title="সংক্ষিপ্ত সারাংশ", file_name="digest.xhtml", lang="bn")
    digest_ch.content = digest_html
    book.add_item(digest_ch)

    chapters = [digest_ch]
    for section in SECTIONS:
        items = grouped.get(section, [])
        if not items:
            continue
        html = f"<h1>{section} — বিস্তারিত</h1>"
        if degraded:
            html += f"<p><i>{DEGRADED_NOTICE}</i></p>"
        for a in items:
            html += (
                f"<h2 id=\"{a['anchor']}\">{a['headline']}</h2>"
                f"<p>{a['summary']}</p>"
                f"<p><i>{a['source']}</i> — <a href=\"{a['link']}\">মূল প্রতিবেদন</a></p>"
            )
        ch = epub.EpubHtml(title=f"{section} (বিস্তারিত)", file_name=f"{section.lower()}.xhtml", lang="bn")
        ch.content = html
        book.add_item(ch)
        chapters.append(ch)

    book.toc = chapters
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav"] + chapters
    epub.write_epub(str(out_path), book)


# --- site (GitHub Pages archive) --------------------------------------------

def render_run_html(grouped, run_dt, degraded=False):
    notice = f"<p class=notice>{DEGRADED_NOTICE}</p>" if degraded else ""
    digest = f"<section class=quick-digest><h2>সংক্ষিপ্ত সারাংশ <span class=hint>(৫-৭ মিনিট)</span></h2>"
    details = "<section class=details><h2>বিস্তারিত</h2>"
    for section in SECTIONS:
        items = grouped.get(section, [])
        if not items:
            continue
        digest += f"<h3>{section}</h3><ul class=teaser-list>"
        for a in items:
            digest += f'<li><a href="#{a["anchor"]}"><strong>{a["headline"]}</strong></a> — {a["teaser"]}</li>'
        digest += "</ul>"
        details += f"<h3>{section}</h3>"
        for a in items:
            details += (
                f'<article id="{a["anchor"]}"><h4>{a["headline"]}</h4><p>{a["summary"]}</p>'
                f'<p class=meta>{a["source"]} — <a href="{a["link"]}">মূল প্রতিবেদন</a></p></article>'
            )
    digest += "</section>"
    details += "</section>"
    bd = to_bd(run_dt)
    ed_label, ed_cls = edition(bd)
    date_str, time_str = bn_date(bd), bn_time(bd)
    header = (
        f"<a class=back href=\"../index.html\">← সব সংস্করণ</a>"
        f"<header class=\"run-head {ed_cls}\">"
        f"<p class=eyebrow>{ed_label} · {bn_weekday(bd)}</p>"
        f"<h1>{date_str} <span class=time>{time_str}</span></h1></header>"
    )
    return (
        "<!doctype html><html lang=bn><head><meta charset=utf-8>"
        f"<title>{date_str}, {time_str} — বাংলা সংবাদ সংক্ষেপ</title>"
        "<link rel=stylesheet href=\"../style.css\"></head><body>"
        f"{header}{notice}{digest}{details}</body></html>"
    )


def _run_fragment(fname):
    """The digest+details body of an archived run page, stripped of its
    outer <html>/<head>/header chrome -- shared by the tabbed index and the
    RSS feed so both show the actual news, not just a link to it."""
    html = (SITE_DIR / fname).read_text()
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
    entries with an archived EPUB get a download link; degraded runs still
    have one (build_epub always runs), older pre-this-feature entries won't."""
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
        desc = ", ".join(f"{k}: {v}" for k, v in r["counts"].items())
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
    """Today's editions as tabs (radio-input CSS hack, no JS) instead of a
    growing list -- retention now caps this at a handful of same-day runs."""
    tabs, panels = [], []
    for i, r in enumerate(manifest[:3]):
        bd = to_bd(datetime.fromisoformat(r["dt"]))
        ed_label, ed_cls = edition(bd)
        checked = " checked" if i == 0 else ""
        tabs.append(
            f'<input type=radio name=tab id=tab-{i}{checked}>'
            f'<label for=tab-{i} class={ed_cls}>{ed_label.split()[0]} · {bn_time(bd)}</label>'
        )
        panels.append(
            f'<div class=panel>{_run_fragment(r["file"])}'
            f'<p class=permalink><a href="{r["file"]}">স্থায়ী লিংক</a></p></div>'
        )
    return (
        "<!doctype html><html lang=bn><head><meta charset=utf-8>"
        "<title>বাংলা সংবাদ সংক্ষেপ</title><link rel=stylesheet href=style.css>"
        "<link rel=alternate type=application/rss+xml title=\"বাংলা সংবাদ সংক্ষেপ RSS\" href=feed.xml></head>"
        "<body><header class=masthead><h1>বাংলা সংবাদ সংক্ষেপ</h1><hr class=arc></header>"
        "<p class=hint>আজকের প্রভাতী ও সান্ধ্য সংস্করণ — গতকালের সংস্করণ পরের সকালে সরে যায়। "
        "<a class=feed href=feed.xml>RSS</a> <a class=feed href=opds.xml>OPDS</a></p>"
        f'<div class=tabs>{"".join(tabs)}{"".join(panels)}</div></body></html>'
    )


def update_site(grouped, run_dt, degraded=False, epub_path=None):
    SITE_DIR.mkdir(exist_ok=True)
    (SITE_DIR / "runs").mkdir(exist_ok=True)
    (SITE_DIR / "epubs").mkdir(exist_ok=True)

    bd_now = to_bd(run_dt)
    _, ed_cls = edition(bd_now)
    manifest = json.loads(RUNS_MANIFEST.read_text()) if RUNS_MANIFEST.exists() else []
    if ed_cls == "dawn":  # morning edition: drop everything from before today
        manifest = _prune_before(manifest, bd_now.date())

    fname = f"runs/{run_dt.strftime('%Y-%m-%d-%H%M')}.html"
    (SITE_DIR / fname).write_text(render_run_html(grouped, run_dt, degraded=degraded))
    if epub_path and epub_path.exists():
        (SITE_DIR / "epubs" / (Path(fname).stem + ".epub")).write_bytes(epub_path.read_bytes())

    counts = {s: len(grouped.get(s, [])) for s in SECTIONS if grouped.get(s)}
    manifest.insert(0, {"dt": run_dt.isoformat(), "file": fname, "counts": counts, "degraded": degraded})
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


def send_email(epub_path, run_dt, grouped, degraded=False):
    to_addrs = parse_recipients(os.environ["EMAIL_TO"])
    if not to_addrs:
        raise RuntimeError("EMAIL_TO has no valid addresses")
    smtp_host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.environ.get("SMTP_PORT", "465"))
    smtp_user = os.environ["SMTP_USER"]
    smtp_pass = os.environ["SMTP_PASS"]

    counts = ", ".join(f"{s}: {len(grouped.get(s, []))}" for s in SECTIONS if grouped.get(s))
    note = f" {DEGRADED_NOTICE}" if degraded else ""
    msg = EmailMessage()
    msg["Subject"] = f"বাংলা সংবাদ সংক্ষেপ - {run_dt.strftime('%Y-%m-%d %H:%M')}"
    msg["From"] = smtp_user
    msg["To"] = smtp_user  # subscribers are Bcc'd -- they shouldn't see each other's addresses
    msg.set_content(f"আজকের সংক্ষেপ সংযুক্ত। ({counts}){note}")
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

    log.info("summarizing %d articles via pi CLI (Claude Sonnet 5)", len(articles))
    degraded = False
    try:
        ai_results = retry(lambda: summarize_batch(articles), what="claude summarization")
    except Exception:
        log.exception("summarization failed after retries -- falling back to raw listings, no AI summary this run")
        ai_results = fallback_results(articles)
        degraded = True

    grouped = group_by_section(articles, ai_results)

    epub_path = ROOT / f"digest-{now.strftime('%Y%m%d-%H%M')}.epub"
    build_epub(grouped, now, epub_path, degraded=degraded)
    update_site(grouped, now, degraded=degraded, epub_path=epub_path)
    # Content is on the site archive now -- mark seen regardless of whether
    # email succeeds below, so a flaky SMTP send doesn't resurface/duplicate
    # the same articles next run.
    save_state(state)

    try:
        retry(lambda: send_email(epub_path, now, grouped, degraded=degraded), what="email send")
    except Exception:
        log.exception("email send failed after retries -- digest is still on the site archive")
    finally:
        epub_path.unlink(missing_ok=True)  # not archived in git either way

    log.info("run complete (degraded=%s)", degraded)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log.exception("run failed")
        sys.exit(1)
