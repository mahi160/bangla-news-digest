#!/usr/bin/env node
// Emails the just-built EPUB for the latest run. Run after `astro build`
// (reads the EPUB astro build already generated in dist/epubs/, doesn't
// rebuild it). No-op if EMAIL_TO isn't set -- same optionality as the old
// pipeline. Port of old/pipeline.py's send_email()/render_email_html().
import { readFileSync, existsSync } from "node:fs";
import { createTransport } from "nodemailer";
import { loadManifest } from "../src/lib/state.ts";
import { makeTeaser } from "../src/lib/collect.ts";
import { retry } from "../src/lib/retry.ts";
import { bnDate, bnNum, bnTime, bnWeekday, edition, toBd } from "../src/lib/dates.ts";
import type { EditionClass } from "../src/lib/dates.ts";
import { SECTIONS, SITE_URL } from "../src/lib/config.ts";
import { SECTION_BN } from "../src/lib/sections.ts";
import type { RunEntry } from "../src/lib/types.ts";

function parseRecipients(raw: string): string[] {
	return raw
		.split(/[,\n;]+/)
		.map((e) => e.trim())
		.filter(Boolean);
}

function esc(t: string | null | undefined): string {
	return String(t ?? "")
		.replace(/&/g, "&amp;")
		.replace(/</g, "&lt;")
		.replace(/>/g, "&gt;")
		.replace(/"/g, "&quot;");
}

function renderEmailHtml(run: RunEntry): string {
	const bd = toBd(new Date(run.dt));
	const [edLabel, edCls] = edition(bd);
	// Email keeps a simple two-look split -- light header for the daytime
	// runs, dark for the two around dark out -- mail clients strip enough
	// styling that four near-identical variants wouldn't read as different.
	const light: EditionClass[] = ["morning", "noon"];
	const isLight = light.includes(edCls);
	const [headBg, headFg] = isLight ? ["#e7d5a8", "#191410"] : ["#191410", "#f1e4c3"];
	const accent = isLight ? "#b82219" : "#f0674c";

	let rows = "";
	for (const section of SECTIONS) {
		const items = run.grouped[section] ?? [];
		if (items.length === 0) continue;
		rows +=
			`<tr><td style="padding:26px 0 6px"><table width="100%" cellpadding="0" cellspacing="0"><tr>` +
			`<td style="font:700 17px Georgia,serif;color:#b82219;white-space:nowrap">${SECTION_BN[section]}</td>` +
			`<td width="100%" style="border-bottom:2px solid #b82219;` +
			`border-top:1px solid #191410;height:5px;font-size:0;line-height:0">&nbsp;</td>` +
			`<td style="font:600 13px Arial,sans-serif;color:#b82219;padding-left:10px">${bnNum(items.length)}</td>` +
			`</tr></table></td></tr>`;
		for (const a of items) {
			const hlStyle = "font:700 16px Georgia,serif;color:#191410;text-decoration:none;line-height:1.45";
			const headline = a.link
				? `<a href="${esc(a.link)}" style="${hlStyle}">${esc(a.headline)}</a>`
				: `<span style="${hlStyle}">${esc(a.headline)}</span>`;
			rows +=
				`<tr><td style="padding:11px 0;border-bottom:1px solid #c2a96f">` +
				headline +
				`<div style="font:12px Arial,sans-serif;color:#6f5f42;padding-top:3px">${esc(a.source)}</div>` +
				`<div style="font:14px Georgia,serif;color:#6f5f42;line-height:1.55;` +
				`padding-top:4px">${esc(makeTeaser(a.excerpt))}</div>` +
				`</td></tr>`;
		}
	}

	const total = SECTIONS.reduce((sum, s) => sum + (run.grouped[s]?.length ?? 0), 0);
	return (
		`<!doctype html><html lang="bn"><body style="margin:0;padding:0;` +
		`background:#f1e4c3"><table width="100%" cellpadding="0" cellspacing="0" ` +
		`style="background:#f1e4c3"><tr><td align="center" style="padding:22px 14px 40px">` +
		`<table cellpadding="0" cellspacing="0" width="560" style="max-width:560px;width:100%">` +
		`<tr><td style="background:${headBg};color:${headFg};border:2px solid #191410;padding:14px 16px">` +
		`<div style="font:600 13px Arial,sans-serif;color:${accent};` +
		`padding-bottom:4px">${edLabel} · ${bnWeekday(bd)}</div>` +
		`<div style="font:700 26px Georgia,serif;line-height:1.2">${bnDate(bd)}` +
		`<span style="font:400 15px Arial,sans-serif;color:${accent};` +
		`padding-left:10px">${bnTime(bd)}</span></div>` +
		`<div style="font:600 13px Arial,sans-serif;color:${accent};` +
		`border-top:1px solid #c2a96f;margin-top:12px;padding-top:8px">` +
		`${bnNum(total)}টি খবর</div>` +
		`</td></tr>${rows}` +
		`<tr><td style="padding:22px 0 0;border-top:3px solid #191410;margin-top:20px;` +
		`font:13px Arial,sans-serif;color:#6f5f42;line-height:1.6">` +
		`পুরো লেখাংশ সংযুক্ত EPUB ফাইলে। ` +
		`<a href="${esc(SITE_URL)}" style="color:#b82219">ওয়েবে দেখুন</a>` +
		`</td></tr></table></td></tr></table></body></html>`
	);
}

async function sendEmail(run: RunEntry, epubBytes: Buffer, epubName: string) {
	const toAddrs = parseRecipients(process.env.EMAIL_TO ?? "");
	if (toAddrs.length === 0) throw new Error("EMAIL_TO has no valid addresses");
	const smtpHost = process.env.SMTP_HOST ?? "smtp.gmail.com";
	const smtpPort = Number(process.env.SMTP_PORT ?? "465");
	const smtpUser = process.env.SMTP_USER!;
	const smtpPass = process.env.SMTP_PASS!;

	const bd = toBd(new Date(run.dt));
	const [edLabel] = edition(bd);
	const counts = SECTIONS.filter((s) => run.grouped[s]?.length)
		.map((s) => `${SECTION_BN[s]} ${bnNum(run.grouped[s]!.length)}`)
		.join(", ");

	const transport = createTransport({
		host: smtpHost,
		port: smtpPort,
		secure: true,
		auth: { user: smtpUser, pass: smtpPass },
	});

	const info = await transport.sendMail({
		from: smtpUser,
		to: smtpUser, // subscribers are Bcc'd -- they shouldn't see each other's addresses
		bcc: toAddrs,
		subject: `${edLabel} · ${bnDate(bd)}, ${bnTime(bd)}`,
		text: `${edLabel} — ${bnDate(bd)}, ${bnTime(bd)}\n${counts}\n\nপুরো সংক্ষেপ সংযুক্ত EPUB ফাইলে। ${SITE_URL}`,
		html: renderEmailHtml(run),
		attachments: [{ filename: epubName, content: epubBytes, contentType: "application/epub+zip" }],
	});
	if (info.rejected?.length) console.warn(`some recipients refused: ${info.rejected}`);
}

async function main() {
	const emailTo = process.env.EMAIL_TO ?? "";
	if (parseRecipients(emailTo).length === 0) {
		console.log("EMAIL_TO not set -- skipping email, digest is still on the site archive");
		return;
	}

	const manifest = loadManifest();
	if (manifest.length === 0) {
		console.log("no runs in manifest -- nothing to email");
		return;
	}
	const run = manifest[0];
	const epubName = run.file.split("/").pop()!.replace(/\.html$/, ".epub");
	const epubPath = `dist/epubs/${epubName}`;
	if (!existsSync(epubPath)) {
		throw new Error(`expected build output missing: ${epubPath} (run \`astro build\` first)`);
	}
	const epubBytes = readFileSync(epubPath);

	try {
		await retry(() => sendEmail(run, epubBytes, epubName), "email send");
	} catch (e) {
		console.error("email send failed after retries -- digest is still on the site archive", e);
	}
}

main();
