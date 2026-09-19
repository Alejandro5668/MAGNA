# Exploration: Anthropic prompt caching in MAGNA (change: prompt-caching)

## Current State

MAGNA makes Anthropic API calls from exactly 4 distinct call-construction sites (verified via grep for `anthropic.Anthropic(` and `.messages.create(`), all in `messages=[{"role":"user","content":...}]` form — none currently use a `system` array or any `cache_control` block:

1. `aicli/services/indexer.py:181-219` `_call_claude()` — shared helper (own `Anthropic()` client at L187, `.messages.create()` at L194) used by 6 functions, each building a unique one-shot prompt with a tiny (1-5 sentence) fixed instruction preamble immediately followed by large variable content (source file, diff, tree, samples):
   - `generate_module_content` L224 (Sonnet)
   - `generate_case_summary` L248 (Haiku)
   - `analyze_file_deep` L352 (Sonnet)
   - `document_zone` L437 (Sonnet)
   - `generate_project_md` L587 (Sonnet)
   - `document_architecture` L706 (Sonnet)
2. `aicli/services/indexer.py:302-349` `describe_image()` — own inline client (L319) + call (L321), multimodal (image + ~110-token fixed instruction text), bypasses `_call_claude` (no retry/backoff).
3. `aicli/commands/task.py:21-67` `_detect_relevant_modules()` — own inline client (L56) + call (L57), sets `thinking: {"type": "adaptive"}`, bypasses `_call_claude`.
4. `aicli/commands/task.py:70-105` `_generate_task_brief()` — own inline client (L99) + call (L100), bypasses `_call_claude`.

`MODEL_BY_OPERATION` (indexer.py:34-44) references a `"role"` entry ("generate_role_md — template rellenado") but no `generate_role_md` function exists anywhere in the codebase — dead/aspirational config entry, not a real call site.

`aicli/services/gemini.py` uses `google.generativeai` (genai) exclusively (L27,33,36,40,45,49,62,69,70) — confirmed a different SDK/provider, correctly out of scope for Anthropic prompt caching.

Every one of the 4 call sites instantiates its own `anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))` — no shared/reused client. Confirmed this is orthogonal to prompt caching: Anthropic caches server-side, keyed by exact content match tied to the API key/workspace, not by local SDK client object lifetime — reusing a client would not change cache hit/miss behavior. Consolidating the 4 instantiations is a legitimate but separate minor cleanup (also: 3 of 4 sites bypass `_call_claude`'s retry/backoff-on-rate-limit logic entirely today, an existing reliability gap independent of caching).

`PROYECTO.md` handling: `aicli/commands/task.py:143-147` reads `PROYECTO.md` directly in `_execute_task` and passes it as `project_context` into `_detect_relevant_modules`, where it is embedded in the prompt at task.py:39/45 — this IS sent to an Anthropic call. This is a SEPARATE read from `aicli/services/builder.py:26-39` (`build_context`), which re-reads `rol.md`, team `rules/*.md`, and `PROYECTO.md` purely to assemble `session_context.md` for the Claude Code subprocess handoff (confirmed out of scope — different consumer, no Anthropic call involved). `rol.md`/team rules are read ONLY in `build_context` — never sent to any Anthropic API call, so they are irrelevant to this change.

## Affected Areas

- `aicli/services/indexer.py` — `_call_claude()` (L181-219) and its 6 callers; `describe_image()` (L302-349)
- `aicli/commands/task.py` — `_detect_relevant_modules()` (L21-67), `_generate_task_brief()` (L70-105)
- `aicli/services/builder.py` — read-only reference point confirming PROYECTO.md/rol.md's OTHER (non-Anthropic) consumer; NOT modified by this change
- `aicli/services/gemini.py` — confirmed excluded (different SDK)

## The one clearly viable caching target

`_detect_relevant_modules` (task.py:21-67) is the single most expensive repeated context block: its `listing` (task.py:24-32) concatenates name + description + first-300-chars-of-doc for EVERY `Module` row in the project, plus the full `PROYECTO.md` content as `project_context`. For a large real project (~11,000 files) this plausibly reaches several thousand tokens — comfortably above any published per-model minimum cacheable prefix (see threshold caveat below) — and it is rebuilt and resent FULLY on every single `ctx task` invocation. Marking this block (module listing + PROYECTO.md) with `cache_control: {"type": "ephemeral"}` — most naturally by moving it into a `system` array — would let repeat `ctx task` runs on the same project within the cache TTL (5 min default, up to 1h extended at higher write cost) reuse it at ~10% of base input token price instead of paying full price every time.

Exact token sizes were NOT measured against a live large project DB in this exploration — flag as an assumption to validate empirically in `sdd-propose`/`sdd-design`, not a verified number.

## Why the other 3 call sites do NOT clearly benefit as currently structured

- `generate_case_summary` (Haiku, indexer.py:248): prompt = task + up to 5000 chars of diff (~1,250 tokens) + fixed JSON-instructions block (~300-350 tokens). Nothing is stable/repeated across calls (diff/task always differ) — not a caching candidate regardless of size or threshold.
- `_generate_task_brief` (Haiku, task.py:70): builds its OWN listing from the FILTERED `relevant` module subset, one-liner format (no content snippet, no PROYECTO.md) — textually and structurally DIFFERENT from `_detect_relevant_modules`'s listing, so the two calls within one `ctx task` execution do NOT share an identical cacheable prefix today. Its stable block is typically small and plausibly falls below even the lower published Haiku threshold for typical tasks. Sharing a cache entry with `_detect_relevant_modules` would require deliberate re-architecture (extract one common `system` segment used identically by both calls) — flagged as an option, not decided here — AND resolving that `_detect_relevant_modules` sets `thinking: {"type": "adaptive"}` while `_generate_task_brief` does not; per Anthropic's docs, a change in `thinking` config invalidates/breaks cache reuse between requests, so the two calls cannot share one cache entry while this mismatch exists.
- The 5 Sonnet-routed one-shot generators (`generate_module_content`, `analyze_file_deep`, `document_zone`, `generate_project_md`, `document_architecture`) and `describe_image`: each builds a prompt with a tiny fixed instruction preamble (~1-5 sentences, well under any published minimum) immediately followed by content that is UNIQUE per call (different file/zone/tree/image every time) — even where these run in a loop within one command, there is no byte-identical block large enough to cache, so none of these are viable caching candidates under the current prompt design.

## Threshold research (unresolved discrepancy — verify before finalizing scope)

Two independent lookups produced inconsistent numbers for Anthropic's minimum cacheable prefix length:
- WebSearch summary: Sonnet family ≈ 1,024 tokens; Haiku 4.5 ≈ 2,048 tokens.
- Direct docs fetch (platform.claude.com/docs/en/build-with-claude/prompt-caching): Sonnet 5/4.6/4.5 = 1,024 tokens; Haiku 4.5 = 4,096 tokens, Haiku 3.5 = 2,048 tokens — this fetch also surfaced model names ("Fable 5.1", "Mythos 5.1") that do not match any known Anthropic naming pattern, suggesting possible summarization drift in the fetch tool.

Below the threshold, `cache_control` is silently ignored (no error, `cache_creation_input_tokens` stays 0) per both sources — consistent on this point. Sonnet-family minimum (~1,024 tokens) is consistent across both sources and is the number that matters most, since the one viable target (`_detect_relevant_modules`) runs on `claude-sonnet-5`. The Haiku discrepancy matters less for scope because `_generate_task_brief` and `generate_case_summary` are already excluded on other grounds — but `sdd-propose`/`sdd-design` should verify the exact current number directly (live API test or current docs) before writing it into any spec as fact.

Also confirmed: max 4 explicit `cache_control` breakpoints per request; cache hierarchy order `tools → system → messages`; default TTL 5 minutes, extended TTL 1 hour at ~2x write cost; cache writes ~1.25x base input price, cache reads ~10% of base input price.

## Approaches

| Approach | Pros | Cons | Effort |
|----------|------|------|--------|
| 1. Cache only `_detect_relevant_modules`'s module-listing + PROYECTO.md via a `system` array with `cache_control: ephemeral` | Highest-confidence win; isolated (task.py only); no `thinking`-config conflict | Only pays off across repeated `ctx task` runs within TTL; single-run sessions see a net cost increase | Low |
| 2. Also restructure `_generate_task_brief` to share the same cached block | Doubles cache-read benefit per invocation | Requires unifying listing format + resolving `thinking` mismatch; regression risk to brief's conciseness/quality; unclear net win | Medium |
| 3. Consolidate all 4 call sites onto one shared client + `_call_claude`-style helper with built-in caching | Single place for caching logic; closes retry/backoff gap as side benefit | Scope creep beyond "prompt caching" into client/error-handling refactor; not requested | Medium-High |

## Recommendation

Approach 1: scope `sdd-propose` to ONLY `_detect_relevant_modules` (task.py:21-67). Leave `_generate_task_brief`, `generate_case_summary`, `describe_image`, and the 5 Sonnet one-shot generators unchanged — their prompts are either non-repeating or too small to benefit. Present approaches 2 and 3 as explicit, separately-scoped follow-ups rather than folding them into this change.

## Risks

- Per-model minimum cacheable token threshold not fully reconciled (Haiku 2,048 vs 4,096) — verify live before `sdd-design` states numbers as fact.
- Real token size of the target block not measured against a live large-project DB — validate empirically.
- Cache benefit is session-dependent: a single `ctx task` per session sees a net cost increase (write premium, no read).
- `_detect_relevant_modules` is strict-JSON-parsed (task.py:64-66) — any prompt restructuring must preserve output format.
- `thinking: adaptive` on `_detect_relevant_modules` blocks future cache-sharing with `_generate_task_brief` unless aligned.
- `MODEL_BY_OPERATION["role"]` references a nonexistent `generate_role_md` — pre-existing dead config, unrelated hygiene note.

## Ready for Proposal

Yes — scope is narrow and well-bounded (single call site: `_detect_relevant_modules` in `aicli/commands/task.py`). `sdd-propose` should explicitly exclude the other 3 call-construction sites and the 6 one-shot indexer.py generators, citing the reasons above, and flag the Haiku threshold number as needing live verification before `sdd-design`/`sdd-spec` state it as fact.

