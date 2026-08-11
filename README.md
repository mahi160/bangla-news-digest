# Bangla News Digest

Twice a day (6am / 6pm Bangladesh time), pulls RSS from Prothom Alo, Banglanews24,
BBC Bangla, ESPN Cricinfo, and a handful of tech blogs, summarizes each article
into Bengali (via Claude Code / Opus), builds a Bengali EPUB, emails it, and
publishes a browsable archive to GitHub Pages.

See `CONTEXT.md` for terminology and `docs/adr/` for the why-behind design decisions.

## Setup

1. **Repo secrets** (Settings → Secrets and variables → Actions):
   - `ANTHROPIC_API_KEY` — for the Claude Code CLI in CI
   - `SMTP_USER` / `SMTP_PASS` — an email account + [app password](https://support.google.com/accounts/answer/185833) (Gmail default; override `SMTP_HOST`/`SMTP_PORT` for another provider)
   - `EMAIL_TO` — where the digest gets sent

2. **GitHub Pages**: Settings → Pages → Source → "GitHub Actions" (the workflow deploys `site/` itself, no branch/folder setting needed).

3. **Sections/sources**: edit `config.py`. Adding a source is one dict entry; set `section` to a fixed section name if the feed is already single-category, or `None` to let Claude classify each article.

## Run locally

```
python -m venv .venv && .venv/bin/pip install -r requirements.txt
ANTHROPIC_API_KEY=... SMTP_USER=... SMTP_PASS=... EMAIL_TO=... .venv/bin/python pipeline.py
```

## Tests

```
.venv/bin/python test_pipeline.py
```
