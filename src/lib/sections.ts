import type { Section } from "./config";

// SECTIONS (config.ts) are English because they're dict keys/state; readers
// get Bangla labels here.
export const SECTION_BN: Record<Section, string> = {
	Local: "দেশ",
	International: "আন্তর্জাতিক",
	Entertainment: "বিনোদন",
	Tech: "প্রযুক্তি",
	Sports: "খেলা",
};

// References the Tailwind theme tokens in global.css (--color-local etc.)
// rather than duplicating hex values -- one source of truth for the palette.
export const SECTION_ACCENT: Record<Section, string> = {
	Local: "var(--color-local)",
	International: "var(--color-international)",
	Entertainment: "var(--color-entertainment)",
	Tech: "var(--color-tech)",
	Sports: "var(--color-sports)",
};
