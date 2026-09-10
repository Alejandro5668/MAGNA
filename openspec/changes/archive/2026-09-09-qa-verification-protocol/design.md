# Design: QA verification protocol for bug-shaped tasks

## Technical Approach

Three pure, stdlib-only additions plus two keyword-defaulted parameter extensions. A new module
`aicli/services/qa_protocol.py` owns the fixed Spanish instruction block and the bug heuristic.
`build_context` gains `es_bug: bool = False` and prepends the rendered protocol ahead of the team-rule
fragments. `_execute_task` computes `es_bug` once from its own locals and threads it into the single
`build_context` call site (`task.py:288`). Ground truth flows back through a JSON file the Claude Code
session writes at the end of verification, which `ctx sync` reads, consumes and forwards to
`save_round(..., qa_verified=...)`.

No new dependency, no new command, no orchestration code. The protocol is text; every runtime behavior
(browser, DB, Playwright) happens inside the Claude Code session.

## Architecture Decisions

### Decision 1: `QA_PROTOCOL` is a constant with sentinel placeholders, rendered by `str.replace`

**Choice**: `QA_PROTOCOL: str` stays a module-level constant containing two literal sentinels,
`<E2E_DIR>` and `<QA_RESULT_DIR>`. A thin `render_qa_protocol(project_id: int | None) -> str` resolves
them with `str.replace`. `build_context` calls the renderer; the raw constant remains exported so tests
can assert on its text.

**Alternatives considered**: (a) fully fixed text naming `~/.mycontext/projects/<project_id>/e2e/`
literally; (b) `str.format` templating; (c) threading `project_id` into the protocol from `task.py`.

**Rationale**: The session context file lives at `~/.mycontext/session_context_{ts}.md`
(`caller.py:140`) — flat, with no project id in its path — so Claude has *no way* to derive
`project_id` at runtime. Leaving `<project_id>` unresolved is exactly the condition that pushes Claude
to improvise a location, which is the proposal's "Playwright inside the client repo" risk. `.format()`
is rejected because the protocol embeds a literal JSON example with `{`/`}`; every brace would need
doubling, which makes the block unreadable and fragile to edit. `build_context` already has
`modules[0].project_id` (`builder.py:32`), so no new parameter is needed. When `modules` is empty the
sentinel resolves to the literal `<project_id>` path and the protocol instructs Claude to ask.

### Decision 2: verification result at `~/.mycontext/qa_results/<SAFE_ID>.json`, read-and-delete by `ctx sync`

**Choice**: Claude writes `~/.mycontext/qa_results/<TICKET_ID>.json`. A new
`read_qa_result(ticket_id: str) -> dict | None` in `aicli/services/tickets.py` reads it, deletes it, and
returns the parsed dict; `sync.py` calls it just before `save_round(...)` (`sync.py:390`) and passes
`qa_verified`.

**Alternatives considered**: `~/.mycontext/tickets/<TICKET_ID>.qa_result.json` (the path suggested in
the phase brief), a PID-scoped marker like `ticket_activo_{pid}.json`, or a new field appended to the
existing per-ticket JSON.

**Rationale**: The `tickets/` directory is **not** a free namespace — `load_tickets()` globs
`_tickets_dir().glob("*.json")` (`tickets.py:126`) and keys results by `path.stem`, so
`ABC-123.qa_result.json` would surface as a phantom ticket `ABC-123.qa_result`. Today it happens to be
filtered out only because the freshness check (`ultima_actividad` missing → `0`) drops it; that is
incidental protection, not a contract. A sibling `qa_results/` directory removes the collision by
construction. A PID-scoped name is unusable because Claude does not know the AICLI PID. Writing into
the ticket JSON directly would make the session a concurrent writer of a file `_mutate_ticket` assumes
it owns.

Path is built with the existing `_safe_id()` (`tickets.py:29`) so sanitization stays identical to
`_ticket_path` — one sanitizer, one convention.

### Decision 3: the result file is deleted after being read

**Choice**: `read_qa_result` unlinks the file after a successful read, and also on parse failure.

**Rationale**: The file is a one-shot handoff for exactly one sync run. Leaving it would make the next
`ctx sync` on the same ticket (a second round, or a reopen weeks later) record a stale `qa_verified`
from a previous session — a silent lie in the very field whose purpose is truthfulness. Deleting a
corrupt file too prevents it from poisoning every future round. `_write_ticket`'s atomic
`tmp.replace(path)` pattern is not needed here (single writer, single reader), but the delete uses
`unlink(missing_ok=True)` and is wrapped so a permission error never aborts sync.

### Decision 4: `qa_verified` defaults to `None`, never `False`

**Choice**: missing file, unreadable file, invalid JSON, or a `verified` value that is not a real
`bool` all yield `None`.

**Rationale**: Hard requirement from the proposal. `False` means "verification ran and failed" —
actionable signal. `None` means "we do not know". A crashed session, a closed terminal, or a non-bug
task must not be counted as a QA failure, or the reopen-rate metric this whole change exists to enable
becomes noise. Explicitly: `isinstance(data.get("verified"), bool)` — a string `"true"` is `None`, not
truthy.

### Decision 5: `is_bug_task` matches on accent-folded, whitespace-collapsed text with word boundaries

**Choice**: normalize (NFD accent strip + lowercase + whitespace collapse) the concatenation of
`task_desc`, `jira_data["summary"]` and `jira_data["description"]`, then match one precompiled
alternation regex with `\b` boundaries. Multi-word phrases are part of the same alternation.

**Alternatives considered**: plain substring `in` checks; `task_desc.lower()` only; an AI
classification call.

**Rationale**: Substring matching produces indefensible false positives ("error" inside "terrorismo",
"falla" inside "fallar" is fine but "bug" inside "debug"/"bugalú" is not). Word boundaries keep recall
high without absurd hits. Accent folding is required because users type both "corrección" and
"correccion"; `unicodedata` is stdlib, so the no-dependency rule holds. An AI call is explicitly out of
scope (cost, latency, non-determinism) per the proposal.

### Decision 6: the reopen signal is a normalized phrase match, not `startswith`

**Choice**: check `"ticket reabierto" in normalized_text` (short-circuit before the regex), not
`task_desc.startswith("[TICKET REABIERTO")`.

**Rationale**: Both resume paths build the prefix identically (`screens.py:325`, `screens.py:522`), so
`startswith` would work *today* — but it breaks on any leading whitespace, a lowercase variant, a
changed bracket style, or a future path that embeds the marker mid-string. A normalized `in` check is
strictly more permissive, costs nothing, and cannot produce a false negative where `startswith`
succeeds. Recall over precision, per the proposal.

### Decision 7: `is_bug_task` is pure and tolerant of malformed `jira_data`

**Choice**: no module-level mutable state, no I/O, no logging. `jira_data` values are coerced with
`str(...)` only when they are already `str`; anything else is skipped.

**Rationale**: `_execute_task` runs on a background `ThreadPoolExecutor(max_workers=1)` thread in the
TUI path — shared state would be a cross-run corruption vector. `_resume_jira_context` returns a dict
whose shape differs from `fetch_issue` (`jira.py:95-104`, plus a `comments` key), so defensive `.get`
access with type checks avoids a `TypeError` killing the whole task run for a classification detail.

## Data Flow

```
ctx task / resume (CLI or TUI)
        │
        ▼
_execute_task  ── is_bug_task(task_desc, jira_data) ──► es_bug: bool   (pure, no I/O)
        │
        ▼
build_context(relevant, project_path=path, es_bug=es_bug)
        │
        ├─ es_bug ─► render_qa_protocol(project_id)  ──► fragments[0]
        ├─ team rules ─► fragments[1..n]
        └─ rol.md / PROYECTO.md / modules
        │
        ▼
session_context_{ts}.md ──► Claude Code session
                                    │
                    (verifies, writes Playwright suite in ~/.mycontext/projects/<id>/e2e/)
                                    │
                                    ▼
                  ~/.mycontext/qa_results/<TICKET_ID>.json   {verified, attempts, ...}
                                    │
ctx sync ── read_qa_result(ticket_id) ──► (parse, DELETE) ──► qa_verified: bool | None
                                    │
                                    ▼
                     save_round(..., qa_verified=qa_verified)
                                    │
                                    ▼
                  ~/.mycontext/tickets/<TICKET_ID>.json  → rondas[-1]["qa_verified"]
```

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `aicli/services/qa_protocol.py` | Create | `QA_PROTOCOL`, `render_qa_protocol()`, `is_bug_task()`; stdlib only (`re`, `unicodedata`, `pathlib`) |
| `aicli/services/builder.py` | Modify | `build_context(..., es_bug: bool = False)`; prepend rendered protocol ahead of `builder.py:17-24` |
| `aicli/commands/task.py` | Modify | Compute `es_bug` in `_execute_task`; pass at `task.py:288` |
| `aicli/services/tickets.py` | Modify | `_qa_results_dir()`, `read_qa_result()`, `save_round(..., qa_verified: bool \| None = None)` |
| `aicli/commands/sync.py` | Modify | Read + consume QA result before `save_round` (`sync.py:390`) |
| `tests/test_tickets.py` | Modify | `read_qa_result` + `save_round(qa_verified=...)` round-trip (unittest, `MYCONTEXT_HOME`) |
| `tests/test_commands.py` | Modify | `is_bug_task` cases + `build_context` real-argument coverage (`check()` harness) |
| `knowledge/decisions.md` | Modify | New DEC entry |

## Interfaces / Contracts

### `aicli/services/qa_protocol.py`

```python
QA_PROTOCOL: str  # bloque fijo en español; contiene los sentinelas <E2E_DIR> y <QA_RESULT_DIR>


def render_qa_protocol(project_id: int | None = None) -> str:
    """Resuelve los sentinelas de rutas del protocolo. str.replace, no format —
    el bloque contiene llaves literales del ejemplo JSON."""
    base = Path.home() / ".mycontext"
    pid = str(project_id) if project_id is not None else "<project_id>"
    return (
        QA_PROTOCOL
        .replace("<E2E_DIR>", str(base / "projects" / pid / "e2e"))
        .replace("<QA_RESULT_DIR>", str(base / "qa_results"))
    )
```

`render_qa_protocol` deliberately uses `Path.home()` and not `tickets._base_dir()`: `MYCONTEXT_HOME` is
a *test* redirection, and the protocol text is consumed by a real Claude session against the real home.

### `QA_PROTOCOL` — exact text

```markdown
# Protocolo de verificación QA — obligatorio en este caso

Esta tarea fue clasificada como bug. Nada de lo que sigue es opcional.
Un fix sin verificar no está terminado, no importa lo obvio que parezca el cambio.

## 1. Plan de pruebas — antes de verificar
Escribí el plan antes de ejecutarlo, como lista numerada:
- Camino feliz: el flujo exacto que el ticket dice que falla.
- Casos borde que identifiques para ESTE bug: roles y permisos distintos, datos
  vacíos, datos con volumen, estados previos del registro, filtros por empresa.
Seguí el plan punto por punto y reportá el resultado de cada punto.
Si aparece un caso nuevo durante la verificación, agregalo al plan y decilo.

## 2. Reproducí antes de creerle al ticket
- Reproducí el bug vos mismo, desde cero, antes de proponer un fix.
- El diagnóstico del ticket es una hipótesis, no un hecho: confirmalo o descartalo con evidencia.
- Si no lográs reproducirlo, decilo explícitamente en vez de arreglar a ciegas.

## 3. Verificación en navegador real
- Verificá con `claude-in-chrome` sobre la app corriendo, no leyendo código.
- Revisá la consola (errores JS) y la pestaña de red (status, payload, respuesta),
  además del estado visual.
- Un mensaje de éxito en la UI no es evidencia suficiente.

## 4. Verificación en base de datos
- Si el bug involucra escrituras (INSERT/UPDATE/DELETE), consultá la tabla real
  y mostrá el SELECT y su resultado.
- Verificá el dato, no el mensaje.

## 5. Producción es solo lectura
- En producción: SELECT únicamente.
- Cualquier escritura en producción requiere autorización explícita del usuario
  para este caso puntual. No la asumas.

## 6. Si falta información, pará y preguntá
- Si te falta algo para verificar (backup de la BD del cliente, credenciales,
  usuario de prueba con cierto rol, entorno levantado), pará y pedilo explícitamente.
- No inventes datos ni asumas el estado del entorno.

## 7. Reintentos y escalamiento
- Si la verificación falla, no repitas el mismo intento: usá la evidencia nueva
  (consola, red, BD) para formular una hipótesis distinta.
- Máximo 3 ciclos de fix + verificación.
- Al tercer ciclo fallido, pará y escalá al usuario con: hipótesis actual,
  evidencia recolectada, qué descartaste y qué falta.
- Nunca declares el caso resuelto sin verificación exitosa. Si no verificaste, decilo.

## 8. Suite de regresión (Playwright)
Ubicación obligatoria: `<E2E_DIR>`
- Ese directorio es un proyecto Node independiente, con su propio `package.json`.
- **Nunca** crees `package.json`, `node_modules` ni tests de Playwright dentro del
  repositorio del cliente.
- Si Playwright o sus navegadores no están instalados ahí, instalalos vos en ese
  directorio sin preguntar.
- Si el módulo afectado ya tiene tests ahí, corré esa suite ANTES de confiar en
  una verificación nueva.
- Después de un fix verificado, generá o actualizá el test que cubre este bug y
  dejalo pasando.
- Si la ruta de arriba todavía contiene `<project_id>`, preguntá al usuario cuál
  es antes de crear nada.

## 9. Resultado de la verificación — al cerrar la sesión
Antes de terminar, escribí este archivo:
`<QA_RESULT_DIR>/TICKET.json`, donde `TICKET` es el ticket de Jira de esta tarea
en MAYÚSCULAS (por ejemplo `ABC-123.json`).

    {
      "verified": true,
      "attempts": 2,
      "ticket_id": "ABC-123",
      "test_plan": ["camino feliz: ...", "borde: rol supervisor ..."],
      "evidence": "qué probaste y cómo confirmaste el resultado"
    }

- `verified`: `true` solo si la verificación en navegador (y en BD si aplica) pasó.
  Si falló o no llegaste a verificar, `false`.
- `attempts`: cantidad de ciclos fix + verificación que hiciste (1 a 3).
- Si esta tarea no tiene ticket de Jira, no escribas el archivo.
- No lo escribas antes de terminar de verificar.
```

### `is_bug_task` — proposed body

```python
_REOPEN_MARKER = "ticket reabierto"

_BUG_KEYWORDS = (
    # sustantivos
    "bug", "bugs", "error", "errores", "falla", "fallas", "fallo", "fallos",
    "defecto", "incidencia", "incidente", "regresion", "excepcion", "traceback",
    # verbos / acciones
    "arreglar", "arregla", "corregir", "corrige", "correccion", "fix", "hotfix",
    "solucionar", "reparar", "reabierto", "reabrir", "rechazado", "devuelto",
    # síntomas
    "roto", "rota", "rompe", "rompio", "crashea", "se cae", "se cuelga",
    "se traba", "no funciona", "no anda", "no carga", "no guarda", "no muestra",
    "no aparece", "no actualiza", "no elimina", "no envia", "no responde",
    "no valida", "no filtra", "no deja", "no calcula", "no coincide",
    "pantalla en blanco", "error 500", "timeout", "duplicado", "duplicados",
    "incorrecto", "incorrecta", "mal calculado", "dato erroneo",
)

_BUG_RE = re.compile(r"\b(?:" + "|".join(re.escape(k) for k in _BUG_KEYWORDS) + r")\b")


def _normalize(text: str) -> str:
    """Minúsculas, sin acentos y con espacios colapsados — para que 'corrección'
    y 'correccion' matcheen igual y las frases de varias palabras funcionen."""
    folded = unicodedata.normalize("NFD", text.lower())
    folded = "".join(c for c in folded if unicodedata.category(c) != "Mn")
    return " ".join(folded.split())


def is_bug_task(desc: str, jira_data: dict | None = None) -> bool:
    """Heurística por palabras clave sobre la descripción de la tarea y, si hay,
    el summary/description de Jira. Función pura: sin estado, sin I/O —
    corre en el thread de fondo del TUI."""
    parts: list[str] = [desc or ""]
    if isinstance(jira_data, dict):
        for key in ("summary", "description"):
            value = jira_data.get(key)
            if isinstance(value, str):
                parts.append(value)

    text = _normalize(" ".join(parts))
    if not text:
        return False
    # Una reapertura es, casi siempre, un fix que falló — señal positiva por sí sola
    if _REOPEN_MARKER in text:
        return True
    return bool(_BUG_RE.search(text))
```

### `build_context` — diff sketch

```python
-def build_context(modules: list[Module], project_path: Path | None = None) -> tuple[str, list[str]]:
+def build_context(
+    modules: list[Module],
+    project_path: Path | None = None,
+    es_bug: bool = False,
+) -> tuple[str, list[str]]:
     """
     Ensambla session_context.md a partir de módulos relevantes.
     Retorna (context_str, warnings) — warnings lista problemas de frescura detectados.
+    es_bug=True antepone el protocolo de verificación QA como primer fragmento.
     """
     warnings: list[str] = []
     fragments: list[str] = []

+    # El protocolo QA va antes que las reglas del equipo: una verificación que
+    # Claude pueda despriorizar no sirve
+    if es_bug:
+        project_id = modules[0].project_id if modules else None
+        fragments.append(render_qa_protocol(project_id))
+
     # Team rules come first so Claude treats them as highest-priority constraints
     rules_dir = Path.home() / ".mycontext" / "rules"
```

Import added at the top: `from aicli.services.qa_protocol import render_qa_protocol`. No circular import
risk — `qa_protocol.py` imports only stdlib.

### `_execute_task` — diff sketch

`task_desc` and `jira_data` are already `_execute_task` parameters (`task.py:109`, `task.py:114`), so
the computation needs no new plumbing:

```python
+    from aicli.services.qa_protocol import is_bug_task
+    es_bug = is_bug_task(task_desc, jira_data)
+
-    context, ctx_warnings = build_context(relevant, project_path=path)
+    context, ctx_warnings = build_context(relevant, project_path=path, es_bug=es_bug)
```

`es_bug` is computed immediately before the call (not at function top) so the local stays adjacent to
its only use. It is passed by keyword, matching the existing `project_path=path` style.

### `tickets.py` additions

```python
def _qa_results_dir() -> Path:
    # Directorio propio: tickets/ lo recorre load_tickets() con glob("*.json")
    return _base_dir() / "qa_results"


def read_qa_result(ticket_id: str) -> dict | None:
    """Lee el resultado de verificación que dejó la sesión de Claude y lo consume
    (borra el archivo) para que un sync posterior no lea un resultado viejo.
    Devuelve None si no existe o si está corrupto."""
    path = _qa_results_dir() / f"{_safe_id(ticket_id)}.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        data = None
    finally:
        try:
            path.unlink(missing_ok=True)
        except Exception:
            pass
    return data if isinstance(data, dict) else None


def save_round(..., memoria: dict | None = None, qa_verified: bool | None = None) -> None:
    ronda = {..., "memoria": memoria, "qa_verified": qa_verified}
```

`qa_verified` is appended last in the `ronda` dict, after `memoria`, so existing rounds read back
unchanged (`format_history` uses `.get`, `tickets.py:186-195`, and needs no edit).

### `sync.py` integration

Inserted inside the `if save:` block, immediately before `save_round(...)` (`sync.py:390`), where
`ticket_id` is already normalized (`sync.py:353`):

```python
+            qa_result = read_qa_result(ticket_id)
+            qa_verified = None
+            if qa_result is not None and isinstance(qa_result.get("verified"), bool):
+                qa_verified = qa_result["verified"]
+
             save_round(
                 ticket_id=ticket_id,
                 ...
                 memoria=case_memory,
+                qa_verified=qa_verified,
             )
```

`read_qa_result` is added to the existing `from aicli.services.tickets import ...` line
(`sync.py:17`). Reading only inside `if save:` is intentional: if the user declines to save the case,
consuming the file would silently discard the evidence.

## Testing Strategy

| Layer | What to Test | Approach |
|-------|-------------|----------|
| Unit (pure) | `is_bug_task` | `tests/test_commands.py`, `check()` harness — pure function, no filesystem, matches the file's smoke/import style |
| Unit (fs) | `build_context(es_bug=...)` | `tests/test_commands.py`, `check()` harness with `modules=[]` — no DB session is opened when `modules` is empty (`builder.py:31`), so no `MYCONTEXT_HOME` isolation is needed |
| Unit (fs) | `read_qa_result`, `save_round(qa_verified=...)` | `tests/test_tickets.py`, stdlib `unittest` + `MYCONTEXT_HOME` tempdir — this file already owns the ticket-storage contract |
| E2E | Browser/Playwright verification | Out of scope for AICLI tests — happens inside the Claude session, driven by `QA_PROTOCOL` text |

Concrete cases:

**`is_bug_task` (`tests/test_commands.py`)**
1. `"[TICKET REABIERTO ABC-123] no carga el listado"` → `True` (reopen marker).
2. `"[ticket reabierto abc-123] revisar"` → `True` (case-insensitive, no keyword in the reason).
3. `"Corregir el cálculo del total"` → `True` (accent-folded keyword `corregir`).
4. `"Migrar el módulo de reportes a la nueva API"` → `False`.
5. `"Agregar filtro por fecha"` with `jira_data={"summary": "Error al guardar", "description": ""}`
   → `True` — the Jira-summary-only match required by the proposal's success criteria.
6. `"Agregar filtro por fecha"` with `jira_data=None` → `False` (same text, negative control).
7. `"Refactor del debugger interno"` → `False` — word boundaries: `debugger` must not match `bug`.
8. `is_bug_task("", None)` → `False`; `is_bug_task("x", {"summary": None})` → `False` (no exception).

**`build_context` (`tests/test_commands.py`)** — replaces the current `callable(build_context)`
assertion at `test_commands.py:214/218`:
1. `build_context([], es_bug=False)` → returned context does NOT contain `"Protocolo de verificación QA"`.
2. `build_context([], es_bug=True)` → contains `"Protocolo de verificación QA"`, `"claude-in-chrome"`,
   and `"qa_results"`.
3. `build_context([], es_bug=True)` → the protocol block starts at index `0` of the returned string
   (ordering assertion: it precedes any team-rule fragment, which is the whole point of the placement).
4. `build_context([])` with no third argument → identical output to `es_bug=False` (default preserved,
   proves existing call sites are unaffected).
5. Returned `warnings` is a `list` in both cases.

**`read_qa_result` / `save_round` (`tests/test_tickets.py`)**
1. Write `qa_results/PROJ-100.json` with `{"verified": true, "attempts": 2}` → `read_qa_result("proj-100")`
   returns the dict (case-insensitive via `_safe_id`) **and** the file no longer exists.
2. Second `read_qa_result("PROJ-100")` → `None` (delete-after-read prevents stale reuse).
3. Corrupt file (`"{not json"`) → returns `None` and the file is deleted.
4. Missing file → `None`, no exception, no directory created.
5. `save_round("PROJ-100", ..., qa_verified=True)` → `rondas[-1]["qa_verified"] is True`.
6. `save_round("PROJ-200", ...)` without the argument → `rondas[-1]["qa_verified"] is None`.
7. `save_round(..., qa_verified=False)` → stored as `False`, and `format_history` still renders without
   error (backward compatibility of the reader).
8. A round saved before this change (legacy JSON with no `qa_verified` key) is read back by
   `format_history` without `KeyError`.

## Threat Matrix

N/A — no routing, shell, subprocess, VCS/PR automation, executable-file classification, or
process-integration boundary is introduced. `build_context` output is written to a context file that
`caller.py` already launches Claude Code with; this change adds text to that file, it does not add a
new process, argument, or command path. The only new filesystem writes are inside `~/.mycontext/`,
under paths derived from the existing `_safe_id()` sanitizer.

## Migration / Rollout

No migration required. `qa_verified` is a new optional key in newly appended `ronda` dicts; existing
ticket JSON files are never rewritten and all readers use `.get`. Both new parameters are
keyword-defaulted, so every existing caller stays valid. Rollback is a plain revert — see the
proposal's rollback plan.

## Open Questions

- [ ] None blocking. One assumption to confirm at apply time: the QA result filename uses the Jira
      ticket key as Claude reads it from the task text; if a session's task text carries no ticket key,
      no file is written and `qa_verified` stays `None` by design.
