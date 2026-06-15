#!/bin/bash
# Runs the BSR scrape on this Mac and pushes the results.
#
# Used by two things, both set up by local/setup.sh:
#   - the 3am launch agent (com.fisherapps.booktracker), via caffeinate
#   - the "Update Books" shortcut on the Desktop (manual run)
#
# It scrapes DIRECTLY from this Mac's home IP (no proxy env is set), which is
# the IP Amazon almost never captcha-blocks. Output goes to stdout, which the
# launch agent captures in ~/Library/Logs/booktracker.log.

# Continue past non-fatal errors (e.g. a flaky git pull) so we always try to
# scrape and push whatever we get.
set -uo pipefail

# Locate the repo from this script's own path, so it works no matter which
# user (or the system daemon) runs it, regardless of $HOME.
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="$REPO/.venv/bin/python"

cd "$REPO" || { echo "ERROR: $REPO not found — run setup.sh first."; exit 1; }

echo "=== BookTracker local run: $(date) ==="

# Pull first so our commit builds on top of any cloud/other commits.
git pull --rebase --autostash || echo "WARNING: git pull failed, continuing anyway."

# Scrape, then regenerate the dashboard.
"$PY" -m src.scrape
"$PY" -m src.dashboard

# Commit and push whatever we collected.
git add bsr.db dashboard.html discovered_titles.txt
if git diff --cached --quiet; then
  echo "No changes to commit."
else
  git commit -m "Daily BSR update $(date -u +%Y-%m-%d) (local)"
  git pull --rebase --autostash || echo "WARNING: pull before push failed."
  if git push; then
    echo "Pushed successfully."
  else
    echo "ERROR: git push failed (check the token / network)."
  fi
fi

echo "=== Done: $(date) ==="
