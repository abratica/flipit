# Face-value check (Claude in Chrome)

Goal: record the standard face value of every upcoming show at the 20 panel venues (`data/panel.csv`),
once per show, from the Ticketmaster event page. Run with Claude in Chrome, in a Chrome profile that is
**signed out** of Ticketmaster. Read only: never add to cart, never buy.

## Steps

1. Get the worklist: `python3 -m collector.face_task prepare 40 > face_work.jsonl` (one show per line, up to 40).
2. For each show, open its `tm_url` in a new tab and read the prices:
   - Use the price filter, the seat map legend or the price list. Record each **standard** price tier you can see
     as `{"label": ..., "price": ..., "fees_included": true|false}`. Ticketmaster often shows prices with fees
     ("incl. fees"); say which. If you can, switch the display to the price before fees and record that.
   - Leave out Platinum, VIP, packages, "Official Platinum", resale and verified resale.
   - Also record the lowest and highest standard price on the page as `page_min` / `page_max`.
   - Status `ok` when you recorded at least one standard price. Status `no_price` when the page loads but shows no
     standard tickets (sold out, resale only, cancelled), with the reason in `note`. Status `retry` when the page
     shows a queue, a waiting room, a captcha, "tickets not on sale yet" or fails to load; put the reason in `note`
     and move on. Don't wait in queues or solve captchas.
   - Never guess a price. Pause a few seconds between shows.
3. Append one JSON line per show to `face_results.jsonl` (shape at the top of `collector/face_task.py`) as soon as
   the show is done. Every worklist show gets exactly one line.
4. Run `python3 -m collector.face_task record face_results.jsonl`. It updates `data/face/observations.csv` and
   `data/face/status.csv`. Shows marked `retry` come back on later worklists (up to 3 tries).
5. Commit only `data/face/` as "Face check YYYY-MM-DD" (today in America/New_York), `git fetch origin main`,
   rebase, and push to main. Don't commit `face_work.jsonl` or `face_results.jsonl`.
6. End with one line: shows checked, how many got prices, how many need a retry, how many had no price.
