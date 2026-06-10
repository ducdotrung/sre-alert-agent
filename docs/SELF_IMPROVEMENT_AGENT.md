# Self-Improvement Agent

## Purpose

The self-improvement workflow analyzes manual review history and proposes changes to rules, prompts, or operating thresholds. It is designed as a read-only recommendation layer first, not an automatic config mutator.

## Current Shape

- collector: gathers review outcomes and queue history
- analyzer: looks for recurring patterns
- proposer: builds proposal bundles for human review
- UI support: proposals can be surfaced in the review web UI

Relevant code:

- [../alert_agent/improvement/collector.py](../alert_agent/improvement/collector.py)
- [../alert_agent/improvement/analyzer.py](../alert_agent/improvement/analyzer.py)
- [../alert_agent/improvement/proposer.py](../alert_agent/improvement/proposer.py)
- [../scripts/run_self_improve.py](../scripts/run_self_improve.py)

## Run It

```bash
python3 scripts/run_self_improve.py --dry-run --force
```

Output is written under `output/improvement/`.

## Inputs

The workflow depends on:

- manual review audit history
- pending, approved, rejected, and ignored queue files
- the configured AI provider if AI summarization is enabled

## Guardrails

- proposals are generated, not auto-applied
- config changes stay in Git review
- manual review outcomes remain the source signal for tuning

## Next Logical Improvements

- accept/reject lifecycle for proposals
- proposal-to-patch generation
- tighter links between review outcomes and rule updates
