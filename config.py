"""Source list and run constants. Pure data — no logic here."""

SECTIONS = ["Local", "International", "Entertainment", "Tech", "Sports"]

# section=None means the feed mixes categories -- pipeline.py's
# classify_by_link() reads the outlet's own URL path (e.g. prothomalo.com's
# /sports/... vs /technology/...) to sort those without AI; anything it
# can't place falls back to Local. Set section=<name> per-source instead
# when the feed (or a topic-specific variant of it) is already clean.
#
# BBC Bangla's own URLs are opaque IDs with no path signal, so its World/
# Entertainment topic feeds are listed as separate sources instead -- ahead
# of the general feed, so the shared same-run URL dedup (see
# fetch_new_entries) lets the more specific tag win over the general feed's
# copy of the same article.
SOURCES = [
    {"name": "Prothom Alo", "url": "https://www.prothomalo.com/feed", "section": None},
    {"name": "Banglanews24", "url": "https://www.banglanews24.com/rss.xml", "section": None},
    {"name": "BBC Bangla World", "url": "https://feeds.bbci.co.uk/bengali/world/rss.xml", "section": "International"},
    {"name": "BBC Bangla Entertainment", "url": "https://feeds.bbci.co.uk/bengali/topics/entertainment/rss.xml", "section": "Entertainment"},
    {"name": "BBC Bangla Sport", "url": "https://feeds.bbci.co.uk/bengali/sport/rss.xml", "section": "Sports"},
    {"name": "BBC Bangla", "url": "https://feeds.bbci.co.uk/bengali/rss.xml", "section": None},
    {"name": "ESPN Cricinfo", "url": "https://www.espncricinfo.com/rss/content/story/feeds/6.xml", "section": "Sports"},
    {"name": "omg! ubuntu", "url": "https://www.omgubuntu.co.uk/feed", "section": "Tech"},
    {"name": "It's FOSS", "url": "https://www.itsfoss.com/feed/", "section": "Tech"},
    {"name": "Ars Technica", "url": "https://arstechnica.com/feed/", "section": "Tech"},
    {"name": "TechCrunch", "url": "https://techcrunch.com/feed/", "section": "Tech"},
    {"name": "The Verge", "url": "https://www.theverge.com/rss/index.xml", "section": "Tech"},
]

# Where the site is deployed -- used to build absolute links in feed.xml/opds.xml.
SITE_URL = "https://mahi160.github.io/bangla-news-digest/"

# Local timezone editions/dates are displayed in, and that the four-times-
# daily edition split (pipeline.py's edition()) and retention pruning key off of.
LOCAL_TZ_OFFSET_HOURS = 6  # Bangladesh Standard Time

# ponytail: fixed lookback window. If a run is skipped/fails, the gap widens
# silently until the next successful run picks up whatever's still in the
# feed. Fine for a hobby digest; add a "catch up from last success" mode if
# missed runs become a real problem.
LOOKBACK_HOURS = 7  # slightly over the 6h run cadence, to cover drift/late starts

# Cap on extracted article text kept in memory per article, before it's
# trimmed further to EXCERPT_CHARS for display.
MAX_ARTICLE_CHARS = 3000

# No AI summary -- each article shows a plain-text excerpt of its extracted
# body (EXCERPT_CHARS) and a one-line teaser cut from that (TEASER_CHARS).
EXCERPT_CHARS = 400
TEASER_CHARS = 120

# How many recent (url) entries to remember per source, to bound state.json growth.
SEEN_URLS_KEEP = 500

# RSS/OPDS feeds include at most this many most-recent runs.
RSS_ITEM_CAP = 30

# Retry knobs for email send. Linear backoff: attempt N waits
# RETRY_BACKOFF_SECONDS * N before the next try.
RETRY_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS = 5
