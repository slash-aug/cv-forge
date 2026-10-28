#!/usr/bin/env bash
# Nightly job discovery, started by the Windows scheduled task (see README).
cd "$(dirname "$0")/.." || exit 1
{
  echo "== $(date '+%Y-%m-%d %H:%M')"
  .venv/bin/cvforge jobs fetch
} >> "$HOME/cvforge-jobs.log" 2>&1
