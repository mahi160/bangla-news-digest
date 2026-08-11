# Bangla News Digest

Pulls RSS from Prothom Alo, Banglanews24, BBC Bangla, ESPN Cricinfo, and a
handful of tech blogs, summarizes each article into Bengali (via `pi` CLI /
Claude Sonnet 5), builds a Bengali EPUB, emails it, and publishes a browsable
archive to GitHub Pages.

Run manually/locally whenever you want a fresh digest -- no scheduled CI run
(pi's subscription auth is local-only, see docs/adr/0003). Pushing the result
updates the GitHub Pages archive automatically (`.github/workflows/pages.yml`
just deploys `site/`, it doesn't run the pipeline).

See `CONTEXT.md` for terminology and `docs/adr/` for the why-behind design decisions.

## Setup

1. **GitHub Pages**: Settings → Pages → Source → "GitHub Actions".

2. **Sections/sources**: edit `config.py`. Adding a source is one dict entry; set `section` to a fixed section name if the feed is already single-category, or `None` to let the model classify each article.

3. **pi auth**: `pi auth check --provider anthropic` should say "ready" (uses your existing subscription login, no API key needed).

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
