# Design: Semantic module prefilter (Chroma)

## Technical Approach

One new service (`aicli/services/embeddings.py`) owns every Chroma call. `Module.id` is the
document id; the embedded text is `f"{name}: {description}"`. `_detect_relevant_modules` calls
`query_modules(...)` once, **before** the listing loop, and builds the listing from the returned
top-`N=20` candidates. Every Chroma failure degrades to today's full-list behavior. Write sites
upsert after their existing `session.commit()`; a reconcile-on-query pass backfills and self-heals.

## Architecture Decisions

### Decision: Reconcile compares stored text, not just missing ids

**Choice**: `collection.get(include=["metadatas"])` once per query; a module is re-upserted when its
id is absent **or** `metadatas["text"]` differs from the current `f"{name}: {description}"`.
**Alternatives**: missing-ids-only diff (proposal wording); a `description_hash` SQLite column.
**Rationale**: the weakest part of this design is the coupling to N write sites. Text-compare makes
the store correct even if a write site is missed or a future one is added, for ~3 lines and no
migration. It is what makes the skipped 4th site below safe.

### Decision: 3 write sites, not 4 — `init._update_project` is intentionally skipped

**Choice**: upsert in `init._save_modules`, `file_cmd._save_zone_modules`, `sync._sync_impl`
(new-module branch only). `init._update_project` (`init.py:248-253`) gets **no** upsert.
**Alternatives**: all 4 sites as the proposal scoped.
**Rationale**: verified in source — `_update_project` writes only `content_path` and
`last_updated_at`; it cannot change `name` or `description`, so the embed text is unchanged and the
upsert would be a no-op. Same for `sync.py:224-228` and the `existing` branch generally. Reconcile
covers the self-heal case that site would otherwise buy. **This deviates from approved scope — flag
for override.** If the embed text ever widens to include the doc snippet, this site becomes
load-bearing and must be added back.

### Decision: hidden `ctx embed-selftest` command as the frozen-exe probe

**Choice**: add `aicli/commands/embed_selftest.py`, registered `hidden=True` in `main.py`.
**Alternatives**: run a `scripts/*.py` probe against the exe; run a full `ctx task`.
**Rationale**: you cannot execute arbitrary Python inside a PyInstaller binary — the only way to
exercise `chromadb`/`onnxruntime` **inside `MAGNA.exe`** is a code path the binary exposes. Precedent
exists (archived `qa-orchestrator-pipeline` added hidden `ctx qa-run`). It needs no
`ANTHROPIC_API_KEY`, so the blocking gate is hermetic. This is a deliberate exception to "no commands
nobody uses yet": it runs on every build.

### Decision: the final name→Module resolution still runs against the full `modules` list

**Choice**: `return [m for m in modules if m.name in names]` is left untouched.
**Rationale**: the prefilter shrinks only what the model *sees*; a name resolving outside the top-N
still maps. The prefilter can reduce prompt size, never correctness.

## Data Flow

    task_desc ──→ query_modules(project_id, modules, task_desc)
                        │  len(modules) <= 20 ─────────────→ modules (no-op)
                        │  reconcile(collection, modules)      ↑
                        ├─ collection.query(top 20) ─→ ids ─→ map to Module
                        └─ any Exception ─→ log.warning ───────┘
                             │
                       candidates (+ --file pin union) ──→ listing ──→ cached system block

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `aicli/services/embeddings.py` | Create | Client, collection, upsert, reconcile, query (~85 lines) |
| `aicli/commands/embed_selftest.py` | Create | Hidden diagnostic; frozen-exe gate (~25 lines) |
| `aicli/commands/task.py:37-48` | Modify | Prefilter + `--file` union before the listing loop |
| `aicli/commands/init.py:120-151` | Modify | Upsert after commit |
| `aicli/commands/file_cmd.py:17-49` | Modify | Upsert after commit |
| `aicli/commands/sync.py:221-241` | Modify | Collect new modules, one upsert after the loop |
| `main.py:34,40+` | Modify | Register hidden `embed-selftest` |
| `requirements.txt` | Modify | `chromadb`, `onnxruntime` (direct pins only) |
| `ctx.spec` | Modify | `datas`/`hiddenimports`/`upx_exclude` |
| `scripts/verify_frozen.ps1` | Create | Blocking frozen-exe verification (~40 lines) |
| `tests/test_module_prefilter.py` | Create | Mocked unit tests + one skip-unless integration test |

## Interfaces / Contracts

```python
# aicli/services/embeddings.py
CHROMA_PATH = Path.home() / ".mycontext" / "chroma"
TOP_N = 20
_client = None                                    # lazy; import chromadb only on first use

def _default_ef():                                # patched by tests to avoid the ONNX download
    from chromadb.utils.embedding_functions import DefaultEmbeddingFunction
    return DefaultEmbeddingFunction()

def get_collection(project_id: int):
    global _client
    if _client is None:
        import chromadb
        from chromadb.config import Settings
        CHROMA_PATH.mkdir(parents=True, exist_ok=True)
        _client = chromadb.PersistentClient(
            path=str(CHROMA_PATH),
            settings=Settings(anonymized_telemetry=False),
        )
    return _client.get_or_create_collection(
        name=f"project_{project_id}", embedding_function=_default_ef()
    )

def _text(name: str, description: str) -> str:
    return f"{name}: {description}"

def _raw_upsert(collection, rows: list[tuple[int, str, str]]) -> None:
    collection.upsert(
        ids=[str(i) for i, _, _ in rows],
        documents=[_text(n, d) for _, n, d in rows],
        metadatas=[{"name": n, "text": _text(n, d)} for _, n, d in rows],
    )

def upsert_modules(project_id: int, rows: list[tuple[int, str, str]]) -> None:
    """(module_id, name, description). Never raises — the prefilter is optional."""
    if not rows:
        return
    try:
        _raw_upsert(get_collection(project_id), rows)
    except Exception as e:
        logging.warning("Chroma upsert falló (project %s): %s", project_id, e)

def _reconcile(collection, modules: list[Module]) -> None:
    """Lazy backfill + self-heal. Raises — caller degrades."""
    got = collection.get(include=["metadatas"])
    stored = dict(zip(got["ids"], got["metadatas"] or []))
    rows = [
        (m.id, m.name, m.description) for m in modules
        if str(m.id) not in stored
        or (stored[str(m.id)] or {}).get("text") != _text(m.name, m.description)
    ]
    if rows:
        logging.info("Chroma backfill: %d módulo(s)", len(rows))
        _raw_upsert(collection, rows)

def query_modules(project_id: int, modules: list[Module], task_desc: str,
                  n_results: int = TOP_N) -> list[Module]:
    if len(modules) <= n_results:
        return modules
    try:
        collection = get_collection(project_id)
        _reconcile(collection, modules)
        res = collection.query(query_texts=[task_desc], n_results=n_results, include=[])
        by_id = {str(m.id): m for m in modules}
        hits = [by_id[i] for i in res["ids"][0] if i in by_id]
        return hits or modules
    except Exception as e:
        logging.warning("Prefiltro semántico deshabilitado: %s", e)
        return modules
```

### `task.py` — exact insertion (replaces line 40's opening)

```python
    from aicli.services.embeddings import query_modules
    candidates = query_modules(modules[0].project_id, modules, task_desc) if modules else modules
    if file:                                   # el pin siempre visible para el modelo
        pinned = next((m for m in modules if m.file_path == file), None)
        if pinned and pinned not in candidates:
            candidates = [pinned] + candidates
    listing_parts = []
    for m in candidates:                       # antes: for m in modules
```
Everything below is untouched, including `return [m for m in modules if m.name in names]`.
`task.py:190-193` (the post-detection pin) also stays untouched — it is the second escape hatch.

### Write sites — exact shape

`init._save_modules` / `file_cmd._save_zone_modules`: collect each added/updated object into
`touched: list[Module]` inside the loop, then

```python
        session.commit()
        payload = [(m.id, m.name, m.description) for m in touched]   # ids exist post-commit
    upsert_modules(project.id, payload)                              # fuera del with
```

`sync._sync_impl`: in the `else` (new module) branch keep a local `new_m = Module(...)`,
`session.add(new_m); session.commit(); new_modules.append((new_m.id, name, description))`;
after the file loop, one `upsert_modules(project.id, new_modules)`.

## PyInstaller Packaging (blocking)

Note: the artifact is **`dist/MAGNA.exe`** (`ctx.spec` line 36 `name='MAGNA'`), not `ctx.exe`.

```python
from PyInstaller.utils.hooks import collect_data_files, collect_submodules, \
    collect_dynamic_libs, copy_metadata

datas += collect_data_files('chromadb')          # chromadb/migrations/**/*.sql — required
datas += collect_data_files('onnxruntime')
datas += copy_metadata('chromadb')               # chromadb reads its own dist version
datas += copy_metadata('onnxruntime')
datas += copy_metadata('tokenizers')
binaries = collect_dynamic_libs('onnxruntime')   # capi/*.dll + onnxruntime_pybind11_state.pyd
hiddenimports += collect_submodules('chromadb')
hiddenimports += ['onnxruntime', 'tokenizers', 'posthog', 'pypika']
```
plus `binaries=binaries` in `Analysis(...)` and
`upx_exclude=['onnxruntime*.dll', 'onnxruntime_pybind11_state.pyd', 'vcruntime140.dll']`
(UPX corrupting native DLLs is the classic failure mode here).

**Correction to the brief**: there is no bundled ONNX model file to add to `datas`. Chroma's default
EF downloads `onnx.tar.gz` (all-MiniLM-L6-v2) on first use into `~/.cache/chroma/onnx_models/`.
First run therefore requires network; this must be re-confirmed at apply time against the installed
package version. If the frozen exe raises `ModuleNotFoundError: X`, add `X` to `hiddenimports` and
rebuild — that iteration loop is expected work, not a failure of the design.

### What `sdd-verify` executes — `scripts/verify_frozen.ps1`

Isolation: set `$env:HOME` and `$env:USERPROFILE` to a fresh temp dir. Both `~/.mycontext/ctx_bd.db`
(`aicli/db/__init__.py:11`) and `CHROMA_PATH` key off `Path.home()`, so the real store is never
touched and the cold-cache path is genuinely exercised.

1. `py -m pip install -r requirements.txt`
2. `py -m PyInstaller ctx.spec --noconfirm` → assert `dist/MAGNA.exe` exists
3. temp-home run #1: `dist\MAGNA.exe embed-selftest` (cold: model download + upsert + query)
4. temp-home run #2: same command again (warm cache, no download)
5. `dist\MAGNA.exe status` — non-regression, the binary still boots normally

`embed-selftest` upserts 3 fixed docs into collection `selftest` (e.g. `auth: login y sesiones`,
`pagos: cobros con tarjeta`, `ui: componentes visuales`), queries `"arreglar el login"`, prints the
top-1 id and a `chromadb` version line, and exits `0`/`1`.

**Success = all five steps exit 0, run #3 and #4 both print `auth` as top-1, and run #4 emits no
download line.** Any `ModuleNotFoundError`, missing-DLL, or `.sql` migration error at step 3 is a
FAIL — this gate is blocking per `state.yaml.user_decisions.pyinstaller_verification`.

## Testing Strategy

| Layer | What | Approach |
|---|---|---|
| Unit | prefilter wiring, `--file` union, ≤20 no-op, exception fallback, write-site call args | `unittest.mock.patch` on `aicli.services.embeddings` / `chromadb` — mirrors `tests/test_prompt_caching.py` + `tests/test_structured_output.py` (fully mocked, sub-second) |
| Integration | real `PersistentClient(tmp_path)` + `_reconcile`/`query` API shapes | `@unittest.skipUnless(find_spec("chromadb"))`, patch `embeddings._default_ef` to a stub EF |
| Frozen | chromadb + onnxruntime inside `MAGNA.exe`, real default EF | `scripts/verify_frozen.ps1` (above) |

**Recommendation: mock for unit tests, but do NOT stop there.** The repo precedent is fully mocked
and fast, and that stays the default. Pure mocks cannot catch an API-shape mismatch, which is this
change's top risk (`chromadb` is not installed anywhere yet and its signatures were verified from
docs, not from a live package). The `skipUnless` integration tier costs nothing when the dep is
absent, stays fast when present (stub EF ⇒ no 80 MB download), and is the only cheap check that the
`upsert`/`get`/`query`/`include` contracts are real.

**Existing-test note**: `test_prompt_caching.py:118` (`system` byte-identical across different
`task_desc`) uses a 1-module fixture, so it stays green on the `len<=N` no-op path. The amended
`ai-prompt-caching` scenario needs a *new* >20-module test asserting the system block now legitimately
varies with `task_desc`.

## Threat Matrix

N/A — no routing, shell, subprocess, VCS/PR automation, executable-file classification, or
process-integration boundary in the product change. Two genuine non-matrix boundaries are recorded
instead: (1) new outbound network egress on first embed (ONNX model download) — expected, documented,
offline-degrading via the existing fallback; (2) Chroma's PostHog telemetry, explicitly disabled via
`Settings(anonymized_telemetry=False)`.

## Migration / Rollout

No schema migration. No new SQLite column. Pre-existing projects self-heal on the first `ctx task`
via `_reconcile`.

**Rollback — confirmed against this design.** `git revert` + drop the two `requirements.txt` lines.
`ctx_bd.db` is never written by this change, so there is nothing to undo. Two orphan dirs remain,
both outside every repository and both fully regenerable: `~/.mycontext/chroma/` (as the proposal
said) and — the proposal missed this — `~/.cache/chroma/onnx_models/` (~80 MB model cache, shared
with any other Chroma install). Manual cleanup:
`Remove-Item -Recurse -Force ~\.mycontext\chroma` (and optionally `~\.cache\chroma`). Re-applying
later rebuilds the store automatically: `_reconcile` sees an empty collection and upserts every
loaded module.

## Line Budget

| Area | Est. lines |
|---|---|
| `embeddings.py` | 85 |
| `embed_selftest.py` + `main.py` | 27 |
| `task.py` / `init.py` / `file_cmd.py` / `sync.py` | 25 |
| `requirements.txt` / `ctx.spec` | 16 |
| `scripts/verify_frozen.ps1` | 40 |
| `tests/test_module_prefilter.py` | 130 |
| **Code + config + tests** | **~323 (±40)** |
| OpenSpec artifacts (spec delta, design, tasks) | ~290 |

`400-line budget risk: Medium`. Code+tests **holds under 400** (~323, upper bound ~363), close to the
proposal's 300-380 estimate. It breaks 400 only if `sdd-tasks` counts the OpenSpec markdown toward the
reviewer budget (~613 total). Two shed-able items if the count lands over: drop
`scripts/verify_frozen.ps1` and run its 5 commands manually (−40, gate strength unchanged), and/or
trim the integration tier (−30). `ask-on-risk` should trigger a conversation only on the
artifacts-counted reading.

## Open Questions

- [ ] Skipping the `init._update_project` upsert deviates from approved proposal scope — confirm or override.
- [ ] `chromadb` pin unverified on Windows/py3.11; exact `datas`/`hiddenimports` must be re-checked at apply time against the installed package.
- [ ] Orphan Chroma docs from deleted projects/modules — tolerated in v1 (unknown ids dropped on map-back), no purge command.
