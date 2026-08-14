// Shared HTML string builders for the category panel -- used both by the
// index/run Astro pages (via set:html) and by feed.xml's <description>
// (old/pipeline.py's _row_html/_panel_html reused the same way, for the
// same reason: RSS/OPDS need the exact same markup a page would show).
import { SECTIONS } from "./config.ts";
import { SECTION_BN, SECTION_ACCENT } from "./sections.ts";
import { bnNum } from "./dates.ts";
import type { Article, Grouped } from "./types.ts";

function esc(t: string | null | undefined): string {
	return String(t ?? "")
		.replace(/&/g, "&amp;")
		.replace(/</g, "&lt;")
		.replace(/>/g, "&gt;")
		.replace(/"/g, "&quot;");
}

function rowHtml(a: Article): string {
	const href = esc(a.link || "#");
	let meta = esc(a.source);
	if (a.time) meta += ` · ${esc(a.time)}`;
	return (
		`<li><a class=row href="${href}" data-headline="${esc(a.headline)}" ` +
		`data-source="${esc(a.source)}" data-time="${esc(a.time)}" ` +
		`data-author="${esc(a.author)}" data-image="${esc(a.image)}" ` +
		`data-link="${esc(a.link)}" data-excerpt="${esc(a.excerpt)}">` +
		`<span class=row-hl>${esc(a.headline)}</span>` +
		`<span class=row-meta>${meta}</span></a></li>`
	);
}

export function renderPanel(grouped: Grouped, idx: string | number): string {
	const present = SECTIONS.filter((s) => grouped[s]?.length);
	if (present.length === 0) {
		return "<p class=empty>এই সংস্করণে এখনও কোনো খবর নেই।</p>";
	}
	const chips = present
		.map(
			(s) =>
				`<a class=chip href="#p${idx}-${s}" style="--accent:${SECTION_ACCENT[s]}">${SECTION_BN[s]}` +
				`<span class=chip-n>${bnNum(grouped[s]!.length)}</span></a>`,
		)
		.join("");
	const cats = present
		.map(
			(s) =>
				`<section class=cat id="p${idx}-${s}" style="--accent:${SECTION_ACCENT[s]}">` +
				`<h3 class=cat-head><span>${SECTION_BN[s]}</span>` +
				`<span class=cat-n>${bnNum(grouped[s]!.length)}</span></h3>` +
				`<ul class=rows>${grouped[s]!.map(rowHtml).join("")}</ul></section>`,
		)
		.join("");
	return `<nav class=chips>${chips}</nav><div class=catgrid>${cats}</div>`;
}
