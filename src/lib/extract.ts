// Fetch + article text extraction. Port of old/pipeline.py's
// extract_meta()/fetch_new_entries(), using Readability+jsdom in place of
// trafilatura.

import Parser from "rss-parser";
import { JSDOM, VirtualConsole } from "jsdom";
import { Readability } from "@mozilla/readability";
import { MAX_ARTICLE_CHARS } from "./config.ts";

const rssParser = new Parser({ timeout: 15_000 });

export interface FeedEntry {
	link: string;
	title: string;
	/** ISO instant, or null if the feed didn't say. */
	published: string | null;
}

/** Never throws -- a dead/unparseable feed is the caller's problem to log and skip. */
export async function fetchFeed(url: string): Promise<FeedEntry[]> {
	const feed = await rssParser.parseURL(url);
	return (feed.items ?? []).map((item) => ({
		link: item.link ?? "",
		title: (item.title ?? "").trim(),
		published: item.isoDate ?? (item.pubDate ? new Date(item.pubDate).toISOString() : null),
	}));
}

export interface ExtractedMeta {
	text: string;
	author: string;
	image: string;
}

/** Fetch a URL once and return {text, author, image}, or null if extraction
 * failed/found nothing -- caller logs and skips, same as the old pipeline. */
export async function extractMeta(url: string): Promise<ExtractedMeta | null> {
	try {
		const res = await fetch(url, {
			headers: { "User-Agent": "Mozilla/5.0 (compatible; BanglaNewsDigest/1.0)" },
			signal: AbortSignal.timeout(20_000),
		});
		if (!res.ok) return null;
		const html = await res.text();

		// jsdom logs unsupported-CSS/script noise for every third-party page by
		// design -- silence it, it's not actionable here.
		const virtualConsole = new VirtualConsole();
		const dom = new JSDOM(html, { url, virtualConsole });
		const doc = dom.window.document;

		const reader = new Readability(doc);
		const parsed = reader.parse();
		const text = (parsed?.textContent ?? "").trim();
		if (!text) return null;

		const author =
			parsed?.byline?.trim() ||
			doc.querySelector('meta[name="author"]')?.getAttribute("content")?.trim() ||
			"";
		const image =
			doc.querySelector('meta[property="og:image"]')?.getAttribute("content")?.trim() || "";

		return { text: text.slice(0, MAX_ARTICLE_CHARS), author, image };
	} catch {
		return null;
	}
}
