// Bangla date/number formatting + twice(-now-four)-daily edition logic.
// Port of old/pipeline.py's date-formatting section.
//
// ponytail: fixed 06:00/12:00/18:00/00:00 BD cadence per README -- no
// timezone-of-reader handling needed for a single-author digest site.

import { LOCAL_TZ_OFFSET_HOURS } from "./config.ts";

const BN_DIGITS = "০১২৩৪৫৬৭৮৯";
const BN_MONTHS = [
	"জানুয়ারি", "ফেব্রুয়ারি", "মার্চ", "এপ্রিল", "মে", "জুন", "জুলাই",
	"আগস্ট", "সেপ্টেম্বর", "অক্টোবর", "নভেম্বর", "ডিসেম্বর",
];
// JS getDay(): 0=Sunday..6=Saturday. Python's weekday(): 0=Monday..6=Sunday.
const BN_WEEKDAYS_BY_JS_DAY = ["রবিবার", "সোমবার", "মঙ্গলবার", "বুধবার", "বৃহস্পতিবার", "শুক্রবার", "শনিবার"];

export function bnNum(n: number | string): string {
	return String(n).replace(/[0-9]/g, (d) => BN_DIGITS[Number(d)]);
}

/** A UTC Date, viewed as its Bangladesh-local wall-clock fields. */
export interface BdDate {
	utc: Date;
	year: number;
	month: number; // 1-12
	day: number;
	hour: number;
	minute: number;
	/** Weekday index, Python-style: 0=Monday..6=Sunday (for date-only comparisons). */
	weekdayIdx: number;
}

/** Editions/dates are always shown in Bangladesh local time -- every
 * display/labeling call site converts through here first. */
export function toBd(utc: Date): BdDate {
	const shifted = new Date(utc.getTime() + LOCAL_TZ_OFFSET_HOURS * 3600_000);
	return {
		utc,
		year: shifted.getUTCFullYear(),
		month: shifted.getUTCMonth() + 1,
		day: shifted.getUTCDate(),
		hour: shifted.getUTCHours(),
		minute: shifted.getUTCMinutes(),
		weekdayIdx: (shifted.getUTCDay() + 6) % 7,
	};
}

/** Calendar-date-only key for same-day comparisons (pruning, today's editions). */
export function bdDateKey(bd: BdDate): string {
	return `${bd.year}-${String(bd.month).padStart(2, "0")}-${String(bd.day).padStart(2, "0")}`;
}

export function bnDate(bd: BdDate): string {
	return bnNum(`${bd.day} ${BN_MONTHS[bd.month - 1]}, ${bd.year}`);
}

export function bnWeekday(bd: BdDate): string {
	const jsDay = (bd.weekdayIdx + 1) % 7; // back to JS-style for the lookup table
	return BN_WEEKDAYS_BY_JS_DAY[jsDay];
}

export function bnTime(bd: BdDate): string {
	const period =
		bd.hour < 4 ? "রাত" : bd.hour < 6 ? "ভোর" : bd.hour < 12 ? "সকাল" :
		bd.hour < 16 ? "দুপুর" : bd.hour < 18 ? "বিকাল" : bd.hour < 20 ? "সন্ধ্যা" : "রাত";
	const h12 = bd.hour % 12 || 12;
	return bnNum(`${period} ${h12}:${String(bd.minute).padStart(2, "0")}`);
}

export type EditionClass = "morning" | "noon" | "evening" | "night";

// Four runs/day, six hours apart (06/12/18/24 BD) -- each bucket is centred
// on its own scheduled hour with a 3h either-side margin, so a run that
// fires a little early/late from CI scheduling drift still lands in the
// bucket it was meant for.
const EDITIONS: [number, string, EditionClass][] = [
	[3, "সকালের সংস্করণ", "morning"], // ~06:00
	[9, "দুপুরের সংস্করণ", "noon"], // ~12:00
	[15, "সান্ধ্য সংস্করণ", "evening"], // ~18:00
	[21, "রাতের সংস্করণ", "night"], // ~00:00 (wraps past 21:00)
];

/** [label, css-class] for the four-times-daily run cadence. */
export function edition(bd: BdDate): [string, EditionClass] {
	for (let i = EDITIONS.length - 1; i >= 0; i--) {
		const [start, label, cls] = EDITIONS[i];
		if (bd.hour >= start) return [label, cls];
	}
	return [EDITIONS[EDITIONS.length - 1][1], EDITIONS[EDITIONS.length - 1][2]]; // hour < 3 -> still last night's "night" bucket
}

// Mirrors the .horizon.<cls> rules -- generated per page since which
// editions exist varies day to day (see index page tabs).
export const HORIZON_GRADIENT: Record<EditionClass, string> = {
	morning: "linear-gradient(100deg,#F6D9A8,#E2963C 45%,#B9542F 85%)",
	noon: "linear-gradient(100deg,#FCE9C6,#E2B33C 50%,#C9862E 100%)",
	evening: "linear-gradient(100deg,#2C2653,#5B4B8A 55%,#8A7BB8 100%)",
	night: "linear-gradient(100deg,#141224,#2C2653 55%,#453E78 100%)",
};
