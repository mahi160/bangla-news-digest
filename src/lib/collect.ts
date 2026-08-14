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
	/** Position within this source's own feed, in feed order (0 = first/top
	 * story) -- an outlet's own feed order is usually already its own
	 * editorial priority; used as an importance tiebreaker (see groupBySection). */
	feedIndex: number;
	/** Source.weight (config.ts) -- summed across a story's covering outlets
	 * to score importance (see groupBySection), not just counted. */
	sourceWeight: number;
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

		for (let feedIndex = 0; feedIndex < entries.length; feedIndex++) {
			const entry = entries[feedIndex];
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
				feedIndex,
				sourceWeight: source.weight,
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

// Bengali/English punctuation stripped, lowercased, split on whitespace --
// good enough to catch "same story, near-identical headline" across
// outlets; won't catch heavily paraphrased headlines (no AI used, see
// docs discussion), which is an accepted miss, not a bug.
function titleTokens(title: string): Set<string> {
	return new Set(
		title
			.toLowerCase()
			.replace(/[।,.!?"'‘’“”():;\-]/g, " ")
			.split(/\s+/)
			.filter(Boolean),
	);
}

function jaccard(a: Set<string>, b: Set<string>): number {
	if (a.size === 0 || b.size === 0) return 0;
	let intersection = 0;
	for (const t of a) if (b.has(t)) intersection++;
	const union = a.size + b.size - intersection;
	return union === 0 ? 0 : intersection / union;
}

const ECHO_SIMILARITY_THRESHOLD = 0.5;

// ponytail: O(n^2) title comparison -- fine at run-size (tens of articles),
// revisit only if a run ever collects thousands at once.
/** Importance score per article: the *sum of source weights* of every
 * outlet covering the same story this run (by headline similarity), not
 * just a raw outlet count -- one major outlet's exclusive can outrank three
 * small blogs echoing each other. Free, deterministic, no AI/network call. */
function importanceScores(raw: RawArticle[]): number[] {
	const n = raw.length;
	const parent = Array.from({ length: n }, (_, i) => i);
	function find(x: number): number {
		while (parent[x] !== x) {
			parent[x] = parent[parent[x]];
			x = parent[x];
		}
		return x;
	}
	const tokens = raw.map((a) => titleTokens(a.title));
	for (let i = 0; i < n; i++) {
		for (let j = i + 1; j < n; j++) {
			if (jaccard(tokens[i], tokens[j]) >= ECHO_SIMILARITY_THRESHOLD) {
				const ri = find(i);
				const rj = find(j);
				if (ri !== rj) parent[ri] = rj;
			}
		}
	}
	const clusterWeight = new Map<number, number>();
	const roots = raw.map((_, i) => find(i));
	roots.forEach((r, i) => clusterWeight.set(r, (clusterWeight.get(r) ?? 0) + raw[i].sourceWeight));
	return roots.map((r) => clusterWeight.get(r)!);
}

/** Section -> list of articles ready to render, grouped from this run's raw
 * fetch results, ordered by a no-AI importance heuristic: stories with the
 * highest combined source weight first (importanceScores -- multi-outlet
 * coverage and outlet authority both count), then each outlet's own feed
 * order as a tiebreaker (feedIndex -- a feed's own order is usually already
 * its own editorial priority). No AI: each article's own title as headline,
 * a plain-text excerpt of its extracted body. Section defaults to Local
 * when the source doesn't map cleanly. */
export function groupBySection(raw: RawArticle[]): Grouped {
	const score = importanceScores(raw);
	const order = raw
		.map((_, i) => i)
		.sort((i, j) => score[j] - score[i] || raw[i].feedIndex - raw[j].feedIndex);

	const grouped: Grouped = {};
	for (const idx of order) {
		const a = raw[idx];
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
