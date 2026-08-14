import type { Section } from "./config.ts";

/** One article ready to render -- headline + plain-text excerpt, no AI summary. */
export interface Article {
	headline: string;
	excerpt: string;
	source: string;
	link: string;
	author: string;
	image: string;
	/** Bangla-formatted publish time label, e.g. "সকাল ৭:১৫", or "" if unknown. */
	time: string;
}

export type Grouped = Partial<Record<Section, Article[]>>;

/** One run/edition, as persisted in runs-manifest.json. */
export interface RunEntry {
	/** ISO 8601 UTC instant the run happened. */
	dt: string;
	/** Relative path of the archived permalink, e.g. "runs/2024-01-02-0600.html". */
	file: string;
	counts: Partial<Record<Section, number>>;
	grouped: Grouped;
}
