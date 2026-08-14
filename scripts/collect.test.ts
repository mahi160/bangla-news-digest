import { test } from "node:test";
import assert from "node:assert/strict";
import { partitionBeforeDate, todaysEditions } from "../src/lib/runs.ts";
import type { RunEntry } from "../src/lib/types.ts";

function entry(dt: string): RunEntry {
	return { dt, file: `runs/${dt}.html`, counts: {}, grouped: {} };
}

test("partitionBeforeDate drops runs from before the cutoff (BD-local date)", () => {
	const manifest = [
		entry("2024-01-02T00:30:00Z"), // 06:30 BD, 2024-01-02
		entry("2024-01-01T15:00:00Z"), // 21:00 BD, 2024-01-01
		entry("2024-01-01T09:00:00Z"), // 15:00 BD, 2024-01-01
	];
	const { kept, dropped } = partitionBeforeDate(manifest, "2024-01-02");
	assert.equal(kept.length, 1);
	assert.equal(dropped.length, 2);
	assert.equal(kept[0].dt, manifest[0].dt);
});

test("todaysEditions caps at 4 and only includes the newest calendar date", () => {
	const manifest = [
		entry("2024-01-02T00:30:00Z"), // 2024-01-02 BD
		entry("2024-01-01T15:00:00Z"), // 2024-01-01 BD -- different day, excluded
	];
	const editions = todaysEditions(manifest);
	assert.equal(editions.length, 1);
	assert.equal(editions[0].dt, manifest[0].dt);
});

test("todaysEditions on an empty manifest returns empty", () => {
	assert.deepEqual(todaysEditions([]), []);
});
