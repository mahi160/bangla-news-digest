"""Source list and run constants. Pure data — no logic here."""

SECTIONS = ["Local", "International", "Entertainment", "Tech", "Sports"]

# section=None means the feed mixes categories -> Claude classifies each
# article into one of SECTIONS. section=<name> means it's a clean per-source
# mapping and we trust it, no classification needed.
SOURCES = [
    {"name": "Prothom Alo", "url": "https://www.prothomalo.com/feed", "section": None, "lang": "bn"},
    {"name": "Banglanews24", "url": "https://www.banglanews24.com/rss.xml", "section": None, "lang": "bn"},
    {"name": "BBC Bangla", "url": "https://feeds.bbci.co.uk/bengali/rss.xml", "section": None, "lang": "bn"},
    {"name": "BBC Bangla Sport", "url": "https://feeds.bbci.co.uk/bengali/sport/rss.xml", "section": "Sports", "lang": "bn"},
    {"name": "ESPN Cricinfo", "url": "https://www.espncricinfo.com/rss/content/story/feeds/6.xml", "section": "Sports", "lang": "en"},
    {"name": "omg! ubuntu", "url": "https://www.omgubuntu.co.uk/feed", "section": "Tech", "lang": "en"},
    {"name": "It's FOSS", "url": "https://www.itsfoss.com/feed/", "section": "Tech", "lang": "en"},
    {"name": "Ars Technica", "url": "https://arstechnica.com/feed/", "section": "Tech", "lang": "en"},
    {"name": "TechCrunch", "url": "https://techcrunch.com/feed/", "section": "Tech", "lang": "en"},
    {"name": "The Verge", "url": "https://www.theverge.com/rss/index.xml", "section": "Tech", "lang": "en"},
]

# ponytail: fixed lookback window. If a run is skipped/fails, the gap widens
# silently until the next successful run picks up whatever's still in the
# feed. Fine for a hobby digest; add a "catch up from last success" mode if
# missed runs become a real problem.
LOOKBACK_HOURS = 13  # slightly over 12h to cover clock drift / late-starting runs

# Cap article body sent to Claude, per article. Keeps token cost bounded
# without losing the substance of the piece.
MAX_ARTICLE_CHARS = 3000

# How many recent (url) entries to remember per source, to bound state.json growth.
SEEN_URLS_KEEP = 500
