# Verification Report: qa-verification-protocol

**Mode**: Full artifacts (proposal + specs + design + tasks + apply-progress), hybrid persistence.
**Delivery**: single-pr, size:exception accepted by user for 435 vs 400-line budget (not re-litigated).

## Completeness

15/15 tasks marked [x] in both Engram sdd/qa-verification-protocol/tasks and
openspec/changes/qa-verification-protocol/tasks.md. All 5 phases verified against real files on disk
(not the apply reports self-assessment).

## Build/Test Evidence (executed directly, venv interpreter)

| Command | Exit | Result |
|---|---|---|
| ./.venv/Scripts/python.exe tests/test_commands.py | (script harness) | 31/35 passed. 4 failures are ImportError/AttributeError on StatusScreen, _MENU, _HELP_ROWS, _dispatch_tui from aicli/tui/app.py, confirmed via git diff --stat HEAD -- aicli/tui/app.py (empty diff, file untouched) and git log -1 -- aicli/tui/app.py (last touched by unrelated prior refactor commit af2322c, before this change existed). None of the 4 failing tests reference qa_protocol.py, builder.py, task.py, tickets.py, or sync.py. Confirmed pre-existing and out of scope. |
| ./.venv/Scripts/python.exe -m unittest tests/test_tickets.py -v | 0 | 19/19 passed (OK). Verified def test_ count on disk: 19 total; git show HEAD:tests/test_tickets.py grep -c def test_ = 11 pre-existing, so 8 are genuinely new -- matches design's "8 round-trip cases." |

Correction to apply-progress self-report: apply-progress claims "19/19 pre-existing... 27/27 total" for
test_tickets.py. This is factually wrong -- HEAD (pre-change) has 11 test methods, not 19; the real total after
adding 8 new tests is 19, not 27. The actual code and passing tests are correct; only the apply report's internal
arithmetic/baseline-count narrative is inaccurate. WARNING, not a functional defect -- flagged below.

## Hard Constraint Checks (scrutinized per explicit request)

| # | Constraint | Status | Evidence |
|---|---|---|---|
| 1 | No new entry in requirements.txt | MET | Full file read; contains only pre-existing packages (google-generativeai, anthropic, sqlmodel, textual, etc.) -- no new line added. |
| 2 | qa_protocol.py has zero non-stdlib imports | MET | aicli/services/qa_protocol.py:7-9 -- import re, import unicodedata, from pathlib import Path. Nothing else. |
| 3 | es_bug/is_bug_task/render_qa_protocol have no module-level mutable state | MET | Module-level names are QA_PROTOCOL (str), _REOPEN_MARKER (str), _BUG_KEYWORDS (tuple), _BUG_RE (compiled read-only re.Pattern) -- all immutable, never mutated after definition. is_bug_task/render_qa_protocol read module constants and their own args only; no writes to module scope. |
| 4 | qa_verified defaults to None (never False) in every failure path of read_qa_result | MET | tickets.py:43-59 -- missing file -> return None; JSON parse exception -> data = None -> final return data if isinstance(data, dict) else None -> None; non-dict JSON -> same guard -> None. No path returns False. save_round also defaults qa_verified: bool or None = None (tickets.py:167), sync.py:391 initializes qa_verified = None before conditionally overwriting only on isinstance(..., bool). |
| 5 | read_qa_result deletes the file after reading, both success and corrupt-JSON paths | MET | tickets.py:50-58 -- try/except/finally wraps only the parse; finally: path.unlink(missing_ok=True) runs unconditionally whether json.loads succeeded or raised. Confirmed by passing tests test_read_qa_result_returns_dict_and_deletes_file, test_read_qa_result_second_call_returns_none (proves deletion after success), test_read_qa_result_corrupt_file_returns_none_and_deletes (proves deletion after corrupt JSON). |
| 6 | qa_results/ is a sibling of tickets/, not inside it | MET | tickets.py:38-40 -- _qa_results_dir() returns _base_dir() / "qa_results"; _tickets_dir() (line 26) returns _base_dir() / "tickets". Siblings under the same base, no nesting -- load_tickets()'s _tickets_dir().glob("*.json") (line 150) cannot see qa_results/*.json. Test at test_tickets.py:226 (qa_dir = self.base / "qa_results") confirms the sibling path directly against the test's own MYCONTEXT_HOME root. |

## Hard Constraint: no screens.py/claude_cmd.py modification

MET. git status --porcelain shows only 7 modified tracked files
(sync.py, task.py, builder.py, tickets.py, decisions.md, test_commands.py, test_tickets.py) plus one
new untracked file (qa_protocol.py). aicli/tui/screens.py and aicli/commands/claude_cmd.py are absent from
that list -- zero diff. Read screens.py:392-418 directly: the free-question "elif command == claude:" branch
still calls _build_ctx(modules, project_path=path) with no es_bug argument (line 414), and
claude_cmd.py:46 still calls build_context(modules, project_path=path) with no es_bug argument -- both
default to es_bug=False, byte-identical call shape to pre-change, satisfying the proposal's "Confirmed unchanged"
rows and the Success Criterion "ctx claude and the TUI free-question path produce byte-identical context to
today."

## Spec Compliance Matrix (by domain)

### Domain: qa-verification-protocol (protocol text)
| Requirement | Status | Evidence |
|---|---|---|
| Test Plan Before Verification | MET | QA_PROTOCOL section 1 (qa_protocol.py:16-22) requires numbered plan before executing. |
| Independent Reproduction | MET | QA_PROTOCOL section 2 (qa_protocol.py:24-27). |
| Real Browser Verification With Deep Inspection | MET | QA_PROTOCOL sections 3-4 (qa_protocol.py:29-38) -- console/network + DB state. |
| Production Read-Only By Default | MET | QA_PROTOCOL section 5 (qa_protocol.py:40-43). |
| Pause on Missing Data | MET | QA_PROTOCOL section 6 (qa_protocol.py:45-48). |
| Bounded Retry With Escalation | MET | QA_PROTOCOL section 7 (qa_protocol.py:50-56) -- caps at 3 cycles, escalation instruction present. |
| No Resolution Without Verification | MET | QA_PROTOCOL section 7 last line + section 9 (qa_protocol.py:56, 72-89). |

This domain is protocol text injected into a Claude session -- AICLI cannot runtime-test the text's effect on
a live session per design's own Testing Strategy table, which scopes E2E/browser verification as out-of-scope
for AICLI's test suite. Compliance here means: exact text present, rendered, and reaches session_context.md
first -- which IS runtime-tested below under bug-task-classification.

### Domain: qa-regression-suite
Design correctly scopes this as text-only (QA_PROTOCOL section 8, qa_protocol.py:58-70) -- no AICLI code installs
or runs Playwright. Requirements are process/text requirements on the Claude session, consistent with proposal's
Out of Scope: "Any AICLI code that installs, runs, or parses Playwright." MET by inspection of protocol text;
correctly untestable by AICLI's own suite per design.

### Domain: bug-task-classification
| Requirement | Status | Evidence |
|---|---|---|
| Pure Bug-Task Heuristic (no module mutable state, no AI call, no issuetype read) | MET | is_bug_task reads only desc/jira_data args + immutable module constants; no issuetype reference anywhere in qa_protocol.py; no network import. Runtime-tested: 8/8 passing in test_commands.py (test_is_bug_task_*). |
| Reopen Marker Is a Positive Signal | MET | _REOPEN_MARKER = "ticket reabierto" checked before keyword regex (qa_protocol.py:148-150). Test test_is_bug_task_reopen_marker PASSED. |
| Recall-Biased Keyword Set | MET | 40+ keyword/phrase set in _BUG_KEYWORDS, broad by design. |
| Conditional QA Protocol Injection in build_context | MET | builder.py:25-27 prepends render_qa_protocol(...) as fragments[0] only when es_bug=True. Tests PASSED: test_build_context_es_bug_false_no_protocol, test_build_context_es_bug_true_includes_protocol, test_build_context_es_bug_true_protocol_first. |
| Single Classification Call Site | MET | Only task.py:288-289 computes es_bug; screens.py/claude_cmd.py unchanged (see above). |
| Minimal Real-Argument Test Coverage | MET | 8 is_bug_task + 5 build_context real-argument tests, all green, none stubs (inspected assertions directly). |

### Domain: qa-outcome-tracking
| Requirement | Status | Evidence |
|---|---|---|
| Session-Produced Verification Artifact | MET (by design contract) | QA_PROTOCOL section 9 specifies exact file/JSON shape written by the session; AICLI-side consumption verified below. |
| ctx sync Passes Through Verification Ground Truth | MET | sync.py:390-393 calls read_qa_result, derives qa_verified via isinstance(..., bool), passes into save_round. |
| save_round Stores Ground-Truth QA Outcome | MET | tickets.py:160-176, qa_verified appended last in ronda dict. Tests PASSED: test_save_round_qa_verified_true_persisted, _default_none, _false_and_history_renders. |
| Missing or Unreadable Result Defaults to Unknown, Never False | MET | See Hard Constraint #4 above. |
| qa_verified Is Never AI-Inferred | MET | generate_case_summary (indexer.py) not modified by this change (absent from git status); no wiring of qa_verified into that function anywhere in the diff. |

## Design Coherence

All 7 Architecture Decisions in design.md verified against actual code, byte-for-byte where design specified
exact bodies (QA_PROTOCOL text, is_bug_task, render_qa_protocol, diff sketches for builder.py/task.py/
tickets.py/sync.py) -- no deviation found. Matches apply-progress's own "Deviations from Design: None" claim,
independently confirmed by direct comparison of design.md's literal code blocks against the files on disk.

One additive, disclosed deviation (not a design decision, a test-file detail): test_commands.py replaced
assert callable(build_context) with assert build_context is not None rather than deleting it outright, to
preserve a broader import-smoke check. Low-risk, does not affect coverage claims (real behavioral coverage lives
in the new dedicated tests) -- SUGGESTION only, not a defect.

## Success Criteria (proposal.md, bottom section)

| # | Criterion | Status | Evidence |
|---|---|---|---|
| 1 | Bug session receives QA_PROTOCOL as first fragment, ahead of team rules | MET | test_build_context_es_bug_true_protocol_first PASSED; builder.py:25-27 precedes team-rules block (line 30+). |
| 2 | Reopened ticket (CLI + TUI resume) classified as bug, receives protocol | MET | is_bug_task reopen-marker branch is unconditional on the rest of text (qa_protocol.py:148-150); both resume paths funnel through _execute_task (verified task.py:108-116 params, single call site at task.py:288) per proposal's own call-graph argument, which this verification independently re-traced and confirmed structurally (not merely trusted). |
| 3 | ctx claude/TUI free-question path byte-identical to today | MET | Confirmed no diff on screens.py/claude_cmd.py; both call sites unchanged argument shape. |
| 4 | is_bug_task True for reopen marker text and Jira-summary-only bug keyword | MET | test_is_bug_task_reopen_marker, test_is_bug_task_jira_summary_only both PASSED. |
| 5 | No Playwright artifact/package.json/node_modules ever created inside client repo | MET (by inspection) | No AICLI code path writes into the client repo tree; all new filesystem writes (qa_protocol.py, tickets.py) target ~/.mycontext/** only; enforcement of the client-repo prohibition is textual (protocol section 8) per explicit proposal scoping -- cannot be runtime-verified by AICLI's own test suite (no live Claude session), and design correctly does not claim it can. |
| 6 | No new entry in requirements.txt | MET | See Hard Constraint #1. |
| 7 | build_context has real-argument test coverage for both es_bug values | MET | 5 tests covering True/False/default/ordering/warnings-type, all PASSED. |
| 8 | Bug session's verification produces a written test plan the user can read | MET (by protocol text contract) | QA_PROTOCOL section 1 mandates it; not independently runtime-verifiable by AICLI tests (same scope boundary as #5). |
| 9 | Ticket round records qa_verified truthfully, never guessed from diff | MET | See qa-outcome-tracking matrix above; generate_case_summary confirmed untouched. |

## Issues

CRITICAL: None found.

WARNING:
1. Apply-progress's TDD Cycle Evidence table for test_tickets.py misreports baseline/total counts
   ("19/19 pre-existing... 27/27 total" -- actual: 11 pre-existing, 19 total after adding 8 new tests, confirmed
   via git show HEAD:tests/test_tickets.py and the actual test run). Purely a reporting/arithmetic error in the
   apply-progress artifact; does not affect code correctness, does not require code changes. Recommend correcting
   the apply-progress record for future audit trail accuracy, but this does not block archive.

SUGGESTION:
1. test_commands.py's replacement of assert callable(build_context) with assert build_context is not None
   is slightly weaker than the original (any non-None object passes, not just callables) -- functionally
   harmless since build_context is always the real function object at that point, but a callable(...) check
   would have been marginally more precise for an import-smoke assertion.

## Verdict

PASS

15/15 tasks complete and independently verified against real code, not the apply report's self-assessment. All 6
scrutinized hard constraints MET with direct evidence. Both test commands executed with real, current output:
test_commands.py 31/35 (4 failures confirmed pre-existing/unrelated via git history -- zero diff on the failing
tests' target module aicli/tui/app.py), test_tickets.py 19/19 (including all 8 new round-trip cases). No
CRITICAL issues. One WARNING (apply-progress self-reported test-count arithmetic error -- cosmetic, not
functional) and one SUGGESTION (test assertion precision) do not block delivery. screens.py/claude_cmd.py
hard constraint confirmed untouched by direct git diff and source inspection, not by trusting prior reports.
