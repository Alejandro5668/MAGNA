# Proposal: Semantic module prefilter (Chroma)

## Intent

`_detect_relevant_modules` puts **every** documented module into the cached system
prompt. At 100+ modules the listing dominates the prompt, cost grows linearly with
project size, and selection quality drops as the model scans irrelevant blurbs.
Add a local semantic prefilter so only the top-N candidates reach the prompt.

## Scope

### In Scope
- `aicli/services/embeddings.py`: `PersistentClient(~/.mycontext/chroma/)`,
  `Settings(anonymized_telemetry=False)`, `DefaultEmbeddingFunction`, one collection
  per project named `project_{project_id}`; `upsert_modules` / `query_modules` /
  `reconcile` helpers. `Module.id` is the Chroma document id (no new SQLite column).
- Upserts co-located with each existing SQLite `Module` write: `init.py`
  (`_save_modules`, `_update_project`), `file_cmd.py` (`_save_zone_modules`),
  `sync.py` (`_sync_impl`).
- Prefilter inside `_detect_relevant_modules`, before the listing loop. `N=20`.
- `chromadb` in `requirements.txt`; `ctx.spec` `datas`/`hiddenimports` for
  chromadb + onnxruntime (real, untested packaging work).

### Out of Scope
- Replacing Claude's selection — the prefilter narrows candidates, the model still chooses.
- Re-opening the embedding source (pre-decided, `state.yaml`).
- A `ctx` command to purge/rebuild the vector store; consolidating Anthropic clients.

## Capabilities

### New Capabilities
- `ai-module-prefilter`: top-N semantic narrowing, lazy backfill/self-heal, and
  degradation to the full list.

### Modified Capabilities
- `ai-prompt-caching`: its scenario *"Task description never affects the cached
  block"* becomes false — the listing is now task-dependent. Delta spec required.

## Approach

| Decision | Choice | Rationale |
|---|---|---|
| Backfill | Lazy reconcile at query time: diff collection ids against loaded `Module.id`s, upsert the missing ones, then query | Matches MAGNA's `module_needs_update` auto-staleness; no manual `ctx init`; also self-heals a failed upsert, not just the upgrade case |
| Embed text | `f"{name}: {description}"` — description only, no doc snippet | Descriptions are already AI-generated to be descriptive; zero extra file I/O per upsert; avoids re-embedding when only `content_path` changes (sync's update branch). Widening later is one function |
| Caching | Keep the listing in the cached `system` block | The 5-min ephemeral TTL rarely spans two `ctx task` runs, so the lost cross-task read is largely theoretical while the token cut is certain. Alternative (move listing to the user turn) is an open question below |
| `--file` | Prefilter builds a new local list, never mutates the caller's; the `task.py:190-193` pin still resolves against the full `modules`. Additionally union the `file`-matched module into the top-N | Keeps the pin as a guaranteed escape hatch and lets the model see its description |
| Degradation | No-op when `len(modules) <= N`; unknown ids from the collection dropped when mapping back to `Module`; any exception → full unfiltered list | Prefilter can never reduce correctness, only prompt size |

## Affected Areas

| Area | Impact | Description |
|---|---|---|
| `aicli/services/embeddings.py` | New | Chroma client, collection, upsert/query/reconcile |
| `aicli/commands/task.py:37-48` | Modified | Prefilter before the listing loop |
| `aicli/commands/init.py:120-151,226-268` | Modified | Upsert after `Module` writes |
| `aicli/commands/file_cmd.py:17-49` | Modified | Upsert after `Module` writes |
| `aicli/commands/sync.py:221-241` | Modified | Upsert on the new-module branch |
| `requirements.txt`, `ctx.spec` | Modified | `chromadb` dependency + PyInstaller bundling |

## Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| PyInstaller can't bundle onnxruntime/chromadb natives | High | Sized as real work in `sdd-tasks`; frozen-binary smoke test is a gate, not a nicety |
| Cross-task cache reads stop hitting | High | Accepted (see Approach); TTL makes the loss mostly theoretical; net token count still falls |
| Prefilter drops the one module that mattered | Med | `N=20` vs `MAX_TREE_ENTRIES=300`; `--file` union; full-list fallback; `ctx task` output already shows the chosen modules |
| SQLite/Chroma drift | Med | Upserts co-located with each SQLite write + reconcile-on-query |
| `chromadb` never installed here; Windows/py3.11 compat unverified | Med | Dependency install/pin verification is an explicit task |
| Description-only embeddings too weak for `sync.py` modules (description = first heading line) | Med | Measurable in verify; widening the embed text is a one-function change |

## Rollback Plan

Pure additive: one new file, one new dependency, new upsert calls, and a prefilter
that already falls back to today's behavior on any failure. Rollback = `git revert`
+ drop `chromadb` from `requirements.txt`; no DB migration, no on-disk format change
inside any repo. `~/.mycontext/chroma/` is left orphaned but harmless — it is outside
every repository, self-contained, and fully regenerable. No cleanup command in v1;
`sdd-design` should document the manual `rm -r ~/.mycontext/chroma` and confirm that
re-applying later rebuilds it through the lazy-reconcile path.

## Dependencies

- `chromadb` (pulls `onnxruntime`) — first introduction to this project.
- Lands on top of `prompt-caching` and `structured-tool-output` (both archived).

## Success Criteria

- [ ] A 100+ module project sends a listing of at most `N` modules; token count for
      `detect_modules` falls measurably in the log line at `task.py:93-99`.
- [ ] `system`-array shape, `cache_control`, `thinking`, `tools` and forced
      `tool_choice` are byte-identical to the post-change-2 request.
- [ ] A project indexed before this change self-heals on its first `ctx task`, with
      no manual re-index.
- [ ] Missing/empty/corrupt Chroma store still produces a correct module selection.
- [ ] `--file` target is always present in the final `relevant` list.
- [ ] The frozen `ctx.exe` runs `ctx task` end to end.

## Open Questions

- [ ] **Cache tradeoff** (needs user sign-off): keep the volatile listing inside the
      cached block (chosen), or move it to the user turn and cache only `PROYECTO.md`?
      The latter preserves the existing caching invariant literally but changes what
      change 1 deliberately cached.
- [ ] Deleting a project/module leaves orphan Chroma documents — tolerated in v1
      (query results are id-mapped back to `Module`, unknowns dropped).
