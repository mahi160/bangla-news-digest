# Bangla News Digest

An automated system that pulls Bangla news and tech RSS feeds, summarizes them, and delivers a Bengali EPUB digest by email twice a day.

## Language

**Run**:
A single digest generation cycle, kicked off manually (`python pipeline.py` on your own machine), that gathers articles published since the previous Run, summarizes them, builds an EPUB, and emails it out. Pushing the result updates the GitHub Pages archive.
_Avoid_: Batch, cycle, job

**Section**:
One of five fixed categories an article is filed under: Local, International, Entertainment, Tech, Sports.
_Avoid_: Category, Media (Media is ambiguous — see Entertainment)

**Source**:
An RSS feed supplying articles (e.g. Prothom Alo's national feed, omg ubuntu's feed). Each Source maps to exactly one Section, set by its own RSS category. Sources whose feed mixes multiple categories fall back to per-article LLM classification into a Section.
_Avoid_: Feed (feed = the RSS mechanism; Source = the thing that owns a Section mapping)

**Entertainment** (Section):
Showbiz/entertainment news — films, TV, music, celebrities (বিনোদন). Not media-industry news (press/journalism business) and not social-media/viral content.
_Avoid_: Media

**Subscriber**:
An email address that receives every Run's digest. Stored as a comma-separated list in the `EMAIL_TO` secret (not committed to the repo — this repo is public, subscriber emails are PII). Bcc'd on send so subscribers don't see each other's addresses.
_Avoid_: Customer, recipient
