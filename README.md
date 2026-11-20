# FlipIt

Tracks US concert ticket resale prices every day, to learn which venues (and later, artists)
resell well above face value.

## How it works

Every morning at 6:00 a.m. Eastern, a GitHub Action runs `python -m collector.run`:

1. **Find shows.** Every US concert on Ticketmaster and SeatGeek, up to 6 months out.
2. **Match** the same show across both sources (same date and state, similar venue and artist).
3. **Capture new artists** on Spotify (followers, popularity, genres) the first time they appear.
4. **Snapshot** every upcoming show: face value (Ticketmaster) and resale prices and listing count (SeatGeek).
5. **Score** finished shows at fixed checkpoints and rate venues.
6. **Write the brief** the app shows (`data/app/brief.json`).
7. **Save** everything to `data/` in this repo.

If a source fails, the run still saves what it got, then shows as failed so GitHub sends an email.

## Data

| File | One row per |
|---|---|
| `data/shows.csv` | show (first-sighting fields never change) |
| `data/artists.csv` | artist, with Spotify numbers from the day first captured |
| `data/venues.csv` | venue, with capacity and where that number came from |
| `data/venue_overrides.csv` | hand-entered capacity fixes (these win over SeatGeek's number) |
| `data/snapshots/YYYY-MM-DD.csv.gz` | upcoming show, per day |
| `data/outcomes.csv` | show with face value: resale ask / face at each checkpoint |
| `data/venue_stats.csv` | venue scorecard |

**Checkpoints:** days 1, 3, 7, 14 and 30 after the on-sale; days 30, 14, 7, 3 and 1 before the show; show day.

**Break-even:** buying at face costs about 20% in fees, and resale sellers lose about 15%, so a show
is profitable when the cheapest resale ask is at least **1.41x** face value. Constants live in
`collector/score.py`.

**Venue tiers** (completed shows with a score): under 5 tracking, 5–9 provisional, 10–19 ranked, 20+ confirmed.

## Running a test

Actions tab → **Daily collect** → Run workflow → mode `test`. This collects Massachusetts only, 30 days out,
and saves nothing to the repo; the output is attached to the run.

## Daily StubHub check (added Nov 20)

The free APIs no longer return resale prices, so prices come from a daily scheduled Claude task that uses the
StubHub connector on a 60-show **watchlist** (`data/watchlist.csv`), rebuilt by the collector each morning:

| Group | Share | What it is |
|---|---|---|
| `second_show` | 1/4 | original date of an artist who just added a nearby date (likely sold out) |
| `climber` | 1/4 | SeatGeek demand score rising fastest over the past week |
| `onsale_soon` | 1/4 | high-demand shows going on sale in the next 10 days |
| `random` | 1/4 | deterministic random draw of ordinary shows, the comparison group |

Shows stay on the list until they happen (max 2 per artist). The task runs
`python -m collector.stubhub_task prepare`, looks each show up on StubHub, then
`python -m collector.stubhub_task record results.jsonl`, which writes `data/stubhub/YYYY-MM-DD.csv`
(cheapest price plus the cheapest listing IDs, so listings that vanish overnight can be counted as probable sales)
and `data/stubhub/ids.csv`. `data/stubhub_growth.csv` tracks each show's price from its first check to now:
face value is missing for almost all high-demand shows, so price growth is the main measure.

Spotify lookups are off (`SPOTIFY_ENABLED=1` turns them back on): developer mode no longer returns follower numbers.
