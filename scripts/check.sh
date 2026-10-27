#!/bin/sh
# Runs the CI checks locally, in the same order as .github/workflows/ci.yml.
# The pre-push hook runs it; skip once with `git push --no-verify`.
#   scripts/check.sh              lint, fast tests, privacy guards, extension when it changed
#   scripts/check.sh --extension  always run the extension checks
#   scripts/check.sh --latex      also run the PDF tests (needs TeX Live or MiKTeX)
set -eu
root="$(git rev-parse --show-toplevel)"
cd "$root"
bin="$root/.venv/bin"
extension=auto
latex=no
for arg in "$@"; do
  case "$arg" in
    --extension) extension=yes ;;
    --latex) latex=yes ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done

step() { printf '\n== %s\n' "$1"; }

step "ruff check"
"$bin/ruff" check .

step "unit tests"
"$bin/pytest" -q -m "not latex"

if [ "$latex" = yes ]; then
  step "PDF tests"
  "$bin/pytest" -q -m latex
fi

step "no tracked files under data/"
if [ -n "$(git ls-files data/)" ]; then
  git ls-files data/
  echo "files under data/ are tracked" >&2
  exit 1
fi

step "guard tree"
"$bin/cvforge" guard tree

if [ "$extension" = auto ]; then
  base="$(git merge-base HEAD origin/main 2>/dev/null || true)"
  if [ -z "$base" ] || ! git diff --quiet "$base" -- extension; then
    extension=yes
  fi
fi
if [ "$extension" = yes ]; then
  step "extension typecheck, tests and build"
  [ -d extension/node_modules ] || (cd extension && npm ci)
  (cd extension && npm run typecheck && npm test && npm run build)
fi

printf '\nAll CI checks passed.\n'
