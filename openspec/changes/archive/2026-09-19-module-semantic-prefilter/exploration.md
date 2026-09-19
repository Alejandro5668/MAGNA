# Exploration: Chroma semantic prefilter for `_detect_relevant_modules`

## Current State

`aicli/commands/task.py:37-102` — `_detect_relevant_modules` builds `listing` (lines 40-48) by iterating **every** `Module` in the project-scoped `modules` list loaded at `task.py:169` (`select(Module).where(Module.project_id == project.id).order_by(Module.id)`), embeds it in a cached `system` block (change 1), and forces structured tool output via `MODULE_SELECTION_TOOL`/`tool_choice` (change 2). Confirmed byte-for-byte consistent with the archived `prompt-caching` and `structured-tool-output` designs — no drift. The prefilter this change adds must trim `modules` to top-N **before** line 40's loop runs.

`Module` model (`aicli/db/models.py:24-34`, verified): `id, project_id, name, description, file_path, content_path, created_at, last_updated_at, category, domain`. `id` is the natural, stable Chroma document id — no new SQLite column is strictly required. An additive-migration system already exists (`aicli/db/migrations.py`, `aicli/db/__init__.py:31-57`, `MIGRATIONS`/`SCHEMA_VERSION`, auto-backup) if `sdd-design` decides a tracking column is needed anyway.

## Affected Areas

- `aicli/commands/task.py:37-48,168-193` — prefilter insertion point + existing fallback/file-pin logic that must survive unchanged.
- `aicli/db/models.py:24-34` — `Module` fields; `id` reused as Chroma doc id.
- `aicli/commands/init.py:120-151` (`_save_modules`, new-project path) and `:226-268` (`_update_project`, re-run path) — upsert call sites.
- `aicli/commands/file_cmd.py:17-49` (`_save_zone_modules`) — same shape as `init.py`.
- `aicli/commands/sync.py:221-241` — inline upsert inside `_sync_impl` (not a named helper — different call shape than the other two).
- `aicli/services/indexer.py:26-30` (`MAX_TREE_ENTRIES=300` etc.) — MAGNA's existing scale anchor; confirms top 15-20 as a proportionate prefilter N.
- `main.py:8-9` — `~/.mycontext/` convention; `~/.mycontext/chroma/` is unclaimed, no conflict.
- `requirements.txt` (38 lines, verified `chromadb` absent) and `ctx.spec` (PyInstaller — no onnxruntime/chromadb hooks yet).

## Chroma API — verified against current docs.trychroma.com

- `chromadb.PersistentClient(path=...)` — embedded/local, no server. (Direct fetch of the persistent-client doc page 404'd this session — likely a moved URL slug, not a deprecation signal; corroborated via Cookbook/Manage-Collections pages. Re-verify the exact page in `sdd-design`.)
- `client.get_or_create_collection(name=..., embedding_function=...)` — confirmed current. **Constraint**: the same embedding function must be supplied consistently every time a given collection name is opened.
- `collection.upsert(ids=[...], documents=[...], metadatas=[...])` — confirmed current, add-or-update semantics.
- `collection.query(query_texts=[...], n_results=N, include=[...])` — confirmed current; embeds query text internally via the collection's embedding function.
- `chromadb.utils.embedding_functions.DefaultEmbeddingFunction` — confirmed still at that exact import path, current docs state it "runs locally" (all-MiniLM-L6-v2). Not renamed/deprecated.

## New discovery (not in original brief)

Chroma enables **anonymized telemetry by default** (PostHog-backed, `ANONYMIZED_TELEMETRY`). Recommend `sdd-design` explicitly disable it (`Settings(anonymized_telemetry=False)`) — small hardening detail, not a re-litigation of the embedding-source decision. Also investigated GitHub issue #5848 (claims `DefaultEmbeddingFunction` sends data to OpenAI) — **could not corroborate**; contradicts current official docs and has no visible maintainer resolution. Flagged as an unconfirmed residual item for `sdd-apply`/`sdd-verify` smoke-testing, not a blocker.

## Approaches

Not applicable in the usual sense — the embedding approach itself is pre-decided and out of scope for re-evaluation. The only real forks are scoped as open questions below, for `sdd-design` to resolve.

## Recommendation

Proceed to `sdd-propose` with: new `aicli/services/embeddings.py` (Chroma client/collection/upsert/query helpers), a prefilter step in `_detect_relevant_modules`, upsert calls added at the 3 verified call sites, `chromadb` added to `requirements.txt`, and `ctx.spec` updated with chromadb/onnxruntime PyInstaller data/hidden-imports.

## Risks

- **Backfill for pre-existing projects** (real open decision): first `ctx task` after upgrade finds an empty/missing Chroma collection. Recommend lazy backfill (embed all currently-loaded modules once, self-healing) over requiring manual `ctx init` re-run, consistent with MAGNA's existing `module_needs_update` auto-staleness philosophy — but this is a decision for `sdd-design`, not settled here.
- **Embedding-text composition** undecided: `description` alone (cheap) vs. description + doc snippet (richer, costlier I/O on every upsert).
- **PyInstaller/onnxruntime friction**: real, previously-accepted cost; `ctx.spec` needs new `datas`/`hiddenimports` entries for chromadb's bundled ONNX model + onnxruntime native binaries — untested in this repo since the dependency isn't installed yet.
- **`chromadb` not yet installed** anywhere in this environment or `requirements.txt` — first introduction of this dependency; `sdd-tasks` should size dependency/pin/Windows-compatibility verification as real work.
- Two WebFetch 404s (persistent-client page, add-and-update-data page) mean the Chroma API was cross-verified via secondary current docs pages + WebSearch rather than one canonical page — recommend a final signature re-check in `sdd-design` once `chromadb` is actually installed locally.

## Ready for Proposal

Yes.
