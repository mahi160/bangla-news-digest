// Minimal OPDS 1.2 acquisition feed (Atom + acquisition links) -- only
// entries with an archived EPUB get a download link. Port of
// old/pipeline.py's build_opds().
import type { APIRoute } from "astro";
import { loadManifest } from "../lib/state.ts";
import { xmlEscape } from "../lib/util.ts";
import { bnDate, bnNum, bnTime, edition, toBd } from "../lib/dates.ts";
import { SECTIONS, RSS_ITEM_CAP, SITE_URL } from "../lib/config.ts";
import { SECTION_BN } from "../lib/sections.ts";

export const prerender = true;

export const GET: APIRoute = () => {
	const manifest = loadManifest();
	// Every manifest entry gets an EPUB -- generated at build time from this
	// same manifest (src/pages/epubs/[run].epub.ts), not conditionally
	// persisted, so no existence check needed.
	const entries = manifest
		.slice(0, RSS_ITEM_CAP)
		.map((r) => {
			const epubName = r.file.split("/").pop()!.replace(/\.html$/, ".epub");
			const dt = new Date(r.dt);
			const bd = toBd(dt);
			const [edLabel] = edition(bd);
			const title = `${edLabel} — ${bnDate(bd)}, ${bnTime(bd)}`;
			const htmlLink = SITE_URL + r.file;
			const epubLink = `${SITE_URL}epubs/${epubName}`;
			const desc = SECTIONS.filter((s) => r.counts[s])
				.map((s) => `${SECTION_BN[s]} ${bnNum(r.counts[s]!)}`)
				.join(", ");
			return (
				"<entry>" +
				`<title>${xmlEscape(title)}</title>` +
				`<id>${xmlEscape(htmlLink)}</id>` +
				`<updated>${dt.toISOString()}</updated>` +
				`<content type="text">${xmlEscape(desc)}</content>` +
				`<link rel="http://opds-spec.org/acquisition" href="${xmlEscape(epubLink)}" type="application/epub+zip"/>` +
				`<link rel="alternate" href="${xmlEscape(htmlLink)}" type="text/html"/>` +
				"</entry>"
			);
		})
		.join("");

	const xml =
		'<?xml version="1.0" encoding="UTF-8"?>' +
		'<feed xmlns="http://www.w3.org/2005/Atom" xmlns:opds="http://opds-spec.org/2010/catalog">' +
		`<id>${SITE_URL}opds.xml</id>` +
		"<title>বাংলা সংবাদ সংক্ষেপ</title>" +
		`<updated>${new Date().toISOString()}</updated>` +
		`<link rel="self" href="${SITE_URL}opds.xml" type="application/atom+xml;profile=opds-catalog;kind=acquisition"/>` +
		entries +
		"</feed>";

	return new Response(xml, {
		headers: { "Content-Type": "application/atom+xml; charset=utf-8" },
	});
};
