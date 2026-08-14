// Minimal hand-built EPUB (zip + XHTML, no epub-gen dependency needed --
// the format is simple enough to write directly). Port of
// old/pipeline.py's build_epub(). Generated at `astro build` time from the
// committed manifest, not persisted separately -- see epubs/[run].epub.ts.
import JSZip from "jszip";
import { SECTIONS } from "./config.ts";
import { SECTION_BN } from "./sections.ts";
import { bnDate, bnNum, bnTime, edition, toBd } from "./dates.ts";
import type { BdDate } from "./dates.ts";
import type { Grouped } from "./types.ts";

function esc(t: string | null | undefined): string {
	return String(t ?? "")
		.replace(/&/g, "&amp;")
		.replace(/</g, "&lt;")
		.replace(/>/g, "&gt;")
		.replace(/"/g, "&quot;");
}

const EPUB_CSS = `body{font-family:serif;line-height:1.65;margin:0 6%}
h1{font-size:1.5em;font-weight:700;margin:1em 0 .2em}
h1.part{font-size:.9em;font-weight:400;color:#b82219;
  border-bottom:2px solid #b82219;padding-bottom:.35em}
h2.sec{font-size:1.15em;color:#b82219;border-bottom:1px solid #c2a96f;
  padding-bottom:.2em;margin:1.6em 0 .5em}
h2.sec .n{float:right;font-size:.8em;font-weight:400}
ol.rows{list-style:none;margin:0;padding:0}
ol.rows li{margin:0 0 .9em}
ol.rows .hl{font-weight:700}
.src{font-size:.8em;color:#6f5f42}
article{margin:0 0 1.4em}
article h3{font-size:1.05em;font-weight:700;margin:0 0 .3em}
.meta{font-size:.8em;color:#6f5f42;margin:.4em 0 0}
`;

function xhtml(title: string, bodyInner: string): string {
	return (
		`<?xml version="1.0" encoding="UTF-8"?>` +
		`<!DOCTYPE html>` +
		`<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="bn"><head>` +
		`<meta charset="utf-8"/><title>${esc(title)}</title>` +
		`<link rel="stylesheet" type="text/css" href="style/panjika.css"/>` +
		`</head><body>${bodyInner}</body></html>`
	);
}

function ncxNavPoints(chapters: { id: string; title: string; file: string }[]): string {
	return chapters
		.map(
			(c, i) =>
				`<navPoint id="${c.id}" playOrder="${i + 1}"><navLabel><text>${esc(c.title)}</text></navLabel>` +
				`<content src="${c.file}"/></navPoint>`,
		)
		.join("");
}

// ponytail: NCX-only navigation (EPUB2-style), no EPUB3 nav.xhtml -- every
// reader that matters (and OPDS clients) still get a working TOC from the
// NCX; add nav.xhtml if a reader ever turns up that needs it.

/** Builds one EPUB as a Buffer. run identifier used only for the book id. */
export async function buildEpub(grouped: Grouped, runDt: Date, runId: string): Promise<Buffer> {
	const bd: BdDate = toBd(runDt);
	const [edLabel] = edition(bd);
	const title = `${edLabel} · ${bnDate(bd)}, ${bnTime(bd)}`;

	const zip = new JSZip();
	zip.file("mimetype", "application/epub+zip", { compression: "STORE" });
	zip.file(
		"META-INF/container.xml",
		`<?xml version="1.0"?><container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">` +
			`<rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles></container>`,
	);
	zip.file("OEBPS/style/panjika.css", EPUB_CSS);

	// Table of contents chapter.
	let digestBody = `<h1>${esc(title)}</h1>`;
	for (const section of SECTIONS) {
		const items = grouped[section] ?? [];
		if (items.length === 0) continue;
		const fname = `${section.toLowerCase()}.xhtml`;
		digestBody += `<h2 class="sec">${SECTION_BN[section]}<span class="n">${bnNum(items.length)}</span></h2><ol class="rows">`;
		items.forEach((a, n) => {
			digestBody += `<li><a class="hl" href="${fname}#a${n}">${esc(a.headline)}</a> <span class="src">${esc(a.source)}</span></li>`;
		});
		digestBody += "</ol>";
	}

	const chapters: { id: string; title: string; file: string }[] = [
		{ id: "digest", title: "সূচি", file: "digest.xhtml" },
	];
	zip.file("OEBPS/digest.xhtml", xhtml("সূচি", digestBody));

	for (const section of SECTIONS) {
		const items = grouped[section] ?? [];
		if (items.length === 0) continue;
		let html = `<h1>${SECTION_BN[section]}</h1>`;
		items.forEach((a, n) => {
			const origin = a.link
				? ` — <a href="${esc(a.link)}">মূল প্রতিবেদন</a>`
				: "";
			const byline = a.author ? ` — ${esc(a.author)}` : "";
			html += `<article id="a${n}"><h3>${esc(a.headline)}</h3><p>${esc(a.excerpt)}</p><p class="meta">${esc(a.source)}${byline}${origin}</p></article>`;
		});
		const fname = `${section.toLowerCase()}.xhtml`;
		zip.file(`OEBPS/${fname}`, xhtml(SECTION_BN[section], html));
		chapters.push({ id: section.toLowerCase(), title: SECTION_BN[section], file: fname });
	}

	const manifestItems = chapters
		.map((c) => `<item id="${c.id}" href="${c.file}" media-type="application/xhtml+xml"/>`)
		.join("");
	const spineItems = chapters.map((c) => `<itemref idref="${c.id}"/>`).join("");
	zip.file(
		"OEBPS/content.opf",
		`<?xml version="1.0" encoding="UTF-8"?>` +
			`<package xmlns="http://www.idpf.org/2007/opf" version="2.0" unique-identifier="bookid">` +
			`<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">` +
			`<dc:identifier id="bookid">bn-news-digest-${esc(runId)}</dc:identifier>` +
			`<dc:title>${esc(title)}</dc:title><dc:language>bn</dc:language></metadata>` +
			`<manifest><item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>` +
			`<item id="css" href="style/panjika.css" media-type="text/css"/>${manifestItems}</manifest>` +
			`<spine toc="ncx">${spineItems}</spine></package>`,
	);
	zip.file(
		"OEBPS/toc.ncx",
		`<?xml version="1.0" encoding="UTF-8"?>` +
			`<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">` +
			`<head><meta name="dtb:uid" content="bn-news-digest-${esc(runId)}"/></head>` +
			`<docTitle><text>${esc(title)}</text></docTitle>` +
			`<navMap>${ncxNavPoints(chapters)}</navMap></ncx>`,
	);

	return zip.generateAsync({ type: "nodebuffer", mimeType: "application/epub+zip" });
}
