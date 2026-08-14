// Source list and run constants. Pure data -- no logic here.
// Port of old/config.py.

export const SECTIONS = ["Local", "International", "Entertainment", "Tech", "Sports"] as const;
export type Section = (typeof SECTIONS)[number];

export interface Source {
	name: string;
	url: string;
	/** null means the feed mixes categories -- classifyByLink() sorts by URL path. */
	section: Section | null;
	/** Authority/trust weight (1-3), subjective starting point -- tune freely.
	 * Feeds into groupBySection's importance ordering: a story's score is the
	 * sum of weights of every outlet covering it this run, not just a raw
	 * outlet count, so one major outlet's exclusive can outrank three small
	 * blogs echoing each other. */
	weight: number;
}

// section=null means the feed mixes categories -- classifyByLink() reads the
// outlet's own URL path (e.g. prothomalo.com's /sports/... vs /technology/...)
// to sort those without AI; anything it can't place falls back to Local. Set
// section=<name> per-source instead when the feed (or a topic-specific
// variant of it) is already clean.
//
// BBC Bangla's own URLs are opaque IDs with no path signal, so its World/
// Entertainment topic feeds are listed as separate sources instead -- ahead
// of the general feed, so the shared same-run URL dedup (see collect.ts)
// lets the more specific tag win over the general feed's copy of the same
// article.
export const SOURCES: Source[] = [
	// -- Bangladesh, general (URL-classified) --
	{ name: "Prothom Alo", url: "https://www.prothomalo.com/feed", section: null, weight: 3 },
	{ name: "Banglanews24", url: "https://www.banglanews24.com/rss.xml", section: null, weight: 2 },
	{ name: "The Daily Star", url: "https://www.thedailystar.net/rss.xml", section: null, weight: 3 },
	{ name: "Dhaka Tribune", url: "https://www.dhakatribune.com/feed/rss", section: null, weight: 2 },
	// BDNews24 Bangla, Kalerkantho, Ittefaq, Bangla Tribune tried and dropped:
	// Cloudflare/bot-gated (403) or no working feed path found (404). Jugantor
	// tried and dropped: bot-blocked ("Access denied", inconsistent with its
	// feed's HTTP 200). Samakal tried and dropped: /rss/rss.xml serves its
	// HTML homepage, not a feed -- no working feed path found.

	// -- BBC Bangla: topic feeds listed ahead of the general one, so the
	// shared same-run URL dedup (see collect.ts) lets the more specific
	// section win over the general feed's copy of the same article. --
	{ name: "BBC Bangla World", url: "https://feeds.bbci.co.uk/bengali/world/rss.xml", section: "International", weight: 3 },
	{ name: "BBC Bangla Entertainment", url: "https://feeds.bbci.co.uk/bengali/topics/entertainment/rss.xml", section: "Entertainment", weight: 3 },
	{ name: "BBC Bangla Sport", url: "https://feeds.bbci.co.uk/bengali/sport/rss.xml", section: "Sports", weight: 3 },
	{ name: "BBC Bangla", url: "https://feeds.bbci.co.uk/bengali/rss.xml", section: null, weight: 3 },

	// -- International --
	{ name: "Al Jazeera", url: "https://www.aljazeera.com/xml/rss/all.xml", section: "International", weight: 3 },
	{ name: "The Guardian World", url: "https://www.theguardian.com/world/rss", section: "International", weight: 3 },
	// VOA Bangla, DW Bangla tried and dropped: no working public feed URL found.

	// -- Sports --
	{ name: "ESPN Cricinfo", url: "https://www.espncricinfo.com/rss/content/story/feeds/6.xml", section: "Sports", weight: 3 },
	{ name: "ESPN", url: "https://www.espn.com/espn/rss/news", section: "Sports", weight: 2 },
	{ name: "BBC Sport", url: "https://feeds.bbci.co.uk/sport/rss.xml", section: "Sports", weight: 2 },
	{ name: "The Daily Star Sports", url: "https://www.thedailystar.net/taxonomy/term/3/rss.xml", section: "Sports", weight: 2 },

	// -- Entertainment --
	{ name: "The Daily Star Entertainment", url: "https://www.thedailystar.net/taxonomy/term/283449/rss.xml", section: "Entertainment", weight: 2 },

	// -- Tech --
	{ name: "omg! ubuntu", url: "https://www.omgubuntu.co.uk/feed", section: "Tech", weight: 1 },
	{ name: "It's FOSS", url: "https://www.itsfoss.com/feed/", section: "Tech", weight: 1 },
	{ name: "Phoronix", url: "https://www.phoronix.com/rss.php", section: "Tech", weight: 1 },
	{ name: "TechShohor", url: "https://techshohor.com/feed/", section: "Tech", weight: 1 },
	{ name: "Ars Technica", url: "https://arstechnica.com/feed/", section: "Tech", weight: 2 },
	{ name: "TechCrunch", url: "https://techcrunch.com/feed/", section: "Tech", weight: 2 },
	{ name: "The Verge", url: "https://www.theverge.com/rss/index.xml", section: "Tech", weight: 2 },
	{ name: "Wired", url: "https://www.wired.com/feed/rss", section: "Tech", weight: 2 },
	{ name: "Engadget", url: "https://www.engadget.com/rss.xml", section: "Tech", weight: 2 },
	{ name: "9to5Google", url: "https://9to5google.com/feed/", section: "Tech", weight: 2 },
	{ name: "The Hacker News", url: "https://feeds.feedburner.com/TheHackersNews", section: "Tech", weight: 2 },
	// XDA Developers tried and dropped: feed connection unreliable (empty replies).
];

// Where the site is deployed -- used to build absolute links in feed.xml/opds.xml.
export const SITE_URL = "https://mahi160.github.io/bangla-news-digest/";

// Local timezone editions/dates are displayed in, and that the four-times-
// daily edition split (dates.ts's edition()) and retention pruning key off of.
export const LOCAL_TZ_OFFSET_HOURS = 6; // Bangladesh Standard Time

// ponytail: fixed lookback window. If a run is skipped/fails, the gap widens
// silently until the next successful run picks up whatever's still in the
// feed. Fine for a hobby digest; add a "catch up from last success" mode if
// missed runs become a real problem.
export const LOOKBACK_HOURS = 7; // slightly over the 6h run cadence, to cover drift/late starts

// Cap on extracted article text kept in memory per article, before it's
// trimmed further to EXCERPT_CHARS for display.
export const MAX_ARTICLE_CHARS = 3000;

// No AI summary -- each article shows a plain-text excerpt of its extracted
// body (EXCERPT_CHARS) and a one-line teaser cut from that (TEASER_CHARS).
export const EXCERPT_CHARS = 400;
export const TEASER_CHARS = 120;

// How many recent (url) entries to remember per source, to bound state.json growth.
export const SEEN_URLS_KEEP = 500;

// RSS/OPDS feeds include at most this many most-recent runs (in practice the
// manifest itself never holds more than ~4, same-day pruning keeps it small).
export const RSS_ITEM_CAP = 30;

// Retry knobs for email send. Linear backoff: attempt N waits
// RETRY_BACKOFF_SECONDS * N before the next try.
export const RETRY_ATTEMPTS = 3;
export const RETRY_BACKOFF_SECONDS = 5;
