# Design: QA Orchestrator Pipeline

## Technical Approach

`ctx sync` fires one non-blocking `trigger_qa(...)` that **re-launches the same MAGNA binary** as a
detached OS process running a hidden `qa-run` Typer command. That runner owns the whole pipeline and
communicates only through a per-ticket file blackboard at `~/.mycontext/qa_results/<TICKET>/`. Three
stages are headless `claude -p` subprocesses (repro, verify, corrector), regression is plain
`npx playwright test` (zero tokens), and the aggregator is pure Python and the sole writer of
`verdict.json`. The TUI never owns a thread or a handle: it is a passive poller of `status.json`.

## Architecture Decisions

### Decision: Runner entry point is a hidden `ctx qa-run` subcommand, re-entered via `sys.executable`

**Choice**: `aicli/commands/qa_cmd.py` registers `qa-run <TICKET> --project-path <p> --run-id <id>`
(`hidden=True`) in `main.py`. The launcher builds argv as `[sys.executable, "qa-run", ...]` when
`getattr(sys, "frozen", False)`, else `[sys.executable, str(_main_py()), "qa-run", ...]` where
`_main_py() = Path(aicli.__file__).resolve().parents[1] / "main.py"`.
**Alternatives considered**: `python -m aicli.services.qa_runner`; a standalone script.
**Rationale**: `ctx.spec` packs `main.py` into a one-file PyInstaller EXE — `-m` does not exist for the
frozen binary and `sys.executable` is `MAGNA.exe`, not Python. Re-entry through the same entry point is
the only form that works identically frozen and from source, and it inherits `main.py`'s logging,
`.env` loading and `init_db()` for free.

### Decision: One detached `Popen` for both call sites, output redirected to a file

**Choice**:

```python
flags = 0
if platform.system() == "Windows":
    flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
kwargs = {"creationflags": flags} if flags else {"start_new_session": True}
with open(run_dir / "run.log", "a", encoding="utf-8") as log:
    proc = subprocess.Popen(argv, cwd=str(project_path), stdin=subprocess.DEVNULL,
                            stdout=log, stderr=subprocess.STDOUT, close_fds=True, **kwargs)
```

**Alternatives considered**: `threading.Thread` (daemon/non-daemon); a Textual `@work(thread=True)`
worker for the TUI path plus `Popen` only for the CLI path.
**Rationale**: on the bare-CLI path the process exits immediately — a non-daemon thread blocks exit, a
daemon thread is killed. Inheriting the parent's stdout/stderr handles is the classic Windows failure
(the child dies or blocks when the console closes), so both are redirected to `run.log`. One mechanism
means one behaviour to test and no CLI/TUI divergence.
**Failure is never silent**: the whole launch is wrapped; on any `OSError`/`FileNotFoundError` the
launcher writes `status.json` with `state: "error", reason: "launch_failed"` **before** returning and
reports through `magna_error` (CLI) / the poller's notify (TUI).

### Decision: Headless agents get a short argv message pointing at a prompt file

**Choice**: for each agent stage write `prompts/<stage>.md` (full payload: ticket history, diff,
touched files, role contract, exact output schema), then run
`subprocess.run([claude, "-p", f"Read {prompt_path} and follow it exactly. Output ONLY the JSON object."],
capture_output=True, text=True, cwd=project_path, timeout=STAGE_TIMEOUT)`. `claude` resolves through
`caller._find_claude_windows()` with `"claude"` as fallback — reuse, do not duplicate that lookup.
**Alternatives considered**: passing the payload as the argv string; stdin piping; a templating library.
**Rationale**: mirrors the established `launch_claude` convention (prompt file in `~/.mycontext/`, short
message telling Claude to read it) and avoids Windows command-line length limits. Prompt files are
f-strings — no new dependency, per the project's stdlib-only convention.
**Flags beyond `-p` are UNVERIFIED** and must come from spike S2 before any agent code is written.

### Decision: All agent JSON goes through a local `raw_decode` parser; unparseable = stage error

**Choice**: `qa_orchestrator._parse_agent_json(text)` strips ``` fences then
`json.JSONDecoder().raw_decode(text)`; on failure the stage file is written with `"status": "error"` and
the raw stdout is saved to `raw/<stage>.txt`.
**Alternatives considered**: importing the helper from `task.py`; strict `json.loads`; a retry loop.
**Rationale**: commit `a775146` proves trailing text after the JSON is a real, already-encountered
failure in this repo. `task.py` imports `anthropic` at module scope — importing from it would drag the
SDK into the runner, so the three-line helper is re-stated locally rather than refactoring working code.
One retry is allowed per agent stage (same prompt); a second failure is a stage **error**, and the
aggregator can never turn an error into `qa_verified: true`.

### Decision: Corrector assumes NO skill and NO MCP; both are opportunistic

**Choice**: the corrector prompt always inlines a `SECURITY_CHECKLIST` constant and always ships
diff-scoped context (`git diff` for the touched files + `archivos_tocados`). It additionally says "if the
`security-review` skill or CodeGraph tools are available, use them". No code branches on availability.
**Alternatives considered**: detecting the skill/MCP at runtime and branching.
**Rationale**: `security-review` is confirmed absent from `.atl/skill-registry.md` and there is no
`.mcp.json`; whether either resolves inside a non-interactive subprocess is unverified. Designing the
fallback as the default path makes the implementation independent of the spike's outcome.

### Decision: Supersede is cooperative, via `run_id`; notifications are polled, not pushed

**Choice**: `trigger_qa` writes a new `run_id` (uuid4 hex) and deletes the previous stage artifacts. The
runner re-reads `status.json` at every stage boundary and exits immediately if `run_id` no longer matches.
`heartbeat` is refreshed at each boundary; a non-terminal state with `now - heartbeat > 600s` reads as
`stale`. The runner appends `events[]` with a monotonic `seq`; `TicketPanel.set_interval(5.0, self._poll_qa)`
notifies via `self.app.notify()` for each unseen `seq`.
**Alternatives considered**: killing the old PID; the runner calling `notify()` directly.
**Rationale**: a detached process has no handle on the Textual app, so `notify()` can only originate in
the TUI process. Cross-platform process killing mid-`git commit` is unsafe; cooperative exit at a stage
boundary cannot corrupt the blackboard. `pid` is recorded for diagnosis only.

### Decision: Git writes go through a deny-listed helper; author identity is untouched

**Choice**: every git call in the orchestrator goes through `_git(args, cwd)`, which raises if
`args[0] in {"push","fetch","pull","remote","reset","checkout","clean","rebase","merge","cherry-pick"}`.
Per correction attempt: verify `git rev-parse --abbrev-ref HEAD` equals `get_ticket_branch(ticket_id)`
(mismatch or detached HEAD ⇒ abort to `manual_review`, never switch branches), then
`git add -- <f1> <f2>` (explicit pathspec only, never `-A`/`-a`) and
`git commit --no-verify -m "fix(qa-auto): corrección automática <n>/2 — <motivo>"`.
**Alternatives considered**: `--author="MAGNA QA <qa@magna.local>"`; `commit -a`; running hooks.
**Rationale**: the deny list is the testable guarantee that `origin` is never touched. A synthetic author
pollutes a client repo's history and breaks author-checking CI; the `fix(qa-auto):` prefix is provenance
enough. `--no-verify` prevents an interactive or long hook from hanging an unattended process. Empty diff
after the corrector ⇒ no commit, attempt still counted.

## Data Flow

```
ctx sync (CLI or TUI)                       detached: MAGNA qa-run <TICKET>
  save_round ─► trigger_qa() ──Popen──►  [1] repro    claude -p ─► repro.json
      │  (returns immediately)            [2] verify   claude -p ─► verify.json
      ▼                                   [3] regress  npx playwright ─► regression.json
  process may exit                        [4] aggregate (pure Python) ─► verdict.json
                                                │ fail & attempt<2
                                                └─► corrector (claude -p) ─► git add/commit ─┐
                                                       ▲──────────────────────────────────────┘
  TUI ──set_interval(5s)──► status.json ──► badge in _row() + app.notify() on new seq
```

Blackboard: `~/.mycontext/qa_results/<TICKET>/` (reuse `tickets._safe_id()` for the directory name and
`tickets._write_ticket`'s tmp-then-`replace()` atomic pattern for every write) containing
`status.json`, `repro.json`, `verify.json`, `regression.json`, `verdict.json`, `evidence.log`,
`run.log`, `prompts/`, `raw/`.

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `aicli/services/qa_orchestrator.py` | Create | `trigger_qa()`, blackboard I/O, `_parse_agent_json`, `_git`, badge reader |
| `aicli/services/qa_runner.py` | Create | Stage driver: repro → verify → regression → aggregate → correction loop |
| `aicli/services/qa_prompts.py` | Create | Role contracts, output schemas, `SECURITY_CHECKLIST` |
| `aicli/commands/qa_cmd.py` | Create | Hidden `qa-run` Typer command (re-entry point) |
| `main.py` | Modify | `app.add_typer(qa_cmd.app, name="qa-run")` |
| `aicli/commands/sync.py` | Modify | One guarded `trigger_qa(...)` call after `clear_active_ticket()` (line 439), inside `if save:` |
| `aicli/tui/widgets.py` | Modify | `_fetch()` sets `t["_qa"]`; `_row()` appends badge; `on_mount` adds `set_interval(5.0, self._poll_qa)`; footer gains `[[e]] evidencia`; `on_key` handles `e` |
| `aicli/tui/screens.py` | Modify | `LogScreen.__init__(log_path=None, title="MAGNA — Logs")`; `compose()` uses them |
| `tests/test_qa_orchestrator.py` | Create | Unit + boundary tests (see Testing Strategy) |

`LogScreen`'s single existing call site (`screens.py:1300`, `LogScreen()`) keeps working — both new
params are keyword-defaulted, matching the project's "don't break callers" convention. QA evidence is
shown as `LogScreen(run_dir / "evidence.log", title=f"QA — {tid}")`; the aggregator writes
`evidence.log` as a flat human-readable digest so the `TextArea` needs no JSON rendering logic.

Badge in `_row()`, appended after the `⟳×n` chip — symbol **and** colour, never colour alone:

```python
qa = t.get("_qa")            # {"ch": "✓", "col": _OK, "state": "passed"} | None
if qa:
    txt.append("  " + qa["ch"], style=qa["col"])
```

`◔` running (`_ACCENT`) · `✓` passed (`_OK`) · `✗` failed (`_ERROR`) · `?` dudoso (`_WARN`) ·
`!` manual_review (`_WARN` bold) · `⚠` error/stale (`_ERROR`). All BMP, Windows-Terminal safe, and the
row stays readable with colour stripped.

## Interfaces / Contracts

```python
def trigger_qa(*, ticket_id: str, project_path: Path, files: list[str],
               branch: str | None = None) -> str | None:  # returns run_id, None if disabled/failed
def read_qa_status(ticket_id: str) -> dict | None          # status.json + staleness applied
def read_qa_badge(ticket_id: str) -> dict | None           # {"ch","col","state"} for _row()
```

`status.json`

```json
{"schema":"qa.status/1","run_id":"<hex>","ticket_id":"ABC-123","project_path":"C:/repo",
 "branch":"feature/abc-123","state":"pending|repro|verify|regression|aggregating|correcting|done|error",
 "stage":"verify","attempt":0,"pid":1234,"started_at":0.0,"heartbeat":0.0,
 "events":[{"seq":1,"ts":0.0,"kind":"info|correction|terminal|error","msg":"…"}]}
```

`repro.json` — `{"schema":"qa.repro/1","run_id","status":"reproduced|not_reproduced|error","steps":[],
"expected":"","actual":"","evidence":[],"notes":"","error":null}`

`verify.json` — `{"schema":"qa.verify/1","run_id","status":"pass|fail|error",
"checks":[{"name":"","result":"pass|fail","detail":""}],"evidence":[],"db_reads":[],"error":null}`

`regression.json` — `{"schema":"qa.regression/1","run_id","status":"pass|fail|skipped|error",
"total":0,"passed":0,"failed":0,"failures":[{"test":"","message":""}],"report_path":"","error":null}`
(derived from Playwright's `--reporter=json`, not LLM-authored; `skipped` when `MAGNA_E2E_REPO` is unset.)

`verdict.json` — `{"schema":"qa.verdict/1","run_id","ticket_id","qa_verified":false,
"verdict":"passed|failed|dudoso|manual_review|error","reason":"","attempts":0,
"stages":{"repro":"","verify":"","regression":""},"commits":[],"finished_at":0.0}`

Aggregator truth table: repro `not_reproduced` ⇒ `dudoso` (never a correction). Any stage `error` or
timeout ⇒ `error`. verify `fail` and attempts < 2 ⇒ correction. verify `fail` after 2 attempts, or a git
pre-flight abort ⇒ `manual_review`. `qa_verified: true` requires verify `pass` **and** regression in
`{pass, skipped}`. Every terminal path writes `verdict.json` — there is no path where a trigger produces
no verdict.

## Testing Strategy

| Layer | What to Test | Approach |
|-------|-------------|----------|
| Unit | `_parse_agent_json` (fenced, trailing prose, garbage) | pytest, string fixtures |
| Unit | Aggregator truth table incl. all error/timeout paths | pure function over stage dicts |
| Unit | `_git` deny list rejects `push`/`fetch`/`remote`/`reset` | pytest `raises` |
| Unit | Badge/staleness mapping (`heartbeat` older than 600s) | frozen-clock fixture |
| Integration | Blackboard lifecycle + supersede: second `trigger_qa` invalidates the first `run_id` | `MYCONTEXT_HOME` tmp dir |
| Integration | `trigger_qa` launch failure writes `state: error`, never raises into `_sync_impl` | monkeypatched `Popen` raising `OSError` |
| Integration | Correction commit: staged pathspec only, message shape, no push, dirty-branch abort | throwaway `git init` repo in tmp |
| Manual | Detached survival, `claude -p` flags, badge/evidence rendering | spikes S1–S3 |

## Threat Matrix

| Boundary | Adversarial cases | Applicability | Design response | Planned RED tests |
|---|---|---|---|---|
| Documentation-like paths | executable-ish files in the touched set | **N/A** — the corrector only edits paths already in `archivos_tocados`; it never classifies or executes files | — | — |
| Git repository selection | relative vs absolute cwd, wrong repo | **Applicable** | `_git` always receives `cwd=project_path` resolved from the `Project` row; runner `cwd` is the same path | Commit helper run against a tmp repo asserts the commit lands there and nowhere else |
| Commit state | pre-existing staged changes, empty index, dirty worktree | **Applicable** | Explicit `git add -- <files>` only; empty diff ⇒ no commit, attempt counted; unrelated dirty files are never staged | Test with an unrelated dirty file: it stays unstaged and uncommitted; test empty diff ⇒ zero commits |
| Push state | tracking branch, first push, refspec | **Applicable** | `_git` deny list forbids `push`/`fetch`/`pull`/`remote`; no remote code path exists | Test `_git(["push", ...])` raises; test full correction cycle leaves `origin/<branch>` unchanged |
| PR commands | `--head`, env prefix, composed commands | **N/A** — no PR automation in this change | — | — |
| Subprocess/shell composition | argv injection via ticket id or branch name | **Applicable** | All subprocesses are list-argv with `shell=False`; ticket ids sanitized with `tickets._safe_id` for paths | Test a ticket id containing `&`/spaces produces a safe dir and a non-shell argv |

## Migration / Rollout

No migration; additive only. Kill switch: `trigger_qa` returns `None` immediately when
`os.getenv("MAGNA_QA") == "off"`, so the feature can be disabled without a rollback.

**Apply phase MUST run these spikes first, before any further code**:
- **S1** — in a scratch dir, `claude -p "List the skills and MCP servers you can use right now."`;
  record whether `security-review` and CodeGraph resolve headlessly. Outcome only relaxes prompts; no
  code depends on it.
- **S2** — capture `claude --help` and pin the exact non-interactive flags (`-p`, output format,
  permission handling). Blocks all agent-stage code.
- **S3** — launch a 30-second sleeper via the exact `Popen` call above from a `ctx` invocation, close the
  terminal, confirm it survives and writes `run.log`. Blocks the launcher.

## Open Questions

- [ ] Exact `claude -p` flags and whether non-interactive runs need an explicit permission mode (S2).
- [ ] How the verify stage drives `claude-in-chrome` headlessly, and where read-only DB credentials come
      from (currently assumed to be the project's existing environment).
- [ ] `MAGNA_E2E_REPO` as the Playwright repo locator — env var now; a per-project config field may be
      better once a second project uses it.
