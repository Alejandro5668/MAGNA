# Exploration: qa-orchestrator-pipeline

## Background

A prior change, `qa-verification-protocol` (archived 2026-09-09, merged via PR #9, commit `24f4d79`),
was reverted by the user on 2026-09-10 (revert commit `392410a`, local only, not yet pushed). That
design injected a fixed `QA_PROTOCOL` text block into the SAME Claude session that wrote the bug fix
(`build_context(..., es_bug=True)`), and trusted that same session to self-report `qa_verified` to
`~/.mycontext/qa_results/<TICKET>.json` — mixed into the fixer's own session, not an independent check.

`aicli/services/qa_protocol.py`, `read_qa_result()`/`qa_verified` in `tickets.py`, and all prior QA
openspec artifacts are confirmed gone from the codebase. `knowledge/decisions.md` tops out at
`DEC-080` — `DEC-081` (the entry that documented the stdlib-only/Playwright-outside-repo decisions)
no longer exists and can't be cited by that name; the conventions themselves (stdlib-only,
keyword-defaulted new params, Playwright suite outside the client repo) still hold as house style but
must be re-derived, not referenced.

## Current State

- `aicli/commands/sync.py::_sync_impl(ask_fn=None, confirm_fn=None)` (lines 153-419) is the clean
  trigger call site: change-detection → doc update → decision capture → Jira summary → `save_round(...)`
  (~line 390) → `ModuleLesson` persistence → `clear_active_ticket()`. No leftover QA plumbing to clean
  up; the natural hook is right after `save_round`, inside the `if save:` branch. `_sync_impl` runs both
  from bare `ctx sync` (Typer CLI, short-lived process via `main.py`) and from the TUI via
  `_dispatch_tui("sync", ...)` (`aicli/tui/screens.py` L381-387).

- **No fire-and-forget background pattern exists yet.** Every real `ThreadPoolExecutor` usage in the
  repo (`aicli/tui/screens.py` L856-882, 1475-1738; `aicli/tui/output_screen.py` L132-147) bridges a
  blocking call onto a thread and immediately `.result()`s/`await`s it — none are detached. The one
  genuinely fire-and-forget pattern is Textual's `@work(thread=True, exclusive=True)`
  (`TicketPanel._fetch()`, `aicli/tui/widgets.py` L117-152), but that only survives while the TUI process
  is alive.

- **Process-lifetime gap for the bare-CLI path.** `ctx sync` from a plain terminal is a single
  short-lived Typer process. A daemon thread dies with the process; a non-daemon thread blocks exit and
  defeats "returns immediately". True background execution for that path needs a **detached OS
  subprocess** (e.g. Windows `DETACHED_PROCESS`/`CREATE_NEW_PROCESS_GROUP`) — zero precedent anywhere in
  this codebase today.

- **Headless `claude` CLI invocation is new territory.** `aicli/services/caller.py::launch_claude`
  (L124-247) is the only existing `claude` CLI call, and it's strictly interactive
  (`subprocess.run(["claude", message], ...)`, handed to a human via `self.app.suspend()`). Nothing here
  invokes `claude -p`/print-mode with captured, parsed output — the orchestrator's repro/verify/
  regression/corrector agents would be the first.

- **JSON-parsing-around-Claude-output risk is proven, not hypothetical.**
  `task.py::_detect_relevant_modules` needed `json.JSONDecoder().raw_decode(text)` specifically because
  Claude sometimes appends text after the JSON payload (fixed in commit `a775146`). The pipeline's
  `repro.json`/`verify.json`/`regression.json` outputs will hit the same failure mode and need the same
  defensive parsing.

- `security-review` (an available Claude Code skill) is **not listed in `.atl/skill-registry.md`**, and
  whether it resolves inside a headless, non-interactive `claude` subprocess (vs. only an interactive
  session) is unverified from repo inspection alone — a real open question for the design phase.

- No `.mcp.json` at the project root — CodeGraph is configured at user/global level. Whether a headless
  `claude` subprocess inherits that MCP config is an assumption, not yet confirmed.

- `LogScreen` (`aicli/tui/screens.py` L1069-1116) currently hardcodes reading `~/.mycontext/magna.log`.
  Showing QA evidence there needs a small parameterization (constructor path arg), not pure reuse as-is.

- `TicketPanel._row()` (`aicli/tui/widgets.py` L170-183) already composes the row `Text` (active marker,
  priority badge, ticket id, summary, `⟳×N` round count) — a QA-status suffix (`QA…` / `✔` / `✖ (N)`)
  slots in as one more conditional `txt.append(...)` at the end, same pattern as the existing round
  count.

## Recommendation

Standardize on a **single detached-subprocess launcher** used uniformly from both the CLI (`ctx sync`)
and TUI trigger paths, rather than threads-for-TUI + subprocess-for-CLI — it's the only option that
survives a bare-CLI user closing their terminal right after `ctx sync` returns, and it keeps the TUI
side simple: `TicketPanel`/`LogScreen` become passive readers of
`~/.mycontext/qa_results/<TICKET>/*.json`, not thread-handle owners.

## Style Conventions Confirmed (for new `aicli/services/qa_orchestrator.py`)

Pure functions, no classes, snake_case, type hints on all public functions, Spanish docstrings/
user-facing strings, English identifiers. Heavy/optional imports lazy inside the function that needs
them (`jira.py` pattern). Defensive JSON parsing (`raw_decode`, per commit `a775146`) required for any
JSON a `claude` subprocess is expected to emit.

## Open Questions For Design

1. Detached-subprocess semantics on Windows — unproven here, needs a small spike before design commits
   to it.
2. Whether `security-review` and CodeGraph MCP are reachable from a spawned non-interactive `claude`
   subprocess.
3. Cucumber/Gherkin layering on top of the Playwright suite — floated by the user, explicitly left
   undecided; not part of this exploration's scope.

## Ready for Proposal

Yes. The decoupled multi-agent/blackboard architecture (repro → verify → regression → verdict, with a
bounded 2-cycle corrector sub-pipeline) holds up against the real codebase. The one load-bearing gap the
proposal/design phases must account for is that "background, non-blocking" requires new
detached-subprocess infrastructure — it is not a reuse of an existing thread pattern.
