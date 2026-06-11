# Plan: Next Improvements

Last updated: 2026-06-11

This plan covers two workstreams scoped for an implementation. 
The `pi` CLI dependency is intentionally kept for now and is **out of scope**.

---

## Workstream A: Close the Self-Improvement Loop

### Why

Today the self-improvement pipeline only writes proposals to
`output/improvement/proposals/proposals-<ts>.json` and surfaces them read-only at
`/improvements` in the web UI. There is no accept/reject workflow, no record of
reviewer decisions, no way to apply an accepted proposal, and no measurement of
whether applied proposals reduced noise. Without these, manual review work does
not produce durable improvements.

Source of truth for current state:
- `alert_agent/improvement/{collector,analyzer,proposer}.py`
- `alert_agent/commands/run_self_improve.py`
- `scripts/review_web.py:571-1100` (proposal listing only, no actions)
- `repo-memory/workstreams/self-improvement.md`

### Deliverables (ship in this order)

#### A1. Proposal storage + lifecycle status

Goal: each proposal has an addressable identity that survives across runs and a
status field that can transition.

- Switch proposal storage from "one bundle file per run" to one file per
  proposal under `output/improvement/proposals/<proposal_id>.json`.
- Keep `latest.json` as a manifest (`{"generated_at": ..., "proposal_ids":
  [...]}`) so the UI still has a fast index.
- Status values: `proposed`, `accepted`, `rejected`, `deferred`, `applied`,
  `superseded`. New proposals start at `proposed`. When a new run regenerates a
  pattern that already has an open proposal at the same `(kind, source, project,
  classification, signature)`, mark the old one `superseded` and link it
  via `superseded_by`. Do not overwrite reviewer decisions.
- Add fields: `decision: {status, reviewer, note, timestamp}`,
  `applied: {timestamp, target_file, change_summary}` (nullable).
- Update `alert_agent/improvement/proposer.py:152` (`write_proposal_bundle`) and
  `alert_agent/commands/run_self_improve.py` to write per-proposal files plus
  the manifest. Keep backward read for any `proposals-*.json` already on disk.

#### A2. CLI + web actions to record decisions

Goal: a reviewer can accept / reject / defer a proposal with a note.

- Add `scripts/review_queue.py proposals {list,show,accept,reject,defer}`. Mirror
  the existing review_queue command surface. Reuse `argparse` patterns from the
  `approve/reject/ignore` actions.
- Add per-proposal action buttons on `/improvements` in
  `scripts/review_web.py`. Reuse the POST-action pattern from `record_action`
  in `alert_agent/core/manual_review.py`.
- Add `alert_agent/improvement/decisions.py` with a `record_proposal_decision`
  function that:
  - loads the proposal file
  - writes the new `decision` block
  - flips status (`accepted`, `rejected`, `deferred`)
  - appends one line to `output/metrics/proposal_decisions.jsonl`
- Tests: extend `tests/test_self_improve.py` with end-to-end
  "generate → accept → status persists across reload" and
  "regenerate while accepted → keeps status, marks new pattern as duplicate".

#### A3. Patch generation for accepted proposals

Goal: an accepted proposal becomes a concrete diff a human can git-apply.

- Add `alert_agent/improvement/patcher.py` with one function per `kind`:
  - `ignore_rule`: build a JSON patch for `config/ignore_rules.json` (insert a
    new rule object using `suggested_change.rule_hint`; deduplicate by `id`).
  - `classification_rule`: build a YAML patch for
    `config/classification_rules.yaml` (add keyword to the target class).
  - `priority_threshold`: build a YAML patch for
    `config/priority_thresholds.yaml` (lower `count`/`users` for the class
    until proposal can be hand-tuned). Keep the suggested change conservative
    (e.g. ±20% on the relevant threshold).
  - `prompt_improvement`: emit a markdown diff against
    `prompts/review_decision.md` or `prompts/triage_reclassify.md`. Lean on
    AI: pass the existing prompt + reviewer notes to `PiAIClient.query()` and
    ask for a unified diff. Keep this AI-optional with a templated fallback
    that just appends an "Examples reviewers rejected" section.
- Output as a unified diff written to
  `output/improvement/patches/<proposal_id>.patch`. Do not modify the config or
  prompt files — humans run `git apply` themselves.
- Add `scripts/review_queue.py proposals patch <id>` to (re)generate the patch
  on demand and print the path.
- Tests: snapshot tests on each patch generator with a fixture proposal.

#### A4. Apply workflow + supersession

Goal: the system distinguishes "accepted" from "applied" so impact can be
measured.

- Add a manual `applied` action: `scripts/review_queue.py proposals apply <id>
  --commit-sha <sha>`. This records `applied: {...}` on the proposal but does
  not touch any config file directly. The reviewer is responsible for the git
  commit; the action just bookkeeps "this proposal has shipped".
- On the next `run_self_improve.py` run, treat `applied` proposals as
  baseline: do not regenerate their pattern unless the underlying signal is
  strong enough that they are demonstrably failing (see A5).

#### A5. Impact measurement

Goal: prove the loop works.

- Add `alert_agent/improvement/measurement.py` with one function:
  `measure_applied_proposal_effect(proposal, audit_events, window_days=14)`.
- For each `applied` proposal, compute:
  - count of pending/rejected/ignored cases matching the proposal pattern in
    the `window_days` *before* `applied.timestamp`
  - same count *after*
  - delta and percent reduction
- Surface this on `/improvements` as a small table at the top: applied
  proposals, "before" volume, "after" volume, status pill (✅ reduced /
  ⚠️ no change / ❌ regressed).
- This is read-only; it does not auto-revert. If a proposal regressed, it
  should appear in the next run as a new `prompt_improvement` candidate
  with a higher confidence boost.

### Out of scope for this workstream

- Auto-applying proposals to config files
- Cross-source proposal merging (Sentry-only is fine)
- Proposal voting / multiple reviewers (single reviewer note is enough)

### Acceptance checklist

- [ ] Per-proposal files exist; reviewing one survives a re-run
- [ ] `proposals accept` and `proposals reject` CLIs + web buttons work
- [ ] Accepted proposal produces a `.patch` that `git apply --check` passes
- [ ] Applied proposal shows up in the `/improvements` impact table after
      14 days of fresh data (or with simulated audit events in tests)
- [ ] `tests/test_self_improve.py` covers the new flow

---

## Workstream B: Consolidate Dual Config Surface

### Why

`config/agent_config.yaml` currently carries two parallel definitions for the
same stages:

- canonical: `pipeline.{triage,review,recommendation}` plus
  `sources.sentry`, `policy_packs.sentry-default`
- legacy: `triage_agent`, `review_agent`, `recommendation_agent`, `sentry`

Three concrete consequences:

1. `alert_agent/core/config_loader.py:236` (`load_pipeline_stage_config`) takes
   a `legacy_section` fallback and `:280` (`load_policy_pack`) has a
   sentry-only legacy path.
2. Sender alone uses `load_agent_config('sender', ...)` while triage/review/
   recommendation use `load_pipeline_stage_config(...)`. The config surface
   is inconsistent across stages.
3. Adding any new source plugin (Grafana etc.) on top of this doubles the
   maintenance cost.

### Deliverables (ship in this order)

#### B1. Make `pipeline.*` the only stage section

- Move `sender` settings into `pipeline.sender` in `config/agent_config.yaml`.
  Keep the same keys (`teams_webhook_url`, `timeout`, `dry_run`,
  `max_last_seen_age_hours`).
- Update `alert_agent/pipeline/sender.py:150` to use
  `load_pipeline_stage_config('sender', config_file)` instead of
  `load_agent_config('sender', ...)`.
- Delete the `triage_agent`, `review_agent`, `recommendation_agent`, `sender`
  legacy sections from `config/agent_config.yaml`.
- Delete the legacy `sentry` block (the canonical version is
  `sources.sentry.config`).

#### B2. Drop legacy fallbacks in the loader

- Remove the `legacy_section` parameter from
  `alert_agent/core/config_loader.py:load_pipeline_stage_config`.
- Update all three callers (`alert_agent/pipeline/triage.py:327`,
  `review.py:131`, `recommendation.py:182`) to drop the
  `legacy_section=...` argument.
- Remove the sentry legacy branch from
  `alert_agent/core/config_loader.py:load_policy_pack` (the block matching
  `pack_name in {"sentry", "sentry-default"}`).
- Remove the legacy fallback in `load_source_config` (the `if source_name in
  full_config:` branch). Sources must be defined under `sources.*`.

#### B3. Update tests, docs, examples

- `tests/test_config_loader.py`: drop any test that exercises the legacy
  branches; add tests asserting that an unknown stage / source / policy pack
  raises `KeyError` with a clear message.
- `AGENTS.md`: rewrite the "Configuration Files" section to describe only
  `pipeline.*`, `sources.*`, and `policy_packs.*`. Drop references to
  `triage_agent`/`review_agent`/etc.
- `docs/ARCHITECTURE.md`: nothing to change structurally; verify wording.
- `.env.example` and `config/agent_config.yaml`: update inline comments to
  match the consolidated layout.

#### B4. Sanity pass across the codebase

- `grep -rn "triage_agent\|review_agent\|recommendation_agent" .` after the
  cleanup. The only matches that should remain are inside
  `agent_name=` strings passed to `PiAIClient` — those are usage-ledger labels,
  not config keys, and stay.
- `grep -rn "load_agent_config" .` — if anything other than the monitor / queue
  / daily-summary / self-improve commands still uses it, migrate to
  `load_pipeline_stage_config` or a stage-specific loader as appropriate.

### Out of scope for this workstream

- Renaming any non-config code (no `triage_agent` → `triage` rename in
  metrics labels)
- Schema validation for the YAML (nice-to-have; do separately)
- Adding a second source plugin (Grafana). That is the *next* workstream
  after this one, and explicitly easier once B is done.

### Acceptance checklist

- [ ] `config/agent_config.yaml` has no `triage_agent` / `review_agent` /
      `recommendation_agent` / top-level `sender` / top-level `sentry` keys
- [ ] `load_pipeline_stage_config` no longer takes `legacy_section`
- [ ] `load_policy_pack` and `load_source_config` no longer have legacy
      branches
- [ ] All four pipeline stages run end-to-end against a real `.env` (use
      `python3 -m alert_agent.pipeline.triage --dry-run` etc., or
      `python3 scripts/run_pipeline.py --source sentry --triage-dry-run
      --recommendation-dry-run --sender-dry-run`)
- [ ] All tests under `tests/` still pass

---

## Notes for the implementing agent

- Prefer config and prompt changes before Python logic changes.
- Workstream A and Workstream B are independent — pick one and finish it
  before starting the other. Do not interleave.
- Update `repo-memory/current-state.md` and the relevant
  `repo-memory/workstreams/*.md` file when you finish a deliverable.
- Add a dated handoff note under `repo-memory/handoffs/` at the end of each
  session.
- Keep diffs small. If a deliverable feels like it needs more than ~400 lines
  of new code, stop and write a sub-plan first.
