# Design: QA Pipeline Verification Gaps

## Technical Approach

An increment on the shipped pipeline, not a rewrite. Three additive mechanisms on the existing
blackboard: (a) a **persisted per-ticket environment context** (`env_context.json`) confirmed once by
a pure-Python pre-flight gate that reuses `needs_input` / `answer.json` / `_finalize_awaiting_input` /
`resume_qa`; (b) **repro gains that environment** plus an explicit anti-lookup clause so isolation from
the fix diff survives a repro agent that now has shell, DB and browser; (c) a **combined `review`
stage** (`claude -p` via `invoke_stage()`) whose security findings are judged against a hard-coded
category allowlist by the aggregator, which remains the sole writer of `verdict.json`.

Decision numbering continues the archived `qa-orchestrator-pipeline` design (1–7) at **8**.

## Architecture Decisions

### Decision: Environment context is a separate persisted file, deliberately outside `_STAGE_ARTIFACTS`

**Choice** (decision 8): `run_dir/env_context.json`, schema `qa.env/1`, written once per ticket and
never deleted by a supersede. `_reset_blackboard()` iterates `_STAGE_ARTIFACTS` only, so a file absent
from that tuple survives every `trigger_qa()` and every `resume_qa()` **by construction** — no code
change to `_reset_blackboard` is needed. The guarantee is made explicit and testable:

```python
ENV_SCHEMA = "qa.env/1"
_ENV_CONTEXT_FILE = "env_context.json"
_PERSISTENT_ARTIFACTS = (_ENV_CONTEXT_FILE,)   # nunca borrados por supersede
assert not (set(_PERSISTENT_ARTIFACTS) & set(_STAGE_ARTIFACTS))
```

**Alternatives considered**: reusing `answer.json` (read-and-consume, single-use — it is erased by the
first prompt builder that reads it, so it cannot carry a value across runs); a new field inside
`status.json` (`status.json` **is** in `_STAGE_ARTIFACTS` and is deleted then rebuilt by
`resume_qa`); a row in the SQLite store.
**Rationale**: the user decided the DB/URL answer is confirmed **once per ticket and reused across
resyncs and correction retries**. `answer.json` has the exact opposite lifetime. A separate file keeps
the existing single-use answer channel untouched and makes "survives supersede" a one-line assertion
instead of a special case inside the reset loop. SQLite is rejected because the whole pipeline
communicates only through the file blackboard (archived design, Technical Approach).

### Decision: The pre-flight gate is pure Python and owns the question; answer routing is by invariant

**Choice** (decision 9): `env_preflight()` runs in `run_pipeline()` **before the first `_advance`**,
returns exactly one of `(env, None)` or `(None, question)`, and the caller pauses via the existing
`_finalize_awaiting_input`. Which pending `answer.json` belongs to the env question is resolved by a
stated invariant, not by a new field: **`answer.json` is read by the pre-flight if and only if
`env_context.json` is absent**, because env context is written before stage one and never reset, so no
verify/corrector answer can be pending while it is missing. The question dict carries an additive
`"topic": "env"` for the evidence log and diagnosis only.
**Alternatives considered**: an LLM pre-flight stage; tagging answers and having `resume_qa` move
`question` → `answered_question`; a second answer file per topic.
**Rationale**: "always confirm" must be deterministic — an agent asked to ask may not (proposal,
Approach). `"topic"` is ignored by `widgets._question_modal_kind`, so **`qa_cmd.py` and
`aicli/tui/widgets.py` stay unchanged** and the existing modal + `write_qa_answer` + `resume_qa` path
covers the new pause with zero new UI.

### Decision: Repro isolation is enforced by signature, not by prose

**Choice** (decision 10): `build_repro_prompt(run_dir, ticket_id, ticket_history, env)` gains
`_DB_ACCESS_RULE` and a new `_confirmed_env_block(env)` rendering only the confirmed `db`/`url`. It
does **not** gain `_answer_block()` (a verify/corrector answer may name the fix), does **not** gain
`_default_config_block()` (its "inspect the project config" instruction invites repo archaeology), and
has **no parameter capable of carrying a diff, commit or touched-file list**. The prompt adds an
explicit anti-lookup clause forbidding `git log/diff/show/blame` and reading recent commits.
**Alternatives considered**: a string denylist scan over the rendered prompt; passing the diff and
trusting the agent to ignore it.
**Rationale**: a rendered-text scan is defeated by the isolation clause itself (which must name
`diff`/`commit` to forbid them). The durable, testable guarantee is structural: assert
`inspect.signature(build_repro_prompt).parameters` has no diff/files parameter, and assert the
isolation clause is present. Repro now *has* shell, so prose alone is no longer sufficient.

### Decision: A blocked repro re-enters the env channel once, then becomes `manual_review`

**Choice** (decision 11): `REPRO_SCHEMA` gains `status: "blocked"` plus `blocked_reason: str|null`
and **no `needs_input` field** — the runner synthesises the question deterministically (same rationale
as decision 9) and routes it through the *env* channel: `clear_env_context(run_dir)` then
`_finalize_awaiting_input(...)` with `topic: "env"`, seeded with `blocked_reason`. A counter
`status["repro_blocked_pauses"]` (preserved by `resume_qa`'s `{**status, ...}` merge) bounds this at
`MAX_BLOCKED_REPRO_PAUSES = 1`. A second block falls through to the aggregator. A
`not_reproduced` with an empty `steps[]` is normalised to blocked (`repro_no_attempt_evidence`) so
`dudoso` can never be reached without recorded attempt evidence.
**Alternatives considered**: `blocked` ⇒ `manual_review` immediately (the proposal's assumption,
overruled by the user); adding `needs_input` to `REPRO_SCHEMA` and a third answer channel.
**Rationale**: a blocked repro is *always* an access/environment problem, which is exactly what the
env channel already asks about — one channel, one file, one invariant. The bound prevents an
ask→block→ask loop from nagging forever.

### Decision: `review` runs once, on the only path that can produce `passed`

**Choice** (decision 12): the gate is `_review_applies(verify, regression)` ≡
`verify.status == "pass" and regression.status in ("pass", "skipped")`, evaluated inside the loop
**after regression and immediately before `aggregate()`**.
**Alternatives considered**: running it right after `verify: pass` (the proposal's literal wording).
**Rationale**: verify can pass and regression still fail, which yields `failed` → correction → verify
again; the proposal's placement would spend up to **three** 600s `claude -p` invocations per ticket,
this placement spends exactly **one** and only on runs that would otherwise be stamped
`qa_verified: true`. It also makes "security findings never open a correction cycle" structural — the
loop has already exited. *Deviation*: proposal success criterion 3 ("every `verify: pass` is followed
by a review artifact") is restated as **"no run can reach `passed` without a review artifact"**, which
is the property that actually protects `qa_verified`.

### Decision: Severity authority is a hard-coded category allowlist; agent `severity` is decorative

**Choice** (decision 13): only a finding whose normalised `category` is in
`BLOCKING_SECURITY_CATEGORIES` can move a verdict, and it always moves it to `manual_review` /
`security_finding_severe`. The agent's `severity` string is written to `evidence.log` and **never read
by `aggregate()`**. Everything else — every non-allowlisted category, every `quality` finding — is
advisory-only.

```python
BLOCKING_SECURITY_CATEGORIES = frozenset({
    "sql_injection", "command_injection", "path_traversal", "unsafe_deserialization",
    "credential_exposure", "sensitive_data_exposure",
    "auth_bypass", "authorization_bypass", "xss", "ssrf",
})

def _blocking_security_findings(review: dict) -> list[dict]:
    findings = ((review.get("security") or {}).get("findings")) or []
    return [f for f in findings if isinstance(f, dict)
            and str(f.get("category", "")).strip().lower() in BLOCKING_SECURITY_CATEGORIES]
```

**Alternatives considered**: trusting `severity: "severe"` from the agent (the proposal's assumption,
overruled by the user); a configurable allowlist.
**Rationale**: a free-form severity label is a non-deterministic gate — the same finding blocks or not
depending on the agent's mood. A closed vocabulary means the blocking set is reviewable, diffable and
unit-testable, and an unknown category degrades to advisory instead of to a random verdict.

### Decision: A `review` stage error is `manual_review`, not `error`

**Choice**: `review.status == "error"` ⇒ `manual_review` / `review_stage_error`.
**Alternatives considered**: mapping it to `error` like every other stage error; letting it pass.
**Rationale**: repro/verify/regression errors mean *"we don't know whether it works"* — a pipeline
fault, verdict `error`. A review error means *"it works but nobody reviewed it"* — a human-attention
condition. Passing is excluded because the aggregator's standing invariant is that no stage error can
yield `qa_verified: true`.

## Data Flow

```
resume_qa / trigger_qa ─► qa-run ─► run_pipeline()
   │
   ├─[0] env_preflight(run_dir, ticket_id)      pure Python, 0 tokens
   │        env_context.json? ──no──► consume answer.json ──none──► _finalize_awaiting_input
   │                │                        │                            (topic: env)  ⏸
   │               yes                  parse db=/url= ──► env_context.json (persisted, survives reset)
   │                ▼
   ├─[1] repro  claude -p (+env, −diff) ─► repro.json
   │        status=blocked ──► clear_env_context + pause (max 1) ──► ⏸
   ├─[2] verify ─► [3] regression
   ├─[4] review  claude -p  ─only if verify=pass & regression∈{pass,skipped}─► review.json
   └─[5] aggregate (pure Python) ─► verdict.json + evidence.log
```

Blackboard adds `env_context.json` (persistent) and `review.json`, `prompts/review.md`,
`live/review.log`, `raw/review.txt` (per-run).

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `aicli/services/qa_orchestrator.py` | Modify | `ENV_SCHEMA`, `REVIEW_SCHEMA`, `_STAGE_ARTIFACTS += ("review.json",)`, `_PERSISTENT_ARTIFACTS`, `read_env_context`/`write_env_context`/`clear_env_context`, `_consume_answer`, `_parse_env_answer`, `env_preflight` |
| `aicli/services/qa_prompts.py` | Modify | `build_repro_prompt(..., env)` + `_confirmed_env_block` + isolation clause; new `build_review_prompt`; new `REVIEW_CONDUCT_RULES`; `_consume_answer` delegates to `qa_orchestrator` |
| `aicli/services/qa_runner.py` | Modify | pre-flight hook, `_repro_blocked`, `run_review_stage`, `_review_diff`, `_review_applies`, `aggregate(review=...)`, `_verdict` stages, `_write_evidence_log(review=...)`, `_finalize(review=...)`, `run_pipeline(review_fn=...)` |
| `tests/test_qa_orchestrator.py` | Modify | New cases per Testing Strategy (additive; the 101 existing tests are the regression net) |
| `aicli/commands/qa_cmd.py`, `aicli/tui/widgets.py`, `aicli/tui/modals.py` | Unchanged | `topic` is an additive key the modal dispatcher ignores; the resume path already covers the new pause |

## Interfaces / Contracts

```python
# qa_orchestrator.py
def read_env_context(run_dir: Path) -> dict | None
def write_env_context(run_dir: Path, *, db: str, url: str, source: str) -> dict
def clear_env_context(run_dir: Path) -> None
def _parse_env_answer(value: str) -> tuple[str | None, str | None]     # "db=… url=…"
def env_preflight(run_dir: Path, ticket_id: str) -> tuple[dict | None, dict | None]

# qa_prompts.py
def build_repro_prompt(run_dir: Path, ticket_id: str, ticket_history: str, env: dict) -> Path
def build_review_prompt(run_dir: Path, ticket_id: str,
                        archivos_tocados: list[str], git_diff: str) -> Path

# qa_runner.py
def run_review_stage(run_dir: Path, project_path: Path,
                     ticket_id: str, archivos_tocados: list[str]) -> dict
def _review_diff(project_path: Path, archivos_tocados: list[str]) -> str
def _review_applies(verify: dict, regression: dict) -> bool
def _repro_blocked(repro: dict) -> str | None          # blocked_reason, o None
def aggregate(*, repro, verify, regression, attempts, commits, review: dict | None = None) -> dict
MAX_BLOCKED_REPRO_PAUSES = 1
```

`env_context.json`

```json
{"schema":"qa.env/1","ticket_id":"ABC-123","db":"magna_test",
 "url":"http://localhost:3000","source":"default_confirmed|user","confirmed_at":0.0}
```

env question (both shapes written into `status.json["question"]`)

```json
{"kind":"select","topic":"env","prompt":"QA ABC-123 — ¿contra qué DB/URL verifico?",
 "options":["DB: magna_test · URL: http://localhost:3000","Otro (escribir db y url a mano)"]}
{"kind":"text","topic":"env","options":null,
 "prompt":"QA ABC-123 — escribí el entorno así: db=<nombre> url=<http://…>"}
```

`repro.json` (modified) — `status` enum becomes `"reproduced" | "not_reproduced" | "blocked" | "error"`,
plus `"blocked_reason": "…"|null`. All other fields unchanged.

`review.json` (new, `qa.review/1`)

```json
{"schema":"qa.review/1","run_id":"<hex>","status":"ok|skipped|error",
 "security":{"findings":[{"category":"sql_injection","file":"src/db/query.ts","line":42,
                          "detail":"…","severity":"high"}]},
 "quality":{"findings":[{"kind":"duplication|dead_code|convention","file":"…","line":0,
                         "detail":"…","existing":"ruta/al/helper/que/ya/existe"}]},
 "error":null}
```

`status.json` — `state` enum gains `"review"`; the run carries an optional
`repro_blocked_pauses: int`. `verdict.json` — `stages` gains `"review"`; `reason` gains
`security_finding_severe`, `review_stage_error`, `repro_blocked`, `repro_no_attempt_evidence`.

Aggregator truth table (additions only, in evaluation order): `repro blocked` ⇒ `manual_review` /
`repro_blocked`. Inside the existing `verify pass && regression ∈ {pass, skipped}` branch, before
returning `passed`: `review error` ⇒ `manual_review` / `review_stage_error`; any
`_blocking_security_findings(review)` ⇒ `manual_review` / `security_finding_severe`; otherwise
unchanged `passed`. Quality findings are never consulted.

`run_pipeline()` hook points, against today's line numbers: pre-flight between L387 and L389;
`_repro_blocked` branch merged into the L392 early-exit block; review block between L430 and L432;
`review=` added to the three `aggregate()` call sites (L394, L432, L462) and the three `_finalize()`
call sites (L398, L434, L467).

## Testing Strategy

| Layer | What to Test | Approach |
|-------|-------------|----------|
| Unit | `_PERSISTENT_ARTIFACTS ∩ _STAGE_ARTIFACTS == ∅`; `_reset_blackboard` deletes `review.json` and preserves `env_context.json` | tmp `run_dir` |
| Unit | `_parse_env_answer`: valid pair, missing half, newline/backtick injection, over-length | string fixtures |
| Unit | `env_preflight` state machine: no context ⇒ select; `Otro…` ⇒ text; parsed answer ⇒ file written; existing context ⇒ no question, no answer consumed | tmp `run_dir` |
| Unit | `build_repro_prompt` signature carries no diff/files param; rendered prompt has the isolation clause and the confirmed db/url | `inspect.signature` + substring |
| Unit | `_blocking_security_findings`: allowlisted category blocks regardless of `severity: "low"`; unknown category never blocks even at `severity: "severe"`; quality findings never block | dict fixtures |
| Unit | Aggregator additions: `blocked` ⇒ `manual_review`; `not_reproduced` + empty `steps` ⇒ `repro_no_attempt_evidence`; review error ⇒ `manual_review`; `aggregate()` without `review=` behaves exactly as today | pure function |
| Unit | `_review_diff` with empty `archivos_tocados` issues **no** repo-wide diff and returns `""` | fake `_git` recorder |
| Integration | `resume_qa` after an env answer: `env_context.json` written, reused on the next `trigger_qa`, user asked exactly once per ticket | `MYCONTEXT_HOME` tmp dir |
| Integration | Repro `blocked` ⇒ pause once ⇒ still blocked ⇒ `manual_review`, never `dudoso`, never a correction | injected `repro_fn` |
| Integration | `run_pipeline` invokes `review_fn` exactly once on the passing path and zero times when regression fails | injected stage fns, call counter |

## Threat Matrix

| Boundary | Adversarial cases | Applicability | Design response | Planned RED tests |
|---|---|---|---|---|
| Git repository selection | review agent inspects the wrong repo / wrong base | **Applicable** | `_review_diff` calls `_git(..., cwd=project_path)` only; base resolved via read-only `merge-base` over `("main","master","develop")` with a working-tree-diff fallback | Fake `_git` asserts every argv is read-only (`merge-base`/`diff`) and every `cwd` is `project_path` |
| Commit state | review agent stages, commits or amends while inspecting | **Applicable** | `build_review_prompt` inlines `REVIEW_CONDUCT_RULES`: read-only, never edit, never `git add`/`commit`, never run migrations or DB writes; the runner issues no `add`/`commit` on the review path | Throwaway `git init` repo: a full review run leaves index and HEAD byte-identical |
| Push state | review agent reaches a remote | **Applicable** | Every git call goes through the existing `_git` denylist (`push`/`fetch`/`pull`/`remote`/`reset`/`checkout`/…); no remote code path is added | Existing `_git` denylist tests extended to assert `_review_diff` never constructs a denylisted argv |
| Diff scope blowout | empty `archivos_tocados` ⇒ `git diff <sha>` diffs the whole repo into a prompt file | **Applicable** | Empty list short-circuits to `review.json` `status: "skipped"` with zero findings and **no** `claude -p` call | Empty-files run: no subprocess, `status == "skipped"`, verdict still `passed` |
| Subprocess/shell composition | user-supplied db/url or `blocked_reason` reaching argv | **Applicable** | Env values are stored parsed (strict `db=`/`url=` extraction, no newlines/backticks, length-capped) and rendered only into the prompt **file**; `invoke_stage` argv stays `[exe, "-p", "Read <path> …"]`, `shell=False` | Answer containing `` ` ``, `;`, a newline and 5 000 chars ⇒ rejected by `_parse_env_answer`, question re-asked, argv unchanged |
| Prompt injection via ticket data | ticket history / diff instructs the review agent to hide a finding | **Applicable** | The aggregator is the sole judge and reads only `category` against a closed frozenset; an agent that omits or invents categories cannot fabricate a `passed` it would not already get, and cannot block outside the allowlist | Review JSON with `severity:"none"` on an allowlisted category still blocks; invented category `"totally_fine"` never blocks |
| Documentation-like paths / executable classification | — | **N/A** — the review stage never edits, executes or classifies files; it only reads | — | — |
| PR commands | — | **N/A** — no PR automation in this change | — | — |

## Migration / Rollout

No migration. All additions are keyword-defaulted (`review=None`, `env` rendered from a file that may
not exist yet), so existing callers and the 101 existing tests are unaffected. A ticket with a
blackboard written before this change simply has no `env_context.json` and is asked once on its next
run. Rollback is a revert of the change's commits; `env_context.json` and `review.json` become inert
files. The existing `MAGNA_QA=off` kill switch still disables everything without a revert.

## Open Questions

- [ ] Re-confirmation escape hatch: today the only way to change a ticket's confirmed environment is
      deleting `env_context.json` by hand. A `ctx qa env --reset <TICKET>` command is deferred.
- [ ] `BLOCKING_SECURITY_CATEGORIES` is a starter list (10 entries) chosen for web/CRUD tickets; it
      will need review once real findings accumulate.
- [ ] Whether the repro agent can actually drive a browser headlessly under `claude -p` is still
      unverified (inherited open question from the archived design) — a blocked repro now pauses for
      the user instead of silently degrading, which bounds the damage.
