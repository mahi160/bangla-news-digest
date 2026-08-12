"""Self-check for the non-trivial logic: dedup, cutoff filtering, section
resolution. No network calls -- feedparser.parse and extract_text are
monkeypatched. Run with: python test_pipeline.py
"""
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
    test_parse_recipients_handles_separators_and_whitespace()
    print("all tests passed")
