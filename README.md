# helpdesk-ticket-tracker

A lightweight command-line help desk ticketing system written in Python and backed by SQLite.

I built this to mirror the Tier 1/2 support workflow I use day to day — opening tickets for
clinical and business users, assigning them, logging work notes, closing them with a documented
resolution, and reporting on the queue. No external dependencies: everything runs on the Python
standard library.

## Features

- Create tickets with a requester, category, and priority (`low`, `medium`, `high`, `critical`)
- Assign tickets to a technician and track status (`open` → `in_progress` → `closed`)
- Add timestamped work notes to any ticket
- Close tickets with a required resolution (no "closed with no explanation" tickets)
- Reopen tickets when an issue comes back
- Queue report: counts by status, open tickets by priority, and workload per technician
- Queue is sorted critical-first, then oldest-first, so the right ticket is always at the top

## Quick start

```bash
git clone https://github.com/elijahawusinu/helpdesk-ticket-tracker.git
cd helpdesk-ticket-tracker

python tickets.py create "Printer offline in Suite 204" --user jsmith --category printer --priority high
python tickets.py create "Password reset needed" --user kbrown --category account
python tickets.py list
python tickets.py assign 1 --tech elijah
python tickets.py note 1 "Reseated network cable, printer back online" --author elijah
python tickets.py close 1 --resolution "Loose Ethernet cable at wall jack"
python tickets.py show 1
python tickets.py report
```

Example output of `list`:

```
  ID  PRI      STATUS       ASSIGNEE     REQUESTER    TITLE
------------------------------------------------------------------------------
   1  high     in_progress  elijah       jsmith       Printer offline in Suite 204
   2  medium   open         -            kbrown       Password reset needed
```

The database is created automatically as `tickets.db` in the current directory. Use `--db path/to/file.db`
to keep separate queues (e.g. one per site).

## Project layout

```
tickets.py          # TicketStore (all SQLite logic) + argparse CLI
tests/
  test_tickets.py   # pytest suite covering the store and the CLI end to end
```

## Running the tests

```bash
pip install -r requirements.txt
pytest
```

## Design notes

- **Separation of concerns.** `TicketStore` owns every database operation and knows nothing about
  the terminal; the CLI layer only parses arguments and prints. That makes the core easy to test and
  easy to reuse behind a web front end later.
- **Validation at the boundary.** Bad priorities, blank titles, and closing without a resolution are
  rejected before they reach the database.
- **Parameterized SQL everywhere** — no string-formatted queries, no SQL injection.

## Possible next steps

- SLA tracking (time-to-first-response, time-to-resolve per priority)
- CSV export for weekly reporting
- A small Flask or FastAPI front end on top of `TicketStore`

## Author

Elijah Awusinu — IT support technician, B.S. Information Technology (Towson University),
CompTIA Security+, AWS Certified Solutions Architect – Associate.
