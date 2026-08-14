import type { Section } from "./config.ts";

// First URL path segment -> section, for feeds that mix categories but whose
// own site structure (e.g. prothomalo.com/sports/..., /technology/...)
// already encodes one. No AI: just reading the outlet's own URLs. Outlets
// with opaque/ID-only paths (Banglanews24's /news/<id>, BBC's hashed
// /articles/<id>) don't match anything here and fall back to Local same as
// before -- see BBC's topic-specific sources in config.ts instead.
const PATH_SECTION: Record<string, Section> = {
	sports: "Sports", sport: "Sports", cricket: "Sports",
	entertainment: "Entertainment", showbiz: "Entertainment", glitz: "Entertainment",
	technology: "Tech", tech: "Tech", science: "Tech",
	world: "International", international: "International",
};

export function classifyByLink(link: string | null | undefined): Section | null {
	if (!link) return null;
	let path: string;
	try {
		path = new URL(link).pathname;
	} catch {
		return null;
	}
	const first = path.replace(/^\/+|\/+$/g, "").split("/")[0]?.toLowerCase();
	return first ? PATH_SECTION[first] ?? null : null;
}
