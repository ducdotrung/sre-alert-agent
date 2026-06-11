# Self-Improvement Agent

## Purpose

The self-improvement workflow analyzes manual review history and proposes changes to rules, prompts, or operating thresholds. It is designed as a read-only recommendation layer: proposals are generated and reviewed by a human, never auto-applied.

## Current Shape

- collector: gathers review outcomes and queue history
- analyzer: looks for recurring patterns
- proposer: generates one JSON file per proposal plus a `latest.json` manifest
- decisions: accept, reject, defer, or mark proposals as applied
- patcher: generates a unified diff artifact for accepted proposals
- measurement: measures before/after manual-review volume for applied proposals
- review CLI: `scripts/review_queue.py proposals ...`
- review web UI: `/improvements` tab in `scripts/review_web.py`

Relevant code:

- [../alert_agent/improvement/collector.py](../alert_agent/improvement/collector.py)
- [../alert_agent/improvement/analyzer.py](../alert_agent/improvement/analyzer.py)
- [../alert_agent/improvement/proposer.py](../alert_agent/improvement/proposer.py)
- [../alert_agent/improvement/storage.py](../alert_agent/improvement/storage.py)
- [../alert_agent/improvement/decisions.py](../alert_agent/improvement/decisions.py)
- [../alert_agent/improvement/patcher.py](../alert_agent/improvement/patcher.py)
- [../alert_agent/improvement/measurement.py](../alert_agent/improvement/measurement.py)
- [../alert_agent/improvement/review_state.py](../alert_agent/improvement/review_state.py)
- [../alert_agent/commands/run_self_improve.py](../alert_agent/commands/run_self_improve.py)

## Run It

```bash
python3 -m alert_agent.commands.run_self_improve --dry-run --force
```

Output is written under `output/improvement/`.

## Inputs

The workflow depends on:

- manual review audit history
- pending, approved, rejected, and ignored queue files
- the configured AI provider if AI summarization is enabled

## Proposal Lifecycle

Each proposal is stored as an individual JSON file under `output/improvement/proposals/<id>.json`.

Status transitions: `proposed` → `accepted` / `rejected` / `deferred` → `applied`.

```bash
# List proposals
python3 scripts/review_queue.py proposals list

# Accept a proposal
python3 scripts/review_queue.py proposals accept <id> --reviewer your-name --note "looks good"

# Reject a proposal
python3 scripts/review_queue.py proposals reject <id> --reviewer your-name --note "false positive"

# Generate a patch for an accepted proposal
python3 scripts/review_queue.py proposals patch <id>

# Mark as applied after you git-apply the patch
python3 scripts/review_queue.py proposals apply <id> --commit-sha <sha>
```

The same actions are available via the `/improvements` tab in the web UI.

## Guardrails

- proposals are generated, not auto-applied
- patch files are unified diffs written to `output/improvement/patches/`; a human runs `git apply` themselves
- manual review outcomes remain the source signal for tuning
- applied proposals are suppressed in future self-improve runs unless the signal regresses
