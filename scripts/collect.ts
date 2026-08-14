#!/usr/bin/env node
// Fetch new articles, update state.json + public/runs.json. Run before
// `astro build` -- build itself is a pure function of whatever this script
// leaves on disk (no network access at build time). Port of
// old/pipeline.py's main() (minus EPUB/HTML/email -- Astro build generates
// those from what this script writes, see TODO.temp.md).
import { loadState, saveState, loadManifest, saveManifest } from "../src/lib/state.ts";
import { fetchAllNewArticles, groupBySection } from "../src/lib/collect.ts";
import { SECTIONS } from "../src/lib/config.ts";
import { bdDateKey, toBd } from "../src/lib/dates.ts";
import { edition } from "../src/lib/dates.ts";
import { partitionBeforeDate } from "../src/lib/runs.ts";
import type { RunEntry } from "../src/lib/types.ts";

function runFileFor(now: Date): string {
	// UTC-based timestamp (not BD-localized) -- matches old pipeline.py's
	// run_dt.strftime('%Y-%m-%d-%H%M') on its UTC `now`.
	const p = (n: number, len = 2) => String(n).padStart(len, "0");
	return (
		`runs/${now.getUTCFullYear()}-${p(now.getUTCMonth() + 1)}-${p(now.getUTCDate())}` +
		`-${p(now.getUTCHours())}${p(now.getUTCMinutes())}.html`
	);
}

async function main() {
	const now = new Date();
	const state = loadState();

	const raw = await fetchAllNewArticles(state, now);
	if (raw.length === 0) {
		console.log("no new articles this run, skipping digest");
		saveState(state);
		return;
	}

	console.log(`collecting ${raw.length} articles (no AI summary)`);
	const grouped = groupBySection(raw);

	let manifest = loadManifest();
	const bdNow = toBd(now);
	const [, edCls] = edition(bdNow);
	// "night" (~00:00 BD) is the *first* of each calendar date's four runs --
	// 00:00 lands before that date's own morning/noon/evening runs -- so it's
	// the one that should drop everything from the date before.
	if (edCls === "night") {
		manifest = partitionBeforeDate(manifest, bdDateKey(bdNow)).kept;
	}

	const counts = Object.fromEntries(
		SECTIONS.filter((s) => grouped[s]?.length).map((s) => [s, grouped[s]!.length]),
	) as RunEntry["counts"];

	const entry: RunEntry = { dt: now.toISOString(), file: runFileFor(now), counts, grouped };
	manifest.unshift(entry);
	saveManifest(manifest);
	saveState(state);
	console.log(`run complete -- wrote ${entry.file}`);
}

main().catch((e) => {
	console.error("run failed", e);
	process.exitCode = 1;
});
