# Proposal: Prompt caching for module detection (`ctx task`)

## Intent

`_detect_relevant_modules` (`aicli/commands/task.py:21-67`) rebuilds and resends, on **every** `ctx task` invocation, a block containing every `Module` row (name + description + file path + first 300 chars of doc) plus the full `PROYECTO.md`. On a large project this is the single biggest repeated input block MAGNA pays full price for. It is stable within a working session — exactly the shape Anthropic prompt caching exists for.

## Scope

### In Scope
- Restructure `_detect_relevant_modules`'s prompt so the stable block (module `listing` + `project_context`) becomes a cacheable **prefix**, moved into a `system` array with `cache_control: {"type": "ephemeral"}` (default 5-min TTL).
- Keep the variable parts (`task_desc`, `file_context`, JSON output instruction) in the `messages` user turn, after the cached prefix.
- Deterministic ordering of the module listing (the query at `task.py:134` has no `ORDER BY`) so repeat runs produce byte-identical prefixes.
- Preserve exactly: `model="claude-sonnet-5"`, `thinking={"type":"adaptive"}`, and the strict JSON parse at `task.py:64-66`.

### Out of Scope — explicitly excluded, not forgotten
| Site | Why excluded |
|---|---|
| `indexer.py:181-219` `_call_claude` + its 6 generators | Tiny fixed preamble (1-5 sentences) then per-call-unique content (file/zone/tree). No byte-identical block above threshold. |
| `indexer.py:302-349` `describe_image` | ~110-token fixed instruction + a different image each call. |
| `task.py:70-105` `_generate_task_brief` | Builds a *different* listing (filtered subset, one-liner, no PROYECTO.md); cannot share a prefix without re-architecture, and its missing `thinking` config would invalidate reuse anyway. |

Also deferred: consolidating the 4 `Anthropic()` instantiations, closing the retry/backoff gap, extended 1h TTL.

## Capabilities

### New Capabilities
- `ai-prompt-caching`: invariants for cacheable prefixes on Anthropic calls — prefix stability/determinism, output-format preservation, graceful no-op below threshold.

### Modified Capabilities
- None. (`jira-resume-context`, `ticket-history-store` unaffected.)

## Approach

Exploration Approach 1. `system=[{"type":"text","text":<stable block>,"cache_control":{"type":"ephemeral"}}]`; user message carries only task-variable text. `system` precedes `messages` in Anthropic's cache hierarchy, so this ordering is required — today the variable `task_desc` sits *before* the listing (`task.py:44-47`), which would defeat caching if left in place.

Below-threshold blocks make `cache_control` a silent no-op (no error) — small projects degrade to today's behavior automatically.

## Affected Areas

| Area | Impact | Description |
|---|---|---|
| `aicli/commands/task.py:21-67` | Modified | Prompt split into cached `system` + variable user turn |
| `aicli/commands/task.py:134` | Modified | Add deterministic `ORDER BY` for listing stability |

## Expected Outcome (honest framing)

This pays off **only across repeated `ctx task` runs on the same project within the TTL**. A single one-off run is a **net cost increase**: cache writes cost ~1.25x base input with no read to offset. Break-even is roughly the second invocation; from there reads cost ~10% of base input. Re-indexing (which rewrites `PROYECTO.md` or modules) invalidates the entry — correctly, but it resets the payback clock.

## Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Restructuring changes response framing → JSON parse breaks | Med | Keep the JSON instruction verbatim and in the user turn; verify parse on a real run |
| Block falls under the 1,024-token Sonnet minimum on small projects | Med | Silent no-op, not an error; `sdd-design` measures a live `usage.cache_creation_input_tokens` |
| Exact minimum-token threshold unverified (see below) | Med | `sdd-design` must confirm empirically before any spec states a number as fact |
| Non-deterministic module ordering silently kills hit rate | Med | Explicit `ORDER BY`; assert stability across two runs |
| Net cost increase for single-run users | High | Accepted and documented; not hidden |

### Threshold question — closed by scope, not by fetch

The exploration's Haiku 2,048-vs-4,096 discrepancy is **moot for this change**: the only target runs on `claude-sonnet-5`, and both exploration sources agree on **1,024 tokens** for the Sonnet family. This phase had no web-fetch tool available, so the number was not re-verified against live docs. `sdd-design` MUST verify empirically with one live call (inspect `usage.cache_creation_input_tokens` / `cache_read_input_tokens`) before writing any threshold into a spec.

## Rollback Plan

**Revert the diff — and that is genuinely complete.** Verified: no schema change, no migration, no new dependency, no config key, no on-disk artifact. Anthropic caches are server-side and expire on their own 5-minute TTL; reverting simply stops writing and reading them. Already-paid cache writes are sunk cost, harmless, and self-expiring. No cleanup step is required.

## Dependencies

- None. Uses the installed `anthropic` SDK; `cache_control` and `system` arrays are standard Messages API fields.

## Success Criteria

- [ ] `ctx task` returns the same module selection quality as before (JSON parse intact, no regression).
- [ ] A second `ctx task` run within the TTL on the same project reports non-zero `cache_read_input_tokens`.
- [ ] The measured cached-prefix token count is recorded in `sdd-design` against a real project DB.
- [ ] Changed lines stay within the 400-line review budget (single PR).

## Proposal question round (deferred — automatic execution mode)

Not asked; assumptions made instead. Flag for user review:
1. Is optimizing for the **repeated-invocation** workflow correct, or is one-shot `ctx task` the dominant usage? (Assumed: repeated. If wrong, this change is a net loss.)
2. Is the default 5-minute TTL sufficient, or do sessions span longer gaps warranting the 1h TTL at ~2x write cost? (Assumed: 5 min.)
3. Is a cost-visibility surface (showing cache hit/miss in `ctx task` output) wanted now or deferred? (Assumed: deferred.)
