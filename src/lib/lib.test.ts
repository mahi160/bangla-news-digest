// Smallest possible self-check for the trickiest ported logic (Bangla
// weekday/edition bucketing, headline-dedup, teaser cut). Run: `npm test`.
import { test } from "node:test";
import assert from "node:assert/strict";
import { bnNum, toBd, edition, bnWeekday, bdDateKey } from "./dates.ts";
import { classifyByLink } from "./classify.ts";
import { groupBySection, makeTeaser } from "./collect.ts";

test("bnNum converts ASCII digits to Bangla digits", () => {
	assert.equal(bnNum(123), "১২৩");
});

test("toBd/edition buckets a UTC instant into the right BD edition", () => {
	// 2024-01-01T00:05:00Z + 6h = 2024-01-01 06:05 BD -> morning
	const bd = toBd(new Date("2024-01-01T00:05:00Z"));
	assert.equal(bd.hour, 6);
	const [label, cls] = edition(bd);
	assert.equal(cls, "morning");
	assert.equal(label, "সকালের সংস্করণ");
});

test("edition wraps hour<3 to the previous night bucket", () => {
	// 2024-01-01T18:30:00Z + 6h = 2024-01-02 00:30 BD -> still "night"
	const bd = toBd(new Date("2024-01-01T18:30:00Z"));
	const [, cls] = edition(bd);
	assert.equal(cls, "night");
});

test("bnWeekday matches a known date (2024-01-01 is a Monday)", () => {
	const bd = toBd(new Date("2024-01-01T00:00:00Z")); // 06:00 BD, still Jan 1
	assert.equal(bnWeekday(bd), "সোমবার");
});

test("bdDateKey is stable for same-day comparisons", () => {
	const bd = toBd(new Date("2024-01-01T20:00:00Z")); // -> 2024-01-02 02:00 BD
	assert.equal(bdDateKey(bd), "2024-01-02");
});

test("classifyByLink reads outlet URL path, falls back to null", () => {
	assert.equal(classifyByLink("https://www.prothomalo.com/sports/abc"), "Sports");
	assert.equal(classifyByLink("https://www.prothomalo.com/technology/abc"), "Tech");
	assert.equal(classifyByLink("https://www.banglanews24.com/news/123456"), null);
	assert.equal(classifyByLink(null), null);
});

test("groupBySection strips a repeated headline from the excerpt", () => {
	const grouped = groupBySection([
		{
			source: "Test", sectionHint: "Tech", title: "শিরোনাম টেস্ট",
			link: "https://example.com/a", author: "", image: "",
			text: "শিরোনাম টেস্ট রাখা হলো এখানে আসল লেখা শুরু হচ্ছে।",
			published: null, feedIndex: 0,
		},
	]);
	const a = grouped.Tech![0];
	assert.ok(!a.excerpt.startsWith("শিরোনাম টেস্ট"), `got: ${a.excerpt}`);
});

test("groupBySection drops javascript: URLs via safeUrl", () => {
	const grouped = groupBySection([
		{
			source: "Test", sectionHint: "Local", title: "t",
			link: "javascript:alert(1)", author: "", image: "javascript:alert(2)",
			text: "body text here", published: null, feedIndex: 0,
		},
	]);
	const a = grouped.Local![0];
	assert.equal(a.link, "");
	assert.equal(a.image, "");
});

test("groupBySection ranks multi-outlet (echoed) stories before single-source ones", () => {
	const grouped = groupBySection([
		{
			source: "A", sectionHint: "Tech", title: "একটি এক্সক্লুসিভ খবর যা শুধু এই সংস্থা দিয়েছে",
			link: "https://a.example/1", author: "", image: "", text: "body", published: null, feedIndex: 0,
		},
		{
			source: "B", sectionHint: "Tech", title: "বড় ভূমিকম্প আঘাত হানলো রাজধানীতে আজ সকালে",
			link: "https://b.example/1", author: "", image: "", text: "body", published: null, feedIndex: 5,
		},
		{
			source: "C", sectionHint: "Tech", title: "বড় ভূমিকম্প আঘাত হানলো রাজধানীতে আজ সকাল বেলায়",
			link: "https://c.example/1", author: "", image: "", text: "body", published: null, feedIndex: 2,
		},
	]);
	const headlines = grouped.Tech!.map((a) => a.headline);
	// the two-outlet earthquake story (echoed) should rank above the
	// single-source exclusive, regardless of feed position.
	assert.ok(headlines[0].includes("ভূমিকম্প"), `got order: ${headlines}`);
	assert.ok(headlines[1].includes("ভূমিকম্প"), `got order: ${headlines}`);
});

test("groupBySection uses feedIndex as a tiebreaker within equal echo counts", () => {
	const grouped = groupBySection([
		{
			source: "A", sectionHint: "Tech", title: "দ্বিতীয় সংবাদ আজকের",
			link: "https://a.example/2", author: "", image: "", text: "body", published: null, feedIndex: 3,
		},
		{
			source: "A", sectionHint: "Tech", title: "প্রথম সংবাদ আজকের",
			link: "https://a.example/1", author: "", image: "", text: "body", published: null, feedIndex: 0,
		},
	]);
	const headlines = grouped.Tech!.map((a) => a.headline);
	assert.deepEqual(headlines, ["প্রথম সংবাদ আজকের", "দ্বিতীয় সংবাদ আজকের"]);
});

test("makeTeaser cuts at Bengali sentence-ending mark within the cap", () => {
	assert.equal(makeTeaser("প্রথম বাক্য।দ্বিতীয় বাক্য চলতে থাকে"), "প্রথম বাক্য।");
});

test("makeTeaser falls back to word-boundary ellipsis past the cap", () => {
	const long = "word ".repeat(40).trim();
	const out = makeTeaser(long, 20);
	assert.ok(out.endsWith("…"));
	assert.ok(out.length <= 21);
});
