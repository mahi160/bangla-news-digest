"""Bangla news digest: fetch -> extract -> summarize (Claude Code/Opus) ->
EPUB + HTML archive page -> email. Run twice a day by GitHub Actions.

Everything except summarize_batch() is deterministic, boring code on purpose
(see docs/adr/0001, 0002) -- Claude only turns article text into a Bengali
headline+summary+section, no tool use, one batched call per run.
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
from pathlib import Path

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

DEGRADED_NOTICE = (
    "AI সারাংশ পরিষেবা অনুপলব্ধ ছিল — সারাংশের বদলে মূল শিরোনাম ও অংশ দেখানো হলো।"
)


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


# --- summarize via Claude Code ----------------------------------------------

CLAUDE_SYSTEM_PROMPT = (
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
    """One batched, non-agentic Claude Code call for the whole run.
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
    prompt = CLAUDE_SYSTEM_PROMPT + "\n\n" + json.dumps(payload, ensure_ascii=False)

    result = subprocess.run(
        [
            "claude", "-p", "--model", "opus", "--output-format", "json",
            "--bare",
            "--disallowedTools", "Bash Read Write Edit Glob Grep WebFetch WebSearch Task",
        ],
        input=prompt, capture_output=True, text=True, timeout=600,
    )
    if result.returncode != 0:
        raise RuntimeError(f"claude CLI failed: {result.stderr[:2000]}")

    envelope = json.loads(result.stdout)
    if envelope.get("is_error"):
        raise RuntimeError(f"claude error: {envelope.get('result')}")

    text = envelope["result"].strip()
    text = re.sub(r"^```(json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
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

def group_by_section(articles, ai_results):
    grouped = {s: [] for s in SECTIONS}
    by_index = {r["index"]: r for r in ai_results}
    for i, a in enumerate(articles):
        r = by_index.get(i)
        if not r:
            continue
        section = a["section_hint"] or r.get("section")
        if section not in grouped:
            log.warning("unknown section %r from AI, dropping article", section)
            continue
        grouped[section].append({
            "headline": r["headline"],
            "summary": r["summary"],
            "source": a["source"],
            "link": a["link"],
        })
    return grouped


# --- epub --------------------------------------------------------------------

def build_epub(grouped, run_dt, out_path, degraded=False):
    book = epub.EpubBook()
    book.set_identifier(f"bn-news-digest-{run_dt.isoformat()}")
    book.set_title(f"বাংলা সংবাদ সংক্ষেপ - {run_dt.strftime('%Y-%m-%d %H:%M')}")
    book.set_language("bn")

    chapters = []
    for section in SECTIONS:
        items = grouped.get(section, [])
        if not items:
            continue
        html = f"<h1>{section}</h1>"
        if degraded:
            html += f"<p><i>{DEGRADED_NOTICE}</i></p>"
        for a in items:
            html += (
                f"<h2>{a['headline']}</h2>"
                f"<p>{a['summary']}</p>"
                f"<p><i>{a['source']}</i> — <a href=\"{a['link']}\">মূল প্রতিবেদন</a></p>"
            )
        ch = epub.EpubHtml(title=section, file_name=f"{section.lower()}.xhtml", lang="bn")
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
    body = f"<p class=meta>{DEGRADED_NOTICE}</p>" if degraded else ""
    for section in SECTIONS:
        items = grouped.get(section, [])
        if not items:
            continue
        body += f"<h1>{section}</h1>"
        for a in items:
            body += (
                f"<article><h2>{a['headline']}</h2><p>{a['summary']}</p>"
                f"<p class=meta>{a['source']} — <a href=\"{a['link']}\">মূল প্রতিবেদন</a></p></article>"
            )
    return (
        "<!doctype html><html lang=bn><head><meta charset=utf-8>"
        f"<title>{run_dt.strftime('%Y-%m-%d %H:%M')} digest</title>"
        "<link rel=stylesheet href=\"../style.css\"></head><body>"
        f"<p><a href=\"../index.html\">← সব সংস্করণ</a></p>{body}</body></html>"
    )


def update_site(grouped, run_dt, degraded=False):
    SITE_DIR.mkdir(exist_ok=True)
    (SITE_DIR / "runs").mkdir(exist_ok=True)

    manifest = json.loads(RUNS_MANIFEST.read_text()) if RUNS_MANIFEST.exists() else []
    fname = f"runs/{run_dt.strftime('%Y-%m-%d-%H%M')}.html"
    (SITE_DIR / fname).write_text(render_run_html(grouped, run_dt, degraded=degraded))

    counts = {s: len(grouped.get(s, [])) for s in SECTIONS if grouped.get(s)}
    manifest.insert(0, {"dt": run_dt.isoformat(), "file": fname, "counts": counts, "degraded": degraded})
    RUNS_MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2))

    rows = "".join(
        f"<li><a href=\"{r['file']}\">{r['dt']}</a> "
        f"({', '.join(f'{k}: {v}' for k, v in r['counts'].items())})"
        f"{' ⚠ AI অনুপলব্ধ' if r.get('degraded') else ''}</li>"
        for r in manifest
    )
    index_html = (
        "<!doctype html><html lang=bn><head><meta charset=utf-8>"
        "<title>বাংলা সংবাদ সংক্ষেপ</title><link rel=stylesheet href=style.css></head>"
        f"<body><h1>বাংলা সংবাদ সংক্ষেপ</h1><ul>{rows}</ul></body></html>"
    )
    (SITE_DIR / "index.html").write_text(index_html)
    style_path = SITE_DIR / "style.css"
    if not style_path.exists():
        style_path.write_text(
            "body{max-width:40em;margin:2em auto;font-family:sans-serif;line-height:1.6;padding:0 1em}"
            "article{margin-bottom:2em}.meta{color:#666;font-size:.9em}"
        )


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

    log.info("summarizing %d articles via Claude Code (opus)", len(articles))
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
    update_site(grouped, now, degraded=degraded)
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
