// Fetch -> extract -> classify -> group. Port of old/pipeline.py's
// fetch_new_entries/collect_results/group_by_section/make_teaser/
// _strip_repeated_headline.

import { EXCERPT_CHARS, LOOKBACK_HOURS, SECTIONS, SOURCES, TEASER_CHARS, SEEN_URLS_KEEP } from "./config.ts";
import type { Section } from "./config.ts";
import { classifyByLink } from "./classify.ts";
import { extractMeta, fetchFeed } from "./extract.ts";
import { bnTime, toBd } from "./dates.ts";
import { safeUrl } from "./util.ts";
import type { State } from "./state.ts";
import type { Article, Grouped } from "./types.ts";

interface RawArticle {
	source: string;
	sectionHint: Section | null;
	title: string;
	link: string;
	text: string;
	author: string;
	image: string;
	published: string | null;
}

/** Fetch every configured source, skipping ones that error, deduping against
 * both persisted state and this run's own cross-source overlap (specific
 * topic feeds are listed in config.ts ahead of an outlet's general feed, so
 * an article both carry only gets captured once, with the more specific
 * section -- SOURCES order matters). Never throws. */
export async function fetchAllNewArticles(state: State, now: Date): Promise<RawArticle[]> {
	const seenThisRun = new Set<string>();
	const cutoff = now.getTime() - LOOKBACK_HOURS * 3600_000;
	const articles: RawArticle[] = [];

	for (const source of SOURCES) {
		const srcState = (state[source.name] ??= { seen_urls: [] });
		const seen = new Set(srcState.seen_urls);

		let entries;
		try {
			entries = await fetchFeed(source.url);
		} catch (e) {
			console.warn(`skipping source ${source.name}: fetch failed (${e})`);
			continue;
		}

		for (const entry of entries) {
			if (!entry.link || seen.has(entry.link) || seenThisRun.has(entry.link)) continue;
			if (entry.published && new Date(entry.published).getTime() < cutoff) continue;

			const meta = await extractMeta(entry.link);
			if (!meta) {
				console.warn(`skipping article, no extractable text: ${entry.link}`);
				continue;
			}

			articles.push({
				source: source.name,
				sectionHint: source.section,
				title: entry.title,
				link: entry.link,
				text: meta.text,
				author: meta.author,
				image: meta.image,
				published: entry.published,
			});
			seen.add(entry.link);
			seenThisRun.add(entry.link);
		}

		srcState.seen_urls = Array.from(seen).slice(-SEEN_URLS_KEEP);
	}

	return articles;
}

// Most Bangla outlets open the article body with the headline again --
// sometimes twice, once as a kicker. Left in, every excerpt is just its own
// headline restated. Compared in NFD because the feed title and the
// extracted body disagree on how they spell য়/ড়/ঢ় (composition exclusions --
// NFC does not reconcile them, so a plain startsWith silently misses).
function stripRepeatedHeadline(text: string, title: string): string {
	const nfd = (s: string) => s.normalize("NFD");
	const target = nfd(title.trim());
	if (!target) return text;
	for (let i = 0; i < 3; i++) {
		const body = text.replace(/^\s+/, "");
		if (!nfd(body).startsWith(target)) break;
		let cut: number | null = null;
		const limit = Math.min(body.length, target.length);
		for (let j = 1; j <= limit; j++) {
			if (nfd(body.slice(0, j)) === target) {
				cut = j;
				break;
			}
		}
		if (cut === null) break;
		text = body.slice(cut).replace(/^[ \t\n\r:—\-।]+/, "");
	}
	return text;
}

/** First sentence (Bengali or Latin punctuation) of a longer excerpt, capped
 * -- used only for the email's one-line preview. */
export function makeTeaser(text: string, maxChars = TEASER_CHARS): string {
	text = text.trim();
	for (const sep of ["\u0964", ".", "!", "?"]) {
		// = Bengali sentence-ending mark ।
		const idx = text.indexOf(sep);
		if (idx > 0 && idx <= maxChars) return text.slice(0, idx + 1).trim();
	}
	if (text.length <= maxChars) return text;
	const cut = text.slice(0, maxChars);
	const lastSpace = cut.lastIndexOf(" ");
	return (lastSpace > 0 ? cut.slice(0, lastSpace) : cut) + "…";
}

/** Section -> list of articles ready to render, grouped from this run's raw
 * fetch results. No AI: each article's own title as headline, a plain-text
 * excerpt of its extracted body. Section defaults to Local when the source
 * doesn't map cleanly. */
export function groupBySection(raw: RawArticle[]): Grouped {
	const grouped: Grouped = {};
	for (const a of raw) {
		const title = (a.title || "").trim();
		let text = stripRepeatedHeadline(a.text.trim(), title);
		text = text || a.text.trim(); // body was nothing but the headline

		let excerpt = text.slice(0, EXCERPT_CHARS).trim();
		if (text.length > EXCERPT_CHARS) {
			const lastSpace = excerpt.lastIndexOf(" ");
			excerpt = (lastSpace > 0 ? excerpt.slice(0, lastSpace) : excerpt) + "…";
		}

		const section: Section = a.sectionHint ?? classifyByLink(a.link) ?? "Local";
		if (!SECTIONS.includes(section)) {
			console.warn(`unknown section ${section}, dropping article`);
			continue;
		}

		let timeLabel = "";
		if (a.published) {
			const d = new Date(a.published);
			if (!Number.isNaN(d.getTime())) timeLabel = bnTime(toBd(d));
		}

		const article: Article = {
			headline: title || "(শিরোনামহীন)",
			excerpt,
			source: a.source,
			link: safeUrl(a.link), // untrusted: feeds can send javascript: URLs
			author: (a.author || "").trim(),
			image: safeUrl(a.image),
			time: timeLabel,
		};

		(grouped[section] ??= []).push(article);
	}
	return grouped;
}
