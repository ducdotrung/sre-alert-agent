# Triage Analysis

The analysis tool helps tune classification rules and prompts against a larger slice of historical Sentry data.

## Run

```bash
python3 scripts/analyze_sentry_corpus.py --days 14 --limit 3000
```

## What It Produces

Each run writes a timestamped folder under `output/analysis/` containing:

- fetched issue data
- current rule classifications
- class and priority summaries
- low-confidence or unknown buckets
- candidate keyword observations

## When To Use It

- after prompt changes
- after updating classification rules
- when too many issues land in `unknown`
- when specific issue types are repeatedly misclassified

## Follow-Up Workflow

1. inspect the analysis output
2. update `config/classification_rules.yaml` or prompt files
3. rerun `python3 agents/triage_agent.py --dry-run`
4. rerun corpus analysis to compare the result
