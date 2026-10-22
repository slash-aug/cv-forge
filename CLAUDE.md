# cv-forge

Builds tailored, audited, ATS-checked LaTeX CVs and cover letters from one master YAML profile. Output is PDF only.

## Rules

- Facts come only from `data/profile/master.yaml`. Never invent metrics. When Felipe confirms a new fact in chat, record it in master in the same turn.
- Never commit `data/`. It holds personal data and is git-ignored.
- The human always clicks submit. Never automate job applications.
- No AI attribution in commits or PRs (no Co-Authored-By, no "Generated with" lines).
- No em dashes in public text (docs, code, commit messages).
- Stage files by name; never `git add -A`.

## Commands

Venv: `.venv/bin/cvforge`

- `cvforge validate`: check the profile and selection files
- `cvforge audit`: verify every claim traces to master
- `cvforge build`: render the PDF and run ATS checks
- `cvforge master-cv`: build the full master CV
- `cvforge guard staged` / `cvforge guard msg`: privacy checks used by the git hooks

## Tests

- `pytest -q` runs the fast suite.
- `pytest -m latex` runs the PDF tests; they need MiKTeX or TeX Live.
- Keep test workers at 4 or fewer.
