# ticket-history-store Specification

## Purpose

Per-ticket persistence layer for AICLI ticket history: replaces the single
shared `tickets.json` with one file per ticket to remove cross-ticket data
loss, adds a lazy non-destructive migration path, bounds rendered history to
a fixed number of rounds, and applies merge-on-write semantics to shrink (not
eliminate) the write-race window for two terminals on the same ticket.

## Requirements

### Requirement: Per-Ticket File Storage

The system MUST persist each ticket's data (description, rounds, branch,
cache state) in its own file under `~/.mycontext/tickets/<ticket_id>.json`,
keyed by ticket id instead of a single shared file.

#### Scenario: New ticket creates its own file

- GIVEN no per-ticket file exists for `PROJ-100`
- WHEN a round is saved for `PROJ-100`
- THEN a file `~/.mycontext/tickets/PROJ-100.json` is created containing that round
- AND no other ticket's file is read or rewritten

#### Scenario: Two terminals on different tickets never collide

- GIVEN terminal A saves a round for `PROJ-100` and terminal B saves a round for `PROJ-200` concurrently
- WHEN both writes complete
- THEN `PROJ-100.json` contains only A's round and `PROJ-200.json` contains only B's round

### Requirement: Lazy Additive Migration from tickets.json

The system MUST migrate a ticket's data out of the legacy shared
`tickets.json` into its per-ticket file the first time that ticket is read
or written after this change ships, without deleting or truncating
`tickets.json`.

#### Scenario: Pre-existing ticket migrates on first access

- GIVEN `tickets.json` contains `PROJ-50` with 3 rounds and no per-ticket file exists
- WHEN `PROJ-50` is loaded (e.g. via resume or `save_round`)
- THEN a per-ticket file for `PROJ-50` is created containing all 3 rounds, description, and branch
- AND `tickets.json` still contains the original `PROJ-50` entry unchanged

#### Scenario: Migrated ticket remains fully readable

- GIVEN `PROJ-50` has been migrated
- WHEN its history is requested again
- THEN all 3 original rounds are present, correctly ordered, and none is duplicated or lost

#### Scenario: Already-migrated ticket is not re-migrated

- GIVEN a per-ticket file for `PROJ-50` already exists
- WHEN `PROJ-50` is accessed again
- THEN the system reads only the per-ticket file and does not re-copy data from `tickets.json`

### Requirement: Merge-on-Write for Same-Ticket Mutations

Each mutator (round save, branch save, cache update) MUST re-read the
current per-ticket file immediately before writing and merge its delta into
that fresh read, shrinking the loss window for two terminals on the same
ticket to the write step itself.

#### Scenario: Sequential same-ticket writes both persist

- GIVEN terminal A starts preparing a round save for `PROJ-300`
- WHEN terminal B saves a branch update for `PROJ-300` and completes first
- THEN A's write re-reads the file (now containing B's branch) and merges its round in
- AND the final file contains both A's round and B's branch

#### Scenario: True concurrency remains a known, accepted limitation

- GIVEN two terminals write to `PROJ-300` at the exact same instant (sub-millisecond interleave)
- WHEN both writes race
- THEN the system does not guarantee both deltas survive (no lock is used)
- AND this is documented as an accepted limitation, not treated as a bug

### Requirement: Capped History Rendering

`format_history` MUST render at most the 5 most recent rounds and MUST
prepend an explicit marker stating how many earlier rounds were omitted,
whenever rounds were omitted.

#### Scenario: Ticket with 5 or fewer rounds shows all of them

- GIVEN a ticket has 4 rounds
- WHEN its history is formatted
- THEN all 4 rounds are shown and no omitted-rounds marker appears

#### Scenario: Ticket with more than 5 rounds is capped

- GIVEN a ticket has 8 rounds
- WHEN its history is formatted
- THEN only the 5 most recent rounds are shown
- AND a marker reading "(3 rondas anteriores omitidas)" appears before them
- AND the omitted rounds are NOT deleted from storage — they remain in the per-ticket file

### Requirement: Cache State Accessors

The per-ticket file MUST store and return a `last_comment_id` watermark and a
set of processed-attachment identifiers, readable and writable independently
of round data.

#### Scenario: Watermark persists across resumes

- GIVEN a ticket's `last_comment_id` was set to `10042` on a previous resume
- WHEN the ticket file is loaded again
- THEN `last_comment_id` returns `10042`

#### Scenario: Attachment id marked processed is retained

- GIVEN attachment `att-77` was marked processed for a ticket
- WHEN the ticket file is reloaded
- THEN `att-77` is still present in the processed set
