import { bdDateKey, toBd } from "./dates.ts";
import type { RunEntry } from "./types.ts";

/** The newest run's calendar date, and every other run sharing it (up to
 * `maxN` runs/day -- 06/12/18/24 BD). Filtering by date rather than just
 * slicing manifest[:maxN] matters in the ~6h window after the night edition
 * ticks BD's calendar over to a new date but before the morning run has
 * pruned anything: without this, the index would mix that one new-date run
 * in with up to three still-unpruned runs from the date before. */
export function todaysEditions(manifest: RunEntry[], maxN = 4): RunEntry[] {
	if (manifest.length === 0) return [];
	const newestKey = bdDateKey(toBd(new Date(manifest[0].dt)));
	return manifest.filter((r) => bdDateKey(toBd(new Date(r.dt))) === newestKey).slice(0, maxN);
}

/** Keep only runs on/after cutoffDateKey; return the dropped ones too so the
 * caller can delete their archived EPUBs. */
export function partitionBeforeDate(
	manifest: RunEntry[],
	cutoffDateKey: string,
): { kept: RunEntry[]; dropped: RunEntry[] } {
	const kept: RunEntry[] = [];
	const dropped: RunEntry[] = [];
	for (const r of manifest) {
		const key = bdDateKey(toBd(new Date(r.dt)));
		(key >= cutoffDateKey ? kept : dropped).push(r);
	}
	return { kept, dropped };
}
