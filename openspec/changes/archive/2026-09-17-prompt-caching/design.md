# Design: Prompt caching for module detection (`ctx task`)

## Technical Approach

Split `_detect_relevant_modules` into a stable prefix (module listing + `PROYECTO.md`) carried by `system` as a cacheable text block, and a variable suffix (`task_desc`, `file_context`, JSON instruction) carried by the user turn. One function, one query clause, one log line.

Verified against the installed SDK (`anthropic==0.107.0`, requirements.txt:6):

| Fact | Source |
|---|---|
| `system: Union[str, Iterable[TextBlockParam]]` — a plain string **cannot** carry `cache_control`, so `system` must be a list | `.venv/.../anthropic/resources/messages/messages.py:123` |
| `TextBlockParam = {"type","text","cache_control","citations"}` | `types/text_block_param.py:14-20` |
| `CacheControlEphemeralParam = {"type":"ephemeral", "ttl": "5m"\|"1h"}`, default `5m` | `types/cache_control_ephemeral_param.py:10-22` |
| `Usage.cache_creation_input_tokens` / `cache_read_input_tokens` are `Optional[int]` — **may be `None`** | `types/usage.py:18-22` |

## Code Shape (after)

```python
system_blocks = [{
    "type": "text",
    "text": (
        "Tenés que identificar qué módulos de un proyecto de software son relevantes\n"
        "para una tarea específica de desarrollo.\n"
        f"{project_ctx_block}\n"
        f"Módulos disponibles en el proyecto:\n{listing}"
    ),
    "cache_control": {"type": "ephemeral"},   # ttl omitted -> 5m default
}]

user_prompt = f"""Tarea del desarrollador: {task_desc}{file_context}

Analizá la tarea, entendé qué partes del sistema necesita tocar, y devolvé ÚNICAMENTE
un JSON con los nombres de los módulos relevantes, sin texto adicional:
["nombre_modulo_1", "nombre_modulo_2"]

Seleccioná solo los módulos que realmente necesitarán ser leídos o modificados.
Si no podés filtrar con seguridad, devolvé todos los nombres."""

response = client.messages.create(
    model="claude-sonnet-5", max_tokens=4000,
    thinking={"type": "adaptive"},
    system=system_blocks,
    messages=[{"role": "user", "content": user_prompt}],
)
```

**Prefix-purity invariant**: no task-derived byte may precede `cache_control`. Today `task_desc` sits at task.py:44, above the listing at :47 — that inversion is the defect being fixed. `model`, `max_tokens`, `thinking` and the parse at task.py:64-66 stay byte-identical (a `thinking` change invalidates reuse).

## Architecture Decisions

| Decision | Choice | Rejected | Rationale |
|---|---|---|---|
| Where the breakpoint lives | `system` array | `cache_control` on first user content block | `system` precedes `messages` in the cache hierarchy; structural separation beats string-ordering discipline |
| Breakpoint count | 1 block covering listing + `PROYECTO.md` | 2 blocks (split so a module edit spares the `PROYECTO.md` segment) | Both invalidate together on re-index anyway; 1 keeps the diff minimal and well inside the 4-breakpoint limit. Splitting is a measured follow-up |
| Ordering key | `.order_by(Module.id)` | `.order_by(Module.name)` | `id` is insertion order, indexed PK (free sort), collision-free, and **stable under rename**. `name` reorders the whole listing on any rename — exactly the silent cache-kill being prevented |
| TTL | default 5m (omit `ttl`) | `"1h"` at ~2x write cost | Proposal assumption 2 |
| Surfacing | `logging.info` matching `_call_claude` (indexer.py:202-206) | Rich console output | Proposal assumption 3 defers a user-facing cost surface |

## File Changes

| File | Action | Description |
|---|---|---|
| `aicli/commands/task.py:21-67` | Modify | Prompt split into cached `system` + variable user turn; usage log line |
| `aicli/commands/task.py:134` | Modify | `select(Module).where(Module.project_id == project.id).order_by(Module.id)` |
| `tests/test_prompt_caching.py` | Create | Offline payload-shape tests |

Side note: `modules[0].project_id` (task.py:145) becomes deterministic too; identical value either way since all rows share `project_id` — no behavior change.

## Data Flow

    DB (ORDER BY id) ─┐
    PROYECTO.md ──────┴─→ system[0].text + cache_control ──┐
                                                           ├─→ messages.create
    task_desc / file / JSON instr ─→ messages[0].content ──┘
                                                           └─→ usage.cache_* ─→ logging.info

## Observability

```python
usage = response.usage
logging.info(
    "Claude OK [detect_modules] — input: %d | cache_write: %d | cache_read: %d | output: %d tokens",
    usage.input_tokens,
    usage.cache_creation_input_tokens or 0,
    usage.cache_read_input_tokens or 0,
    usage.output_tokens,
)
```

`or 0` is mandatory — both fields are `Optional[int]` and are `None` when no breakpoint applies.

## Testing Strategy

New `tests/test_prompt_caching.py`, following `tests/test_jira_comments.py` (`unittest.TestCase` + `unittest.mock.patch`, `sys.path` bootstrap, zero network).

**Mock**: `patch("anthropic.Anthropic")`. task.py:5 imports the *module*, so patching the class on it intercepts the call. Inspect `mock_cls.return_value.messages.create.call_args.kwargs`. Stub return: `.content = [SimpleNamespace(type="text", text='["mod_a"]')]`, `.usage` a MagicMock with int fields.

| # | Assertion (all offline) |
|---|---|
| 1 | `system` is a list; `system[0]["type"]=="text"`; `system[0]["cache_control"] == {"type":"ephemeral"}` |
| 2 | Prefix purity: `task_desc` sentinel absent from `system[0]["text"]`, present in `messages[0]["content"]` |
| 3 | Listing + `PROYECTO.md` sentinels present in `system[0]["text"]` |
| 4 | Two calls, same modules/context, different `task_desc` → byte-identical `system[0]["text"]` |
| 5 | `model`/`max_tokens`/`thinking` unchanged; return still filters modules by parsed names |
| 6 | `usage.cache_* = None` does not raise |
| 7 | Ordering: `"ORDER BY" in str(select(...).order_by(Module.id))` (no DB fixture exists today) |

Real cache behavior is **not** assertable offline. Live check belongs to `sdd-verify`: two `ctx task` runs <5 min apart; run 2 logs `cache_read > 0`; record run-1 `cache_creation_input_tokens` as the measured prefix size.

## Threat Matrix

N/A — no routing, shell, subprocess, VCS/PR automation, executable-file classification, or process-integration boundary is touched. (`_execute_task` later calls `launch_claude`, but this change does not modify that path.)

## Migration / Rollout

No migration. Re-verified under this design: `order_by` is a query clause, not DDL — `aicli/db/models.py` is untouched; no new dependency (`cache_control` is native to the pinned SDK); no config key, file format, or on-disk artifact. Rollback = revert the diff; server-side cache entries self-expire in 5 min.

## Open Questions

- [ ] Sonnet minimum cacheable prefix (1,024 tokens per both exploration sources) not re-verified: no web-fetch tool in this phase and the installed SDK ships no threshold constant (grepped `.venv/.../anthropic` — no match). Carry to `sdd-verify` as an empirical check, **not** a design/apply blocker.
- [ ] Measured prefix token size against a real project DB — requires a live call; deferred to `sdd-verify`.
