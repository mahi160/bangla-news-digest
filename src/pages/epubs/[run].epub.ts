// One EPUB per run, generated at `astro build` time from the committed
// manifest (see src/lib/epub.ts) -- not persisted separately, so nothing
// binary needs to be committed to git; OPDS just always links to these.
import type { APIRoute, GetStaticPaths } from "astro";
import { loadManifest } from "../../lib/state.ts";
import { buildEpub } from "../../lib/epub.ts";

export const prerender = true;

export const getStaticPaths: GetStaticPaths = () => {
	const manifest = loadManifest();
	return manifest.map((r) => ({
		params: { run: r.file.replace(/^runs\//, "").replace(/\.html$/, "") },
		props: { run: r },
	}));
};

export const GET: APIRoute = async ({ props }) => {
	const { run } = props as { run: import("../../lib/types.ts").RunEntry };
	const buffer = await buildEpub(run.grouped, new Date(run.dt), run.file);
	return new Response(new Uint8Array(buffer), {
		headers: {
			"Content-Type": "application/epub+zip",
			"Content-Disposition": `attachment; filename="${run.file.split("/").pop()!.replace(/\.html$/, ".epub")}"`,
		},
	});
};
