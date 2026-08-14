/** Feed-provided links/images get interpolated into href=/src=... on the
 * published site, in EPUB chapters and in subscriber email. Anything that
 * isn't plain http(s) is dropped (defuses javascript:/data:/vbscript: URLs).
 * Applied at each sink that emits one, not only once upstream -- sources are
 * third-party RSS, i.e. untrusted. */
export function safeUrl(url: string | null | undefined): string {
	const u = (url ?? "").trim();
	return /^https?:\/\//i.test(u) ? u : "";
}

/** XML text-node/attribute escaping for feed.xml/opds.xml (hand-built XML,
 * not templated through a framework that escapes for us). */
export function xmlEscape(text: string | null | undefined): string {
	return String(text ?? "")
		.replace(/&/g, "&amp;")
		.replace(/</g, "&lt;")
		.replace(/>/g, "&gt;")
		.replace(/"/g, "&quot;")
		.replace(/'/g, "&apos;");
}
