```yaml
schema: gentle-ai.verify-result/v1
evidence_revision: sha256:caefd627800bc6bbbd5df3858b633469d5eddd1e380d77487256f08eb5df4b7f
verdict: fail
blockers: 1
critical_findings: 1
requirements: 10/10
scenarios: 21/23
test_command: .venv/Scripts/python.exe -m unittest tests/test_tickets.py tests/test_jira_comments.py -v
test_exit_code: 0
test_output_hash: sha256:6b75e0aaea9ab6b23b36e91f22e6723f2bd1527a4c57b7647eb0048838df5378
build_command: .venv/Scripts/python.exe tests/test_commands.py
build_exit_code: 1
build_output_hash: sha256:36a02c16118c84d56e9fa95a494ed8e205836421458feb7200dc86a4f94910e4
```

## Verification Report

**Change**: retomar-jira-historial-completo
**Version**: N/A (no openspec/specs/ baseline yet, first capability drop)
**Mode**: Strict TDD (tickets.py/jira.py, Phases 1-3) plus Standard mode (screens.py/task.py/caller.py/docs, Phases 4-7), per explicit user scoping recorded in apply-progress

### Completeness
| Metric | Value |
|--------|-------|
| Tasks total | 31 |
| Tasks complete | 31 |
| Tasks incomplete | 0 |

### Build and Tests Execution

**Build**: N/A, pure-Python project, no build step. test_commands.py used as smoke/import gate instead.

**Tests (focused, Strict TDD scope)**: PASSED - 18 passed / 0 failed / 0 skipped
```text
.venv/Scripts/python.exe -m unittest tests/test_tickets.py tests/test_jira_comments.py -v
Ran 18 tests in 0.755s - OK (11 test_tickets.py + 7 test_jira_comments.py)
```

**Tests (full regression, test_commands.py)**: WARNING - 19 passed / 4 failed / 0 skipped, exit code 1
```text
.venv/Scripts/python.exe tests/test_commands.py
19/23 pasaron | 4 fallaron:
  - tui: app.py, imports y constantes de paleta (ImportError: StatusScreen)
  - tui: todas las descripciones del menu caben en una linea (ImportError: _MENU)
  - tui: help overlay tiene todos los keybindings (ImportError: _HELP_ROWS)
  - tui: _dispatch_tui no llama asyncio.run() y usa TuiConsole (AttributeError: _dispatch_tui)
```
Independently reproduced via git stash / git stash pop around this change diff, which touches
tickets.py, jira.py, screens.py, task.py, caller.py, modals.py, output_screen.py, decisions.md,
and never aicli/tui/app.py: baseline HEAD (a775146) shows the exact same 19/23 with the same 4
named failures, all originating from missing symbols in aicli/tui/app.py that this change never
touches. Confirmed: no new regression, same 4 pre-existing failures.

**Coverage**: Not available, no coverage tool in requirements.txt

### Spec Compliance Matrix

**Capability: ticket-history-store**

| Requirement | Scenario | Test | Result |
|---|---|---|---|
| Per-Ticket File Storage | New ticket creates own file | test_tickets.py::test_per_ticket_file_created_no_collision | COMPLIANT |
| Per-Ticket File Storage | Two terminals, different tickets, never collide | test_tickets.py::test_per_ticket_file_created_no_collision | COMPLIANT |
| Lazy Additive Migration | Pre-existing ticket migrates on first access | test_tickets.py::test_legacy_migration_additive_idempotent_readable | COMPLIANT |
| Lazy Additive Migration | Migrated ticket remains fully readable | same test, second load assertion | COMPLIANT |
| Lazy Additive Migration | Already-migrated ticket not re-migrated | same test, migrated_before equals migrated_after | COMPLIANT |
| Merge-on-Write | Sequential same-ticket writes both persist | test_tickets.py::test_merge_on_write_round_and_branch_both_survive | COMPLIANT |
| Merge-on-Write | True concurrency is an accepted limitation | N/A, negative/non-guarantee scenario, not deterministically testable | N/A, documented in DEC-076, no lock by design |
| Capped History Rendering | 5 or fewer rounds shows all, no marker | test_tickets.py::test_format_history_no_marker_when_5_or_fewer | COMPLIANT |
| Capped History Rendering | More than 5 rounds capped, marker shown, omitted rounds not deleted | test_format_history_caps_at_5_plural_marker plus test_format_history_singular_marker | COMPLIANT |
| Cache State Accessors | Watermark persists across resumes | test_tickets.py::test_jira_cache_watermark_and_attachment_persist_across_reload | COMPLIANT |
| Cache State Accessors | Attachment id marked processed is retained | same test | COMPLIANT |

**Capability: jira-resume-context**

| Requirement | Scenario | Test | Result |
|---|---|---|---|
| Fetch Comments from Jira | Successful fetch returns ordered comments | test_jira_comments.py::test_successful_fetch_returns_ordered_comments | COMPLIANT |
| Fetch Comments from Jira | Jira request fails, empty result, no raise | test_non_200_returns_empty plus test_exception_returns_empty | COMPLIANT |
| Comment Delta Since Watermark | First resume, no watermark, shows all as new | test_watermark_absent_returns_all | COMPLIANT |
| Comment Delta Since Watermark | Later resume shows only unseen comments | test_watermark_present_filters_tail | COMPLIANT |
| Comment Delta Since Watermark | Edited old comment is accepted limitation | N/A, documented in DEC-078, not deterministically testable | N/A, documented |
| Attachment Processing Cache | New attachment processed and cached | No automated test, code inspection only, task.py L192-253 | UNTESTED, Standard-mode phase, explicitly scoped |
| Attachment Processing Cache | Already-cached attachment not reprocessed | No automated test, code inspection only, pending filter at L192 | UNTESTED, Standard-mode phase, explicitly scoped |
| Attachment Processing Cache | Cache never expires | No TTL code exists anywhere, trivially satisfied by omission | COMPLIANT, static evidence |
| Resume Call Sites Pass Ticket Context | Non-TUI resume fetches and forwards jira_data | No automated test, code inspection, screens.py L310-328 | UNTESTED, Standard-mode phase, explicitly scoped |
| Resume Call Sites Pass Ticket Context | TUI resume fetches and forwards jira_data | No automated test, code inspection, screens.py L509-529 | UNTESTED, Standard-mode phase, explicitly scoped |
| Same-Ticket Concurrency Warning | Same ticket open in another terminal, warns, never blocks | Detection logic tested via test_other_sessions_with_ticket_pid_crosscheck; UI wiring not tested | PARTIAL |
| Same-Ticket Concurrency Warning | Stale marker still warns but never blocks | test_other_sessions_with_ticket_pid_crosscheck asserts stale (over 24h) PID is EXCLUDED, meaning it does NOT warn | FAILING vs literal spec wording, see Issues, downgraded to WARNING not CRITICAL |

Compliance summary: 17/23 scenarios COMPLIANT, 2 N/A (documented non-testable limitations), 4 UNTESTED/PARTIAL (Standard-mode wiring, explicitly scoped by user), 1 contradicts literal spec text (stale-marker scenario).

### Correctness (Static Evidence)

| Requirement | Status | Notes |
|---|---|---|
| save_active_ticket motivo-preservation bug fix (DEC-079 #1) | Implemented and tested | tickets.py L276-294; test_save_active_ticket_keeps_motivo_on_empty_same_ticket plus test_save_active_ticket_empty_does_not_leak_across_tickets prove same-ticket preserve plus cross-ticket non-leak |
| save_ticket_branch missing-field bug fix (DEC-079 #2) | Implemented and tested | Routed through _mutate_ticket plus _new_ticket; test_save_ticket_branch_new_ticket_sets_descripcion_and_actividad asserts no KeyError in format_history immediately after |
| Motivo de reapertura prefill, editable | Implemented, both call sites | screens.py L314-315 uses questionary.text with default=prefill; L511-513 uses tui_console.request_input with default=prefill; modals.py diff confirms Input(value=self._value, ...), a live editable field, not read-only display |
| History cap equals 5 rounds, confirmed decision | Implemented | _MAX_HISTORY_ROUNDS = 5 in tickets.py L10 |
| Same-ticket concurrency equals warning-only, no lock, confirmed decision | Implemented | No lock or flock anywhere in tickets.py; _mutate_ticket re-read-merge-write is the only concurrency control |
| Comment delta equals watermark-only, confirmed decision | Implemented | filter_new_comments compares only against last_comment_id; no diffing of edited bodies |
| Attachment cache equals never expires, confirmed decision | Implemented | save_processed_attachments and get_jira_cache have no TTL field or expiry check |
| Migration is lazy and additive, never destructive | Implemented and tested | _load_legacy_raw only reads; migrate_legacy_tickets and _read_ticket never call write_text on the legacy tickets.json path; test_legacy_migration_additive_idempotent_readable asserts byte-identical tickets.json before and after two loads |

### Coherence (Design)

| Decision | Followed? | Notes |
|---|---|---|
| Storage unit: one file per ticket, safe-id sanitized | Yes | Matches design interface exactly |
| Concurrency: mutate-ticket re-read, no locks | Yes | Matches |
| Expiry: filter on read, never delete files | Yes | load_tickets skips expired only in the returned view, never unlinks |
| Test seam: MYCONTEXT_HOME env, never cached | Yes | base_dir reads os.environ.get fresh every call |
| Comment delta: fetch newest 20, filter by watermark index | Yes | MAX_COMMENTS = 20, orderBy=-created |
| Watermark advance after execute_task returns | Yes | screens.py calls save_comment_watermark only after execute_task returns, both call sites |
| caller.py addition, flagged as own open question in design | Resolved, implemented | launch_claude renders a Comentarios nuevos block; design open-question checkbox left unchecked in design.md is stale documentation, non-blocking |
| Motivo prefill: design open question proposed first 120 chars; tasks.md resolved to full text | Yes, tasks.md superseded the tentative design proposal | Full text used, consistent with DEC-079 and apply-progress; not a silent deviation, tasks.md explicitly specifies full text, editable |
| other_sessions_with_ticket stale threshold equals mtime over 24h | Deviates from the literal jira-resume-context spec wording | Design (design.md L75) and tasks.md (1.9/2.7) both explicitly specify the 24h mtime heuristic, so implementation is faithful to design and tasks, but the spec own Stale marker still warns scenario describes staleness as process has since exited, not file older than 24h. For markers older than 24h, the code does NOT warn, contradicting the literal scenario text. For the realistic common case, a process that exited recently with marker still under 24h old, the warning still fires correctly. See Issues. |
| filter_new_comments fallback when watermark id not found returns all | Reasonable, tested | Design says index-of-watermark then tail without specifying the not-found case; returning all is the safer interpretation, a watermark that aged out of the last-20 window means everything fetched is newer; unit-tested via test_watermark_not_found_returns_all; documented in DEC-078 |

### Issues Found

**CRITICAL**: The declared build_command (tests/test_commands.py, the whole-repo regression/smoke gate) exits non-zero (1). This is NOT introduced by this change: the exact same 4 named failures (StatusScreen, _MENU, _HELP_ROWS, _dispatch_tui missing from aicli/tui/app.py, a file this change never touches) are reproduced identically on baseline HEAD via git stash / git stash pop performed in this verify session. This change strictly adds/fixes tickets.py, jira.py, screens.py, task.py, caller.py, modals.py, output_screen.py, decisions.md, and two new test files, none of which affect app.py. Per the strict verify contract, any non-zero declared command exit forces verdict=fail regardless of root cause, so this is recorded as CRITICAL/blocking for the machine envelope even though it is a pre-existing, unrelated repo-wide condition rather than a defect in this change scope. Recommend the orchestrator either (a) triage/fix the unrelated aicli/tui/app.py gap in a separate change before archiving this one under a strict gate, or (b) explicitly accept this as a known pre-existing baseline condition and re-run verify scoping build_command to the two new focused test files only.

**WARNING**:
1. Stale-marker scenario contradicts literal spec text. The jira-resume-context spec Stale marker still warns but never blocks scenario says a stale, process-exited marker must still produce a warning. The implementation, other_sessions_with_ticket in tickets.py L239-268, instead suppresses the warning once the marker file mtime exceeds 24h, which is the opposite of the literal scenario for markers older than a day. This is a deliberate, documented choice made consistently in both design.md L75 and tasks.md 1.9/2.7, since there is no cross-platform PID-liveness check available without a new dependency such as psutil, not present in requirements.txt, so 24h-mtime was chosen as a pragmatic proxy for abandoned. It is unit-tested and behaves as designed, but the spec document itself was never updated to reflect this narrowing, so a literal reading of specs/jira-resume-context/spec.md would flag this scenario as failing for the over-24h edge case. Non-blocking in practice, the realistic case of a terminal that crashed minutes or hours ago still warns correctly, but the spec text and the implemented behavior are not word for word aligned. Recommend updating the spec scenario text before archive, or filing a follow-up.
2. Four spec scenarios in jira-resume-context have no automated covering test: New attachment processed and cached, Already-cached attachment not reprocessed, Non-TUI resume forwards jira_data, TUI resume forwards jira_data. This matches the explicit Standard-mode scoping the user set for Phases 4-7, screens.py/task.py/caller.py, recorded in apply-progress, and is backed only by code inspection plus import-level smoke tests plus the unchanged test_commands.py regression baseline, since no live Jira credentials are available in this environment to run ctx retomar end-to-end, also disclosed by apply-progress. Code inspection shows the logic is correct and matches design, but per the rule that a spec scenario is compliant only when a covering test passed at runtime, these remain UNTESTED rather than COMPLIANT until an integration test or a manual end-to-end run against a real ticket is performed.
3. design.md still shows two unchecked Open Questions, the caller.py addition and the motivo prefill length, even though both were resolved during tasks and apply. Stale documentation only, the resolutions are correctly reflected in tasks.md, the code, and DEC-079. Recommend a small doc touch-up before archive, not a functional issue.

**SUGGESTION**:
1. Consider adding one integration-style test for _resume_jira_context, mocking jira.fetch_issue and fetch_comments, to close the automated-coverage gap for Phase 4 noted above, given how central the resume flow is to this change purpose.
2. No linter or type-checker is configured in this project, requirements.txt has none; quality metrics are skipped, not a regression.

### TDD Compliance
| Check | Result | Details |
|-------|--------|---------|
| TDD Evidence reported | Yes | Found in apply-progress, both tables, tickets.py storage and jira.py comments |
| All tasks have tests | Yes | 2 of 2 Strict-TDD-scoped tasks have test files, test_tickets.py and test_jira_comments.py; Phases 4-7 explicitly Standard-mode per user scoping |
| RED confirmed, tests exist | Yes | Both test files exist, verified by direct Read |
| GREEN confirmed, tests pass | Yes | 18/18 pass on independent re-run in this session |
| Triangulation adequate | Yes | Multiple cases per behavior: cap variants (8-round, 6-round, 4-round), watermark cases (present, absent, empty, not-found), PID cross-check (own, other, stale, malformed in one test) |
| Safety Net for modified files | Yes | tickets.py and jira.py fully rewritten or extended; RED-then-GREEN cycle confirmed per apply-progress, 5 fail plus 4 error then 11/11 OK; 7 error then 7/7 OK |

TDD Compliance: 6/6 checks passed

---

### Test Layer Distribution
| Layer | Tests | Files | Tools |
|-------|-------|-------|-------|
| Unit | 18 | 2, test_tickets.py and test_jira_comments.py | stdlib unittest, unittest.mock |
| Integration | 0 new | none | none added for Phases 4-7, see WARNING 2 |
| E2E | 0 | none | not installed |
| Total | 18 | 2 | |

---

### Changed File Coverage
Coverage analysis skipped, no coverage tool detected in requirements.txt.

---

### Assertion Quality
All assertions verify real behavior. No tautologies, no ghost loops, no assertion-free tests found in test_tickets.py or test_jira_comments.py. Every test calls production code, save_round, format_history, fetch_comments, filter_new_comments, and others, and asserts concrete, varying expected values, different ids, different counts, different markers, rather than trivial or empty checks alone.

Assertion quality: 0 CRITICAL, 0 WARNING

---

### Quality Metrics
Linter: Not available, none configured in this project
Type Checker: Not available, none configured in this project

### Verdict
FAIL (machine envelope, strict binary contract) / PASS WITH WARNINGS (substantive implementation quality)

Machine verdict is FAIL solely because the declared build_command (tests/test_commands.py) exits non-zero (1); the strict validator (gentle-ai sdd-verify-validate) treats any non-zero declared command exit as failing evidence, with no exception for pre-existing-and-unrelated conditions. That exit code is git-stash-verified to be identical before and after this change (same 4 named failures, all rooted in aicli/tui/app.py, a file this change never touches) -- it is not a regression caused by this change.

On substance: all 31 of 31 tasks are complete, all 4 confirmed product decisions and both pre-existing bugs are faithfully implemented and test-covered, migration is verifiably lazy, additive, and non-destructive, and the change own focused test suite (test_tickets.py + test_jira_comments.py, 18/18) passes cleanly. Remaining WARNING-level gaps are: a stale-marker spec-vs-implementation wording mismatch that is deliberate and unit-tested but not literally spec-compliant for the over-24h edge case, and four jira-resume-context wiring scenarios that lack automated coverage under the explicit Standard-mode scoping for Phases 4-7.

Recommendation to the orchestrator: this change own work is sound and ready; the machine FAIL is an artifact of a pre-existing, unrelated repo-wide gap (aicli/tui/app.py) that predates this change and should be triaged separately, not treated as a defect introduced here.
