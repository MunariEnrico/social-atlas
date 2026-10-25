# Social Atlas

A personal lifestyle and events intelligence platform for **Luxembourg, Venice, Cortina d'Ampezzo, Paris, New York City and London**. It answers one question every morning: *what is happening, what is worth attending, what might I discover early, and what should I book or plan now?*

It runs by itself on free infrastructure: a daily GitHub Actions job collects and verifies events, commits the results to this repository, and republishes a static website. Claude does not need to be open and your computer does not need to be on.

---

## 1. Architecture

```
            ┌────────────────────── GitHub (free) ──────────────────────┐
 06:17 CET  │  Actions: Collect (daily cron, or "Run workflow")          │
 every day  │   ├─ pytest (offline) — a broken pipeline never runs       │
            │   ├─ python -m pipeline.run                                │
            │   │    collect → extract → normalise → dedupe → verify     │
            │   │    → score → persist → briefing → run log              │
            │   ├─ git commit data/db + site/data   (the database)       │
            │   └─ Deploy: site/ → GitHub Pages                          │
            │  Actions: Submit URL (issue form → processed in ~1 min)    │
            └────────────────────────────────────────────────────────────┘
                                   │ static JSON
                                   ▼
            Browser: site/index.html (vanilla JS, no build step)
            My Events + trips → this browser's localStorage (export/import)
```

**Key decisions and trade-offs**

| Decision | Why | Trade-off |
|---|---|---|
| **Git-versioned JSON as the database** (`data/db/`) instead of Supabase | No account, no secrets, no inactivity pausing; every daily commit is a free change history and backup | No server-side writes from the browser, so personal selections live in the browser |
| **My Events / trips in localStorage** with JSON export/import | Zero backend, nothing personal published | Not synced across devices automatically (export → import) |
| **Static vanilla-JS frontend**, no framework or build step | Nothing to break, nothing to upgrade; loads in one request per data file | Less component tooling than React/Next.js |
| **GitHub Actions** for scheduling and admin controls | Free for public repositories; the "Run workflow" button *is* the authenticated admin panel | Admin actions happen on github.com, not inside the site |
| **Deterministic extraction** (schema.org JSON-LD, RSS, iCal, APIs) | Free, repeatable, testable; no LLM call per event | Pages without structured data are not parsed — they become leads or manual sources |
| **Flight search links, not a flight API** | No free, reliable flight API is assumed; links never invent fares | No live prices inside the app |

## 2. Repository layout

```
pipeline/            Python data pipeline (stages in run.py)
  collectors/        one module per collection method
  tests/             offline tests (fixtures, fake fetcher)
data/
  sources.yaml       source registry (hand-edited)
  accounts.yaml      influencer & insider accounts directory
  curated/*.yaml     events researched by hand, each with evidence
  overrides.yaml     manual verifications and corrections
  submissions.yaml   queued URL submissions
  db/                the database: events, signals, source state, run log, briefings
site/                the website (index.html, config.js, assets/, data/ = public JSON)
scripts/             probe_source.py, discover_social.py, add_submission.py, build_preview.py
.github/workflows/   collect.yml, deploy.yml, submit-url.yml, tests.yml
```

## 3. Data model

### Event (`data/db/events.json`, one object per event)

| Field | Meaning |
|---|---|
| `id` | Stable id: `ev-<curated-id>` for researched events, `<title-slug>-<hash>` otherwise |
| `title`, `description` | Short factual text (descriptions are trimmed; articles are never copied) |
| `city`, `neighborhood`, `venue_name`, `venue_address` | Location (nullable) |
| `category`, `subcategory`, `tags` | Rule-based classification |
| `start`, `end`, `all_day`, `timezone`, `occurrences[]` | ISO 8601 with offset, or `YYYY-MM-DD` for date-only listings; displayed in the city's own timezone |
| `date_status` | `confirmed` · `announced` · `tentative` · `unknown` |
| `expected_window`, `date_basis` | For unannounced editions: an estimated window and the reason — never shown as a confirmed date |
| `event_status` | `scheduled`, `cancelled`, `postponed`, `rescheduled` (from the source) |
| `verification_status` | `confirmed`, `announced_pending`, `expected`, `needs_review`, `postponed`, `cancelled`, `past` |
| `verification_evidence[]` | `{url, publisher, reliability, checked_at, note}` |
| `sources[]` | Every source that reported it: `{source_id, name, url, reliability, official, published_at, seen_at}` |
| `published_at` / `first_discovered_at` / `last_updated_at` / `last_verified_at` | Four different dates, never conflated |
| `booking` | See below |
| `scores` | `relevance`, `insider`, `actionability` (0–100) + `reasons` |
| `urgency` | `act_now`, `book_soon`, `last_chance`, `plan_ahead`, `monitor`, `information_pending` |
| `radar[]` | Insider Radar buckets the event qualifies for |
| `trip_suitable`, `confidence`, `coverage` | Planning flag, confidence level, number of independent sources/leads |
| `history[]` | Field changes: `{at, field, old, new, source}` |
| `conflicts[]`, `review_flags[]` | Disagreeing sources, possible duplicates, unreachable official pages |
| `field_sources` | Which source set each important field |

**`booking`** — `reservation` (required / recommended / not_required / unknown), `registration` (required / optional / not_required / unknown), `tickets` (ticketed / free_registration / free_entry / paid_reservation / available_verified / sold_out_verified / not_on_sale_verified / unknown), `access` (public / public_ticketed / invitation_only / members_only / industry_only / restricted / unknown), `price` `{amount|min|max, currency, per_person, fees_included, display, source_url, verified_at}`, `free`, `reservation_url`, `ticket_url`, `registration_url`, `booking_deadline`, `ticket_release`, `access_notes`, `dress_code`, `age_restriction`, `evidence[]` (what the source literally said), `inferred[]` (anything derived rather than read, with the reason), `primary_action`.

Rules enforced in code: "available" or "sold out" only from an official source's structured data or text, stamped with the check time; free ≠ walk-in; a missing booking link ≠ no booking; prices only when a source states them.

### Other stores
- `signals.json` — leads from press, search and submissions: `{title, summary (≤200 chars), url, source, city, category, signal_type (opening/announcement/news/retrospective/submission), published_at, discovered_at, mentioned_dates (unverified), linked_event_id}`. Signals are never promoted to confirmed events automatically.
- `source_state.json` — per source: last attempt, last success, status, last error, consecutive failures, last event/lead found, totals.
- `runs.json` — the last 120 runs with per-source results, counts and errors.
- `briefings/YYYY-MM-DD.json` — each day's briefing (archive) and `latest.json`.
- Past events stay in the database (and `site/data/archive.json`) for 400 days, so recurring editions and source performance can be traced. A past date is never copied forward as next year's date.

## 4. The pipeline (`pipeline/run.py`)

1. **Collection** — each enabled source, in parallel across hosts, one request per host every 3 s, robots.txt respected, 20 s timeout, two retries for timeouts/429/5xx. A source checked within its `frequency_days` is skipped unless forced.
2. **Extraction** — schema.org JSON-LD (listing → detail pages), RSS/Atom, iCal, The Events Calendar REST API, Paris open data. Repeated dates of one listing are grouped into `occurrences`.
3. **Normalisation** — local timezones, ISO dates, implausible dates rejected (one official feed contains a year-0206 item), URLs canonicalised (tracking parameters and Bing redirects removed), categories by keyword rules in EN/FR/IT/DE.
4. **De-duplication** — same city + overlapping dates + title similarity ≥ 0.86 (years and "12th edition" ignored) + venues not disagreeing. 0.66–0.86 is flagged "possible duplicate" for review. A single-day sub-event inside a multi-day event (an opening night inside an art fair) is never merged into it.
5. **Verification** — status rules above; credible sources disagreeing on a date are kept side by side and flagged `needs_review`; official URLs of upcoming events are re-checked weekly (404/410 flagged).
6. **Enrichment** — transparent scores with reasons; Insider Score is labelled a heuristic about our own coverage; trip suitability inferred only from explicit words (festival, fair, fashion week…) and recorded as inferred.
7. **Persistence** — merge into the database, change history kept, most reliable source wins per field.
8. **Daily Briefing** — built only from stored events and leads.
9. **Monitoring** — run status `success` / `partial` / `failed`; "succeeded with nothing new" is distinct from "failed". The job exits non-zero on failure so GitHub shows a red run, but the failed run is still committed and visible in System Health.

## 5. Sources

`data/sources.yaml` holds 78 sources (57 collected automatically, 21 manual with the reason recorded) across the six cities plus multi-city publications. Every entry was probed on 2026-10-25 (status, robots.txt, structure) and records the result. Methods:

| Method | Used for | Examples |
|---|---|---|
| `jsonld_detail` | Official listings whose event pages carry schema.org data | Luxembourg City Tourist Office, Casino Luxembourg, Whitney Museum, V&A |
| `jsonld_page` + `require_locality` | Organisers' pages on Eventbrite (city listings; venues outside the city are dropped) | Luxembourg, Venice, Cortina, Paris/NYC/London business and food & drink |
| `rss_events` | Official feeds where each item is an event | Ville de Luxembourg agenda |
| `tribe_api` | Organiser calendars on WordPress | LHoFT (Luxembourg fintech) |
| `paris_opendata` | City open data | Que faire à Paris (Ville de Paris) |
| `rss_news` | Press and newsletters → leads | The Skint, Eater NY, Londonist, Le Monde, Vogue France, VeneziaToday, The Art Newspaper, Dezeen, WWD… |
| `bing_news` | Short multilingual news searches per city → leads | "Venezia nuovo ristorante", "London private view exhibition"… |
| `curated` | Marquee events researched by hand with evidence | Biennale, La Fenice, fashion weeks, Grand Slams, World Cup… |
| `manual` | Not collectable (robots.txt, 403, login, bot challenge) — listed with the reason | Biennale calendar, Fondation Louis Vuitton, MoMA, Southbank Centre, Dolomiti Superski… |

Google News RSS is **not** used: its robots.txt disallows the search feed for automated agents. Instagram, Facebook, X and Threads are **not** collected: no permitted free method is configured. The accounts directory (`data/accounts.yaml`) lists official accounts found as links on each organisation's own website, accounts you add, and creator accounts suggested by named articles (marked as such).

### Adding a source
1. `python scripts/probe_source.py https://example.org/agenda` — shows status, robots.txt, feed or JSON-LD presence, and advertised feeds.
2. Add an entry to `data/sources.yaml` (copy a similar one). Required: `id`, `name`, `city`, `type`, `reliability` (1 official … 4 aggregator), `url`, `method` and the method's fields (`feed`, `api`, `link_pattern`, `queries`). Optional: `keywords`, `categories`, `frequency_days`, `max_items`, `max_details`. Manual sources need a `reason`.
3. `python -m pipeline.run --sources your-id` to test it, then commit.
4. `python scripts/discover_social.py your-id` adds the account handles linked from its website.

### Adding researched events
Add entries to a file in `data/curated/` (see the existing file for the format). Each needs at least one `evidence` item; use `confirmed` only when an organiser/venue/official page states the dates.

## 6. Setup and deployment (about 15 minutes, no paid plan)

You need a free GitHub account. Nothing else.

1. **Create the repository.** On github.com → New repository → name it e.g. `social-atlas`. Choose **Public** for free GitHub Pages and unlimited Actions minutes (the data is public event information; your personal selections never leave your browser). For a private repository see "Private repository option" below.
2. **Upload the code.** Either drag the unzipped folder into the repository's "Add file → Upload files", or from a terminal:
   ```bash
   cd social-atlas
   git init -b main && git add . && git commit -m "Social Atlas"
   git remote add origin https://github.com/<you>/social-atlas.git
   git push -u origin main
   ```
3. **Allow the workflow to commit data.** Settings → Actions → General → Workflow permissions → **Read and write permissions** → Save.
4. **Turn on Pages.** Settings → Pages → Build and deployment → Source: **GitHub Actions**.
5. **Point the site at your repository.** Edit `site/config.js` and set `repo: "<you>/social-atlas"` (this only builds links to your Actions and issue pages). Commit — this also triggers the first deploy.
6. **Create the label** used by the submission form: Issues → Labels → New label → `submission`.
7. **Run the first collection.** Actions → Collect → Run workflow (mode `force`). After ~5–8 minutes it commits fresh data and deploys. Your site is at `https://<you>.github.io/social-atlas/`.
8. From then on it runs every day at 05:17 UTC.

No environment variables or secrets are required. `.env.example` lists the optional tuning variables.

**Private repository option.** GitHub Pages on a private repository needs a paid GitHub plan. Instead: keep the repository private, delete `.github/workflows/deploy.yml` and the two `deploy:` jobs that call it, then in Cloudflare (free account) → Workers & Pages → Create → Pages → Connect to Git → choose the repository, build command *none*, output directory `site`. Every data commit triggers a Cloudflare build (one per day ≈ 30 of the 500 free monthly builds). Actions minutes then count against the 2,000 free private minutes per month (a run uses roughly 6–9 minutes, so about 200–280 minutes a month).

### Running locally
```bash
pip install -r requirements.txt
python -m pipeline.run --force          # full collection (5–8 minutes)
python -m pipeline.run --reprocess      # no network: recompute statuses, scores, briefing
cd site && python -m http.server 8000   # open http://localhost:8000
python scripts/build_preview.py         # single-file snapshot in dist/
python -m pytest pipeline/tests -q && node --test site/tests/logic.test.js
```

## 7. Operating it

| Task | How |
|---|---|
| Run a collection now | Actions → Collect → Run workflow |
| Refresh selected sources | Run workflow, put ids in **sources** (e.g. `lu-vdl-agenda,ny-whitney`) |
| Retry failed sources | Run workflow, mode `retry-failed` |
| Reprocess without fetching | Run workflow, mode `reprocess` |
| Verify / correct / hide an event | Edit `data/overrides.yaml` on GitHub (the event drawer shows the id and a direct link) |
| Submit a URL | Sources page → Submit a URL (opens a pre-filled issue), or the issue form directly. Processed within a minute; the bot replies with the result. Only the repository owner and collaborators are accepted. |
| Add a source / account | See section 5 |

### Monitoring failures
- **System Health** in the site shows last scheduled / attempted / successful run, per-source results with the exact error, run history and processing counts (needs review, missing booking info, conflicts, possible duplicates, unreachable official pages).
- A failed run shows as a red ❌ in the Actions tab, and GitHub emails you by default.
- A source failing repeatedly shows its consecutive-failure count on the Sources page. Typical causes: the site added bot protection (switch to `manual`), changed its URL (update the registry) or removed its feed.
- If nothing runs: check Actions isn't disabled; in public repositories GitHub disables schedules after 60 days without repository activity — the daily data commit counts as activity, but if runs stop, re-enable the workflow from the Actions tab.

## 8. Costs — mandatory monthly cost: €0

| Service | Used for | Free-tier assumption (checked 2026-10-25) | What could cost money | How to avoid it |
|---|---|---|---|---|
| GitHub (repo, Actions, Issues) | Code, database, scheduler, admin controls | Standard runners free for public repositories; 2,000 min/month on private repos (GitHub Free) | Larger runners; private repo minutes beyond the quota *if* a payment method is on file | Keep `runs-on: ubuntu-latest`; no payment method = usage simply stops at the quota |
| GitHub Pages | Hosting the site | Free for public repos; 1 GB site, 100 GB/month soft bandwidth | Private repo Pages needs a paid plan | Public repo, or Cloudflare Pages |
| Cloudflare Pages (optional) | Hosting for a private repo | 500 builds/month, 20,000 files, 25 MiB per file | Paid plan only for higher limits | One build per day is far below the limit |
| Bing News RSS, Paris open data, public feeds and pages | Collection | Public, no key | None | Polite rate limits are built in |
| Google Fonts | Bodoni Moda + Hanken Grotesk | Free | None | Fonts degrade to system serif/sans if blocked |
| Claude | Building and maintaining the code | Within your plan | The deployed site never calls an AI API | No AI inference in the pipeline |

There is no paid API, no paid LLM call and no paid flight API anywhere in the code. If a free tier changes: the site is plain static files (any static host works — Netlify, Cloudflare, an S3 bucket), and the pipeline is a Python script any scheduler can run (cron on a home server, GitLab CI, etc.).

## 9. What is automated vs manual

**Fully automated, daily:** collection from 57 monitored sources; extraction and normalisation; de-duplication; verification status; past-event archiving; weekly official-link re-checks; scoring, urgency and radar buckets; daily briefing; run log and source health; deployment; URL submission processing.

**Needs a person:** researching marquee events into `data/curated/` (Claude can do this in a maintenance session); confirming events the pipeline marks `needs_review` or `announced_pending` (via `overrides.yaml`); checking Instagram/Facebook/X accounts and submitting interesting posts' URLs; marking events booked; adding sources.

## 10. Features implemented

- Eight sections: Overview, Insider Radar (5 subsections), Daily Briefing, City Calendars (6 cities × day/week/month/year), Trip Planner, My Events, Source Intelligence, System Health.
- Structured Booking & Access on every event, with evidence and inferred-field labelling; primary action button that never marks anything booked.
- Filters: city, category, area, date range, price, tickets, access, status, urgency, reservation/registration required, official source, newly discovered, last-minute, trip-worthy, discovery date. Global search across events, leads, sources and accounts.
- Trip Planner: LUX / VCE departure toggle; event-driven travel windows (tentative dates flagged); prefilled Google Flights, Kayak and Skyscanner searches; optional alternative airports with reasons (TSF, INN); Cortina handled as fly-to-Venice + ground transfer; optional rail link Luxembourg→Paris; saved itineraries grouped by day; overlap and possible-overlap detection using only published times; booking links per event.
- My Events: Saved, Must attend, To book, Booked, Past; priority, notes, booking reference, add to trip, remove; export/import.
- Light and dark themes; responsive down to phone width; keyboard focus and reduced-motion respected.

## 11. Known limitations

- **Social media** is not collected automatically (login walls, paid or app-reviewed APIs). Use the accounts directory and Submit a URL.
- **Pages without structured data** are not parsed; many venues (La Fenice, Biennale calendar, Philharmonie, MoMA) are listed as manual sources with the reason.
- **Venice and Cortina** have thinner automated coverage than Luxembourg, Paris, New York and London; they rely more on news leads and researched events. Venice's main open feeds were empty or blocking at setup time.
- **Leads are leads.** News-based signals carry an "unverified" label; dates mentioned in articles are shown as mentioned, not confirmed.
- **Insider Score** measures how early and narrowly *our* sources saw something, not real-world exclusivity.
- **Flights:** search links only — no verified flight data, fares or seats. Travel times between venues are not estimated.
- **Personal data** (My Events, trips) lives in one browser; use export/import to move it.
- **Bing News RSS** is an unofficial-but-public endpoint and could change; failures will show in System Health.
- **The first data in this repository** was collected from a development sandbox on 2026-10-25 (run log: 57 of 57 sources answered, 304 upcoming events, 232 leads, about 5 minutes), not from GitHub Actions. Some sites answer differently to GitHub's datacenter IPs (blocks, rate limits); those show up as failing sources in System Health. The workflows pass `actionlint` but can only be proven by their first run in your repository.
- **Eventbrite** listings are organiser-published; quality varies, and their relevance score is usually lower than official venues'.
- Scheduled GitHub runs can start late under load and are best-effort.

## 12. Tests

`python -m pytest pipeline/tests -q` — extraction (JSON-LD, RSS events, corrupt dates, already-started items), timezones, URL safety, booking rules, de-duplication (merge, no-merge, review, sub-events), conflicts, history, status rules, urgency/radar, submissions, signal filters, registry and curated-file validation.
`node --test site/tests/logic.test.js` — calendar logic, timezones, flight links for every departure/destination case, itinerary conflicts, filters, trip suggestions, search.
