# Daily StubHub check

Runs every morning after the collector (which rebuilds `data/watchlist.csv` at about 6:00 a.m. ET).
Goal: record today's StubHub prices for every show on the watchlist. Use only the StubHub connector
tools (`event-search`, `fetch-listings`). Never guess a price, an event id or a match.

## Steps

1. Get the worklist: `python3 -m collector.stubhub_task prepare > work.jsonl` (one show per line).
2. For each show, in order:
   - **If `stubhub_event_id` is empty, find it.** Call `event-search` with `query` = the artist,
     `intent_level` = `HIGH_INTENT`, `event_start_date` and `event_end_date` = the show's date, and
     `venue_name` = the venue. A result matches only if its date is the show's date and its venue is clearly
     the same place (names can differ slightly, e.g. "TD Garden" vs "TD Garden Boston"). If nothing matches,
     try once more without `venue_name`. Still nothing: status `not_found`, move on. When it matches, keep its
     `entityId` as the event id and `formattedMinPrice` as `min_price`, plus the matched name, venue and date.
   - **Get the listings.** Call `fetch-listings` with that `event_id`, `quantity` 1, `sort_by` `NEWPRICE`.
     Save every listing returned as `{"id": listingId, "price": formattedPrice, "section": sectionInfoText,
     "quantity": quantityText}`. Status `ok`, or `no_listings` if the list is empty.
   - On a tool error, retry once; then status `error` with the message in `note`, and move on.
   - Pass the `stubhubId` from the first response as `stubhub_id` on every later call.
3. Append one JSON line per show to `results.jsonl`, in the shape described at the top of
   `collector/stubhub_task.py` (`show_id`, `stubhub_event_id`, `status`, `min_price`, `listings`,
   `matched_name`, `matched_venue`, `matched_date`, `note`). Write each line as soon as the show is done, so
   a long run never loses work. Every watchlist show gets exactly one line.
4. Run `python3 -m collector.stubhub_task record results.jsonl`. It writes `data/stubhub/YYYY-MM-DD.csv`
   and updates `data/stubhub/ids.csv`.
5. Commit only `data/stubhub/` as "StubHub check YYYY-MM-DD" (today in America/New_York) as
   Claude <noreply@anthropic.com>, `git fetch origin main`, rebase, and push to main. Don't commit
   `work.jsonl` or `results.jsonl`, and change nothing else in the repo.
6. End with one line: shows checked, how many had prices, how many were not found.
