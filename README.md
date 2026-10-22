# cv-forge

cv-forge is a job-search copilot. It keeps one master profile of everything you have done and turns it into an honest, ATS-checked LaTeX CV and cover letter for each real job posting. You always click submit yourself.

![First page of the example CV](examples/persona/preview.png)

## The problem

Searching for a job today means doing the same chores over and over:

- Reformatting your CV for every posting, then wondering whether an applicant tracking system (ATS) can even read the PDF.
- Writing for AI screening filters that reject candidates on keywords and layout quirks before a person looks at them.
- Retyping the same details into every application form.
- Spending time on ghost jobs: postings that are stale, never filled, or never meant to be.

cv-forge removes the mechanical part of this work and keeps the judgment with you.

## What works today (Phase 1)

Phase 1 is the foundation: from a master profile to a checked PDF.

- One master YAML profile holds every job, project, achievement and skill, with stable ids.
- A tailored selection picks which items to show for a given role and may reword their text. Job titles, employers and dates always come from the master; the tailored file only refers to them by id.
- An audit step checks the tailored file against the master: every id must exist, every number in a reworded bullet must appear in its source highlight (numbers in the summary and letter must appear in the master), every skill keyword must be a keyword of that skill in the master, and confidential terms listed in the master are blocked.
- Before anything is compiled, every rendered field, including those taken from the master (employer names, titles, institutions, contact links), is scanned for confidential terms; `build` and `master-cv` stop on a match.
- A LaTeX renderer produces a CV and a matching cover letter, in English, Brazilian Portuguese or European Portuguese.
- A compile step builds the PDFs, and an ATS check verifies the result: the page limit (CV at most 2 pages, letter exactly 1), a clean text layer (no unmapped glyphs or replacement characters), required text present (the CV must contain your name, the summary opening and every contact item; the letter must contain your name), section headings in order, and date ranges joined by an ASCII hyphen. Layout checks fail the build on orphaned entry headers, stranded section headings, holes in a page, pages that end early and text colliding with the footer; a thin last page is reported as a note only, since a CV of one and a half pages is fine.
- Privacy guards run as git hooks and in CI, so personal data stays out of the repository.

Commands:

```
cvforge validate <master>                      check a master profile against the schema
cvforge audit <tailored> --master <master>     compare a tailored CV with the master
cvforge build <tailored> --master <master>     audit, render, compile and ATS-check
cvforge master-cv <master> --lang en           render a full CV straight from the master
cvforge guard staged | tree | msg <file>       privacy checks used by the hooks and CI
```

## Flow

![Flow: master profile, tailor to a job, audit against master, render LaTeX, compile PDF, ATS check, you review and submit](docs/flow.svg)

## Roadmap

| Phase | Scope | Status |
| --- | --- | --- |
| 1 | Master profile, tailoring, audit, LaTeX CV and letter, ATS check, privacy guards, CI | Done |
| 2 | Apply flow: paste a job link or text to get a tailored, audited CV and letter, a salary suggestion, drafted screening answers, a copy-paste application kit and a tracker entry | Planned |
| 3 | Job discovery from public sources, with hard filters and a ghost-job score to drop stale or fake postings | Planned |
| 4 | Feedback loop: email sync for replies, an application report and follow-up reminders | Planned |
| 5 | A clean local web UI to track every application and run cv-forge without the command line | Planned |

## Quick start

Requires Python 3.10 or newer and a LaTeX setup (see below).

```bash
git clone <this repository> cv-forge && cd cv-forge
python3 -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'
git config core.hooksPath .githooks        # enable the privacy hooks

cvforge validate examples/persona/master.yaml
cvforge build examples/persona/tailored.yaml \
  --master examples/persona/master.yaml --out out/
```

`examples/persona` is a fictional candidate, "Ana Exemplo", with an English selection (`tailored.yaml`) and a Brazilian Portuguese one (`tailored.pt-BR.yaml`). The build writes a CV PDF and a cover letter PDF to `out/` and prints the result of the ATS check for each. Without `--out`, `build` writes to `data/applications/<company>-<role>/` and `master-cv` to `data/review/`.

To use your own data, copy the persona files into `data/profile/` and edit them. That directory is ignored by git.

## LaTeX setup

The templates need LuaLaTeX for the CV and XeLaTeX for the letter, plus the `moderncv` class and `fontawesome5`.

Fonts ship with the package, so there is no extra font install. The CV is set in Lato and the cover letter uses Lato with some Raleway, so the two look alike and render evenly on screen. Both families are SIL OFL, and their licence files are included next to the font files. Both templates load them with `fontspec` from a relative path inside the build directory.

- **Linux:** install a current TeX Live (the [official installer](https://tug.org/texlive/) or the `texlive/texlive` Docker image). Distribution packages can lag a year or more behind; the CV header needs a recent `moderncv`.
- **CI:** the PDF job runs inside the official `texlive/texlive` image, pinned by digest, so it uses the same current packages as a local install.
  `poppler-utils` provides `pdftotext`, which the ATS check uses.
- **Windows:** install MiKTeX and run cv-forge from WSL. cv-forge calls the Windows engines (`lualatex.exe`, `xelatex.exe`), which can only write to Windows drives, so the build directory must be under `/mnt` (for example `/mnt/d/cv-forge-build`). The defaults assume MiKTeX in `D:\MiKTeX`; anywhere else, set the engine paths and the build directory as described in [Configuration](#configuration).

## Configuration

Settings come from environment variables first, then the `[cvforge]` table of `cvforge.toml` at the repository root (ignored by git), then the defaults.

| Key in `cvforge.toml` | Environment variable | Default |
| --- | --- | --- |
| `data_dir` | `CVFORGE_DATA_DIR` | `data/` in the repository |
| `build_dir` | `CVFORGE_BUILD_DIR` | `/mnt/d/cv-forge-build` if `/mnt/d` exists, else `build/` in the repository |
| `lualatex` | `CVFORGE_LUALATEX` | `/mnt/d/MiKTeX/miktex/bin/x64/lualatex.exe` if present, else `lualatex` on `PATH` |
| `xelatex` | `CVFORGE_XELATEX` | `/mnt/d/MiKTeX/miktex/bin/x64/xelatex.exe` if present, else `xelatex` on `PATH` |

```toml
[cvforge]
build_dir = "/mnt/c/cv-forge-build"
lualatex = "/mnt/c/Program Files/MiKTeX/miktex/bin/x64/lualatex.exe"
xelatex = "/mnt/c/Program Files/MiKTeX/miktex/bin/x64/xelatex.exe"
```

LaTeX runs in `<build_dir>/.cvforge-jobs/<job>/`, which is wiped before each run; nothing else in the build directory is touched. The finished PDFs are copied to the output directory. The privacy denylist is read from `<data_dir>/profile/master.yaml`.

## Privacy model

A CV repository is easy to leak from by accident, so privacy is enforced by tooling and not by habit.

- `data/` holds your real profile, tailored files and outputs. It is gitignored, and CI fails if any file under it is tracked.
- Git hooks in `.githooks` block commits that contain private paths, terms from a personal denylist derived from your profile (matched ignoring case and character width; a term without spaces or hyphens also matches when they are added, so `projectzebra` catches `Project Zebra`, while a hyphenated term like `acme-corp` matches only as written), ID and phone number patterns, em dashes, or AI attribution in messages.
- In CI, `cvforge guard tree` runs the path and content rules on every tracked file, and `cvforge guard msg` checks every new commit message. CI has no master profile, so its denylist is empty; the other rules still apply.
- Secret scanning runs in CI with gitleaks.
- Everything public in this repository uses a fake persona and fake companies.

## You always click submit

cv-forge prepares material. It does not log in to job sites, fill in forms or send applications on your behalf. Facts come from your master profile and the audit blocks the drift it can detect (changed numbers, unknown skills, confidential terms), but reworded text is still yours to read, and every submission is a decision you make. A tool that applies in bulk produces noise for recruiters and risk for you; this one is built to help you apply to fewer, better-matched jobs.

## Credit and licence

cv-forge builds on [ai-job-search](https://github.com/ai-job-search-dev/ai-job-search) (MIT), whose LaTeX templates and ATS checks it adapts. Licensed under the MIT licence; see `LICENSE`.
