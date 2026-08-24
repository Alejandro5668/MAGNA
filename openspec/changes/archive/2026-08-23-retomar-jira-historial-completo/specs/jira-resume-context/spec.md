# jira-resume-context Specification

## Purpose

Wires `ctx retomar` (both the non-TUI and TUI call sites) to re-fetch live
Jira comments on every resume, compute only the delta since the last-seen
comment, reuse already-processed attachment results, and surface a
non-blocking warning if another process already has the same ticket open —
closing the gap where QA's reopening comment and attachment had to be pasted
by hand.

## Requirements

### Requirement: Fetch Comments from Jira

`jira.fetch_comments(ticket_id)` MUST retrieve all comments for a ticket via
the Jira REST API and convert each comment body from ADF to plain text using
the existing `_adf_to_text` conversion, without any AI-model call.

#### Scenario: Successful fetch returns ordered comments

- GIVEN a ticket has 3 comments in Jira
- WHEN `fetch_comments` is called for that ticket
- THEN it returns 3 comments with id, author, plain-text body, and timestamp, in chronological order

#### Scenario: Jira request fails

- GIVEN the Jira API is unreachable or returns a non-200 status
- WHEN `fetch_comments` is called
- THEN it returns an empty result without raising
- AND the resume flow continues without comments rather than crashing

### Requirement: Comment Delta Since Watermark

On resume, the system MUST compute only the comments newer than the
ticket's stored `last_comment_id` and MUST advance the watermark to the
newest fetched comment id after use.

#### Scenario: First resume with no watermark shows recent comments

- GIVEN a ticket has no stored `last_comment_id`
- WHEN it is resumed and comments are fetched
- THEN all fetched comments are treated as new
- AND the watermark is set to the newest comment's id afterward

#### Scenario: Later resume shows only unseen comments

- GIVEN `last_comment_id` is `500` and Jira now has comments `500, 501, 502`
- WHEN the ticket is resumed
- THEN only comments `501` and `502` are included as new
- AND the watermark advances to `502`

#### Scenario: Edited old comment is a known, accepted limitation

- GIVEN comment `500` (already below the watermark) is edited in Jira after the watermark advanced past it
- WHEN the ticket is resumed again
- THEN the edited content of comment `500` is NOT re-surfaced
- AND this is documented as an accepted limitation, not a bug

### Requirement: Attachment Processing Cache

Before reprocessing an attachment (image description, Excel-to-text, video
analysis) at any resume or task call site, the system MUST check whether
that attachment's id already has a cached result for the ticket and MUST
reuse the cached result instead of re-invoking the AI pipeline. The cache
never expires.

#### Scenario: New attachment is processed and cached

- GIVEN attachment `att-1` has never been processed for a ticket
- WHEN the resume flow processes attachments
- THEN `att-1` is analyzed and its result is stored keyed by its attachment id

#### Scenario: Already-cached attachment is not reprocessed

- GIVEN attachment `att-1` has a cached result from a previous resume
- WHEN the same ticket is resumed again and `att-1` still appears in Jira's attachment list
- THEN the AI pipeline is NOT invoked again for `att-1`
- AND the cached result is reused in the built context

#### Scenario: Cache never expires

- GIVEN attachment `att-1` was cached 90 days ago
- WHEN the ticket is resumed today
- THEN the cached result is still considered valid and reused (no TTL check)

### Requirement: Resume Call Sites Pass Ticket Context

Both `_run_resume` (non-TUI) and `_run_resume_tui` MUST pass `ticket_id` and
freshly fetched `jira_data` (issue + delta comments) into `_execute_task`, so
attachment and comment context reach the task pipeline on every resume.

#### Scenario: Non-TUI resume fetches and forwards jira_data

- GIVEN a user resumes `PROJ-9` from the non-TUI flow
- WHEN `_run_resume` calls `_execute_task`
- THEN `ticket_id="PROJ-9"` and a `jira_data` dict (issue + new comments) are both passed

#### Scenario: TUI resume fetches and forwards jira_data

- GIVEN a user resumes `PROJ-9` from the TUI flow
- WHEN `_run_resume_tui` calls `_execute_task`
- THEN `ticket_id="PROJ-9"` and a `jira_data` dict are both passed, matching the non-TUI behavior

### Requirement: Same-Ticket Concurrency Warning

If another process's active-ticket marker file references the same
`ticket_id` being resumed, the system MUST show a non-blocking warning and
MUST proceed with the resume regardless.

#### Scenario: Same ticket open in another terminal

- GIVEN another PID's active-ticket file shows `PROJ-9` as active
- WHEN a second terminal resumes `PROJ-9`
- THEN a warning is shown that the ticket may already be open elsewhere
- AND the resume flow continues without blocking

#### Scenario: Stale marker (>24h) is treated as gone, no false warning

- GIVEN another PID's active-ticket file has not been touched in more than 24 hours
- WHEN a terminal resumes the same ticket id
- THEN no warning is shown for that stale marker (treated as an abandoned/crashed session, not an active one)
- AND no lock or block prevents the resume in any case

#### Scenario: Fresh marker (<=24h) still warns but never blocks

- GIVEN another PID's active-ticket file was touched within the last 24 hours
- WHEN a terminal resumes the same ticket id
- THEN the warning is shown (informational only)
- AND no lock or block prevents the resume
