# Bangla News Digest

Fetches Bangla/tech RSS feeds, builds a static archive + `feed.xml` +
`opds.xml` + per-run EPUBs, deploys to GitHub Pages. Astro (static output),
TypeScript, no server.

`astro build` *is* the generator -- every page/feed/EPUB is built from one
committed file, `public/runs.json`. `npm run collect` is what updates it
(fetches new articles, dedupes against `state.json`).

## Run

```
npm install
npm run collect   # fetch new articles -> state.json, public/runs.json
npm run build     # generate dist/ (site, feed.xml, opds.xml, EPUBs)
npm run preview   # serve dist/ locally
npm test          # unit tests
```

## Config

Sources/sections/knobs: `src/lib/config.ts`. Colors/fonts: the `@theme`
block in `src/styles/global.css`.

## Deploy

`.github/workflows/digest.yml` runs on a cron, does the whole cycle
(collect -> build -> email if `EMAIL_TO`/`SMTP_*` secrets are set -> commit
`state.json`/`public/runs.json` -> deploy). `pages.yml` is a manual
fallback to redeploy after a code change without waiting for the next
collect.
