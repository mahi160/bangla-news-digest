// RSS 2.0 feed of runs, newest first -- one <item> per edition, the
// headline list (grouped, straight from the manifest) inlined as
// <description>. Port of old/pipeline.py's build_rss().
import type { APIRoute } from "astro";
import { loadManifest } from "../lib/state.ts";
import { renderPanel } from "../lib/render.ts";
import { xmlEscape } from "../lib/util.ts";
import { bnDate, bnTime, edition, toBd } from "../lib/dates.ts";
import { RSS_ITEM_CAP, SITE_URL } from "../lib/config.ts";

export const prerender = true;

function toRfc2822(dt: Date): string {
	return dt.toUTCString().replace("GMT", "+0000");
}

export const GET: APIRoute = () => {
	const manifest = loadManifest();
	const items = manifest
		.slice(0, RSS_ITEM_CAP)
		.map((r) => {
			const dt = new Date(r.dt);
			const bd = toBd(dt);
			const [edLabel] = edition(bd);
			const title = `${edLabel} — ${bnDate(bd)}, ${bnTime(bd)}`;
			const link = SITE_URL + r.file;
			return (
				"<item>" +
				`<title>${xmlEscape(title)}</title>` +
				`<link>${xmlEscape(link)}</link>` +
				`<guid>${xmlEscape(link)}</guid>` +
				`<pubDate>${toRfc2822(dt)}</pubDate>` +
				`<description>${xmlEscape(renderPanel(r.grouped, "r"))}</description>` +
				"</item>"
			);
		})
		.join("");

	const xml =
		'<?xml version="1.0" encoding="UTF-8"?>' +
		'<rss version="2.0"><channel>' +
		"<title>বাংলা সংবাদ সংক্ষেপ</title>" +
		`<link>${SITE_URL}</link>` +
		"<description>প্রতিদিন ০৬টা ও ১৮টায় নতুন বাংলা সংবাদ সংক্ষেপ</description>" +
		"<language>bn</language>" +
		items +
		"</channel></rss>";

	return new Response(xml, { headers: { "Content-Type": "application/rss+xml; charset=utf-8" } });
};
