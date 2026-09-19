# Tasks: Semantic module prefilter (Chroma)

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | ~323 (±40), code+tests only |
| 400-line budget risk | Low |
| Chained PRs recommended | No |
| Suggested split | Single PR |
| Delivery strategy | single-pr |
| Chain strategy | pending |

Decision needed before apply: No
Chained PRs recommended: No
Chain strategy: pending
400-line budget risk: Low

Note: design.md's own estimate is ~323±40 code+tests, ~613 if OpenSpec markdown is added. Per the review-budget convention (Section E, sdd-phase-common.md), the 400-line guard counts authored code/test diff, not already-reviewed planning docs from prior phases. On that basis the estimate is confirmed Low, not Medium — no user conversation needed.

### Suggested Work Units

| Unit | Goal | Likely PR | Focused test command | Runtime harness | Rollback boundary |
|------|------|-----------|----------------------|-----------------|-------------------|
| 1 | Full change (dep + embeddings.py + wiring + packaging + verify) | PR 1 | `.venv\Scripts\python.exe -m pytest tests/test_module_prefilter.py tests/test_prompt_caching.py tests/test_structured_output.py` | `scripts\verify_frozen.ps1` (real `MAGNA.exe` build+run) | `git revert`; drop 2 `requirements.txt` lines; delete `~\.mycontext\chroma` |

## Phase 0: Dependency

- [x] 0.1 `pip install chromadb`; pin exact resolved `chromadb`/`onnxruntime` versions in `requirements.txt`.
- [x] 0.2 `python -c "import chromadb"` in `.venv` on this repo's Python 3.11 — confirm import succeeds before any other task; if incompatible, stop and report.
  - Deviation: repo `.venv` is actually Python 3.14.0 (not 3.11 as briefed — no 3.11 interpreter exists on this machine, only 3.12/3.14). `pip install chromadb` resolved cp314 wheels: `chromadb==1.5.9`, `onnxruntime==1.30.0`. `import chromadb` succeeds cleanly. Gate PASSES on the Python this repo actually runs.

## Phase 1: `aicli/services/embeddings.py` (TDD)

- [x] 1.1 RED — `tests/test_module_prefilter.py`: telemetry disabled (`Settings(anonymized_telemetry=False)`), `get_collection` per-project naming.
- [x] 1.2 RED — `_text()`/upsert: document is exactly `f"{name}: {description}"`; no `content_path`/`file_path` read.
- [x] 1.3 RED — `_reconcile`: missing id upserted; stale `metadatas["text"]` upserted; matching text skipped.
- [x] 1.4 RED — `query_modules`: ≤20 modules returns input unchanged (no Chroma call); >20 calls reconcile+query and maps ids back to `Module`; any exception returns full `modules` list, no raise.
- [x] 1.5 GREEN — implement `embeddings.py` per design's interface to pass 1.1–1.4 (mocked `chromadb`).
- [x] 1.6 Integration — `@unittest.skipUnless(find_spec("chromadb"))` test: real `PersistentClient(tmp_path)`, stubbed `_default_ef`, exercise real `upsert`/`get`/`query` shapes.

## Phase 2: `task.py` wiring + cache contract

- [x] 2.1 RED — `_detect_relevant_modules` calls `query_modules` before the listing loop; `--file` pin unioned into candidates without mutating caller's `modules`.
- [x] 2.2 GREEN — apply design's exact insertion at `task.py:37-48`.
- [x] 2.3 RED — new >20-module fixture: system block's module-listing legitimately differs across two different `task_desc` values.
- [x] 2.4 RED — same fixture: `PROYECTO.md` portion of `system` stays byte-identical across those two calls.
- [x] 2.5 Regression assertion — explicit test/comment confirming `tests/test_prompt_caching.py`'s existing ≤20-module fixture takes the no-op path (`query_modules` not invoked / Chroma untouched).

## Phase 3: Upsert call sites

- [x] 3.1 RED — mock `embeddings.upsert_modules`; assert `init._save_modules` (`init.py:120-151`) calls it post-`session.commit()` with `(id, name, description)` for touched rows.
- [x] 3.2 RED — same for `file_cmd._save_zone_modules` (`file_cmd.py:17-49`).
- [x] 3.3 RED — same for `sync._sync_impl` new-module branch (`sync.py:221-241`), one upsert after the loop.
- [x] 3.4 RED — same for `init._update_project` (`init.py:248-253`), single-row upsert post-commit (literal spec coverage; harmless no-op given unchanged name/description, self-healed by reconcile either way).
- [x] 3.5 GREEN — implement 3.1–3.4; rely on `upsert_modules`'s internal try/except (never raises) — no extra wrapping needed at call sites.

## Phase 4: PyInstaller packaging

- [x] 4.1 `aicli/commands/embed_selftest.py`: hidden diagnostic upserting 3 fixed docs into collection `selftest`, querying `"arreglar el login"`, printing top-1 id + `chromadb` version, exit 0/1.
- [x] 4.2 `main.py`: register `app.add_typer(embed_selftest.app, name="embed-selftest", hidden=True)`.
- [x] 4.3 `ctx.spec`: add `datas`/`copy_metadata`/`hiddenimports`/`binaries` for `chromadb`/`onnxruntime`/`tokenizers`; add `upx_exclude` per design.

## Phase 5: Frozen-exe verification (BLOCKING)

- [x] 5.1 `scripts/verify_frozen.ps1`: temp `HOME`/`USERPROFILE`, `pip install -r requirements.txt`, `pyinstaller ctx.spec --noconfirm`, assert `dist/MAGNA.exe` exists.
  - Deviation: uses `.venv\Scripts\python.exe` instead of the bare `py` launcher — the system `py` (3.14) has no PyInstaller installed; this repo's toolchain lives in `.venv`.
- [x] 5.2 Run `dist\MAGNA.exe embed-selftest` cold (network download) then warm; assert both exit 0, both print `auth` top-1, warm run has no download line.
  - CONFIRMED: cold run downloaded the real 79.3 MB ONNX model, printed `top-1: auth`, `chromadb version: 1.5.9`, `OK`, exit 0. Warm run (same temp HOME) printed the same, no `onnx.tar.gz` download line, exit 0.
- [x] 5.3 Run `dist\MAGNA.exe status`; assert non-regression boot.
  - CONFIRMED: exits 0, no import/native-library/DLL error (the actual scope of this requirement per spec.md's "Frozen Binary Packaging" wording).
- [x] 5.4 Execute `verify_frozen.ps1` for real and record pass/fail — this is the hard gate per `state.yaml.pyinstaller_verification: blocking`.
  - **RESULT: PASS.** `== verify_frozen: PASS - all 5 steps exited 0, cold+warm both top-1 auth, warm had no download line ==`
  - Two pre-existing bugs (unrelated to chromadb, not introduced by this change) were discovered and fixed with minimal ASCII-safe fallbacks to unblock this gate: `aicli/db/__init__.py:56` (`init_db` schema-bump print) and `aicli/tui/theme.py`'s `magna_warn` — both crashed the frozen exe with `UnicodeEncodeError` on a fresh non-UTF8 Windows console (Rich's legacy console writer ignores `PYTHONIOENCODING`). See apply-progress risks section for full detail — flagged for user review, not silently absorbed into "done."

## Phase 6: Full regression

- [x] 6.1 Run `tests/test_prompt_caching.py` and `tests/test_structured_output.py` unchanged; confirm all pass. — 58/58 passed (34 + 24 including new `test_module_prefilter.py`, run together).
- [x] 6.2 Run full `.venv\Scripts\python.exe -m pytest` suite; confirm no unrelated breakage. — 109 passed, 6 subtests passed (excluding pre-existing broken `tests/test_commands.py`, a non-pytest script with a module-level `sys.exit(1)`, confirmed broken before this change at the Phase-0 baseline check and untouched by this diff).
