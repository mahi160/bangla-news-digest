# Bangla News Digest

Pulls RSS from Prothom Alo, Banglanews24, BBC Bangla, ESPN Cricinfo, and a
handful of tech blogs, collects each article's headline + a plain-text
excerpt (no AI summary, see docs/adr/0004), builds a Bengali EPUB, emails it,
and publishes a browsable archive + RSS + OPDS feed to GitHub Pages.

The site is styled as a Bengali almanac (পঞ্জিকা) in two inks on saffron
newsprint -- see docs/adr/0005 before changing colours, tracking, or the
index structure. The stylesheet lives in `STYLE_CSS` in `pipeline.py` and is
written out to `site/style.css` on every run.

Runs on a schedule (06:00/18:00 Bangladesh time, `.github/workflows/digest.yml`)
and can also be run manually/locally. Either way it commits+pushes `site/` and
`state.json`; `.github/workflows/pages.yml` deploys the pushed `site/` to Pages.

See `CONTEXT.md` for terminology and `docs/adr/` for the why-behind design decisions.

## Setup

1. **GitHub Pages**: Settings → Pages → Source → "GitHub Actions".

2. **Sections/sources/knobs**: edit `config.py`. Adding a source is one dict entry; set `section` to a fixed section name if the feed is already single-category, or `None` to fall back to `Local`. Retention window, excerpt/teaser length, RSS cap, and local timezone are all knobs there too.

3. **Email (optional)**: set `SMTP_USER`/`SMTP_PASS`/`EMAIL_TO` as repo secrets (or env vars locally) to also email subscribers. Each send is a plain-text part + an HTML digest + the EPUB attached. Without the secrets, the run still updates the site/feeds, it just logs and skips the email step.

## Run locally

```
python -m venv .venv && .venv/bin/pip install -r requirements.txt
SMTP_USER=... SMTP_PASS=... EMAIL_TO=... .venv/bin/python pipeline.py
git add state.json site/ && git commit -m "digest: $(date -u +%Y-%m-%dT%H:%M)Z" && git push
```

`EMAIL_TO` is a comma/newline/semicolon-separated subscriber list -- add a subscriber by adding their address there. Since it's a plain env var (not a repo file) subscriber emails never get committed to this public repo; they're Bcc'd on send too.

## Tests

```
.venv/bin/python test_pipeline.py
```
