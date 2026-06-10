# Repo Memory

This folder is the repo's working memory for interrupted sessions, handoffs, and active implementation state.

Use `docs/` for durable design, architecture, rollout plans, and Confluence-ready material.

Use `repo-memory/` for:

- what is implemented right now
- what changed recently
- what the next step is
- open questions, blockers, and decisions
- short handoff notes for the next session

Do not use this folder for long-form architecture docs or polished explanations that belong in `docs/`.

## Read Order

At the start of a coding session, read these files in this order:

1. `repo-memory/current-state.md`
2. relevant `repo-memory/workstreams/*.md`
3. latest file in `repo-memory/handoffs/`
4. linked source docs in `docs/` only if more background is needed

## Update Rules

Update repo memory whenever a session changes the implementation, plan, or understanding of what is next.

Minimum updates for a meaningful work session:

1. refresh `repo-memory/current-state.md` if overall status changed
2. update the relevant `repo-memory/workstreams/*.md`
3. add or append a dated note in `repo-memory/handoffs/`

## Writing Style

- keep entries short and factual
- link to code or docs instead of copying them
- record exact next actions, not vague intent
- separate `implemented` from `planned`
- if a roadmap doc is stale, note that here instead of rewriting history in the durable doc

## Folder Map

- `current-state.md`: top-level repo snapshot
- `workstreams/`: one file per active area
- `handoffs/`: dated session notes
- `decisions/`: short ADR-style notes when a decision matters later
- `templates/`: starter templates
- `_scratch/`: optional local-only notes; not meant for Git history
