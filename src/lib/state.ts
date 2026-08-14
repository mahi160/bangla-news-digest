// Persisted state, read/written directly as files (same pattern as the old
// Python pipeline) -- no DB needed for a cron-run static generator.
//
// - state.json (repo root): seen-urls per source, dedup only, never shipped.
// - public/runs.json: today's runs incl. full grouped article data -- both
//   the build's input (site/feed/opds/epub generation reads it) AND,
//   unmodified, part of the shipped site (dist/runs.json) -- same dual role
//   it had as site/runs.json in the old pipeline. EPUBs aren't persisted
//   separately -- see src/pages/epubs/[run].epub.ts, generated fresh from
//   this file at build time.

import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import type { RunEntry } from "./types.ts";

// process.cwd(), not import.meta.url -- the latter resolves to a bundled
// (and wrong) location once Vite/Astro processes this module.
const ROOT = process.cwd();
export const STATE_PATH = join(ROOT, "state.json");
export const RUNS_MANIFEST_PATH = join(ROOT, "public/runs.json");

export interface SourceState {
	seen_urls: string[];
}
export type State = Record<string, SourceState>;

export function loadState(): State {
	return existsSync(STATE_PATH) ? JSON.parse(readFileSync(STATE_PATH, "utf-8")) : {};
}

export function saveState(state: State): void {
	writeFileSync(STATE_PATH, JSON.stringify(state, null, 2) + "\n");
}

export function loadManifest(): RunEntry[] {
	return existsSync(RUNS_MANIFEST_PATH) ? JSON.parse(readFileSync(RUNS_MANIFEST_PATH, "utf-8")) : [];
}

export function saveManifest(manifest: RunEntry[]): void {
	mkdirSync(join(ROOT, "public"), { recursive: true });
	writeFileSync(RUNS_MANIFEST_PATH, JSON.stringify(manifest, null, 2) + "\n");
}
