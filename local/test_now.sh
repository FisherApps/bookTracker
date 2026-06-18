#!/bin/bash
# Prove the WHOLE scheduled path works without waiting until 3am:
# the Mac waking itself + the system job firing + scrape + push.
#
#   bash ~/BookTracker/local/test_now.sh           # arm a real FULL run ~3 min out, then sleep
#   bash ~/BookTracker/local/test_now.sh 5         # ...same, but 5 min out
#   bash ~/BookTracker/local/test_now.sh restore   # put the normal 3am schedule back
#
# "arm" reschedules the real job to fire in a few minutes as a FULL run (every
# book — identical to 3am), sets a one-off wake a minute before, and puts the
# Mac to sleep. You watch the Mac wake itself within ~2 min (that proves wake +
# the job firing); the full scrape then runs and pushes when it finishes (can
# take a while). When it works, run "restore" to return to the normal schedule.

set -euo pipefail

LABEL="com.fisherapps.booktracker"
PLIST="/Library/LaunchDaemons/$LABEL.plist"
INSTALL_DIR="$HOME/BookTracker"
RUN_USER="$(id -un)"
LOG="$HOME/Library/Logs/booktracker.log"

# Render + (re)load the daemon plist. $1=hour $2=minute; any further args are
# appended to ProgramArguments (e.g. --asin X --no-retry for the test run).
write_plist() {
  local hour="$1" minute="$2"; shift 2
  local extra=""
  local a
  for a in "$@"; do extra+="        <string>${a}</string>"$'\n'; done
  sudo tee "$PLIST" >/dev/null <<PLIST_EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${LABEL}</string>
    <key>UserName</key>
    <string>${RUN_USER}</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/caffeinate</string>
        <string>-i</string>
        <string>/bin/bash</string>
        <string>${INSTALL_DIR}/local/scrape_local.sh</string>
${extra}    </array>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/usr/bin:/bin:/usr/sbin:/sbin</string>
        <key>HOME</key>
        <string>${HOME}</string>
    </dict>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>${hour}</integer>
        <key>Minute</key>
        <integer>${minute}</integer>
    </dict>
    <key>StandardOutPath</key>
    <string>${LOG}</string>
    <key>StandardErrorPath</key>
    <string>${LOG}</string>
</dict>
</plist>
PLIST_EOF
  sudo chown root:wheel "$PLIST"
  sudo chmod 644 "$PLIST"
  sudo launchctl bootout "system/$LABEL" 2>/dev/null || true
  sudo launchctl bootstrap system "$PLIST"
  sudo launchctl enable "system/$LABEL"
}

# --- restore ------------------------------------------------------------
if [ "${1:-}" = "restore" ]; then
  echo "Restoring the normal 3:00am schedule..."
  sudo -v
  write_plist 3 0
  sudo pmset repeat wakeorpoweron MTWRFSU 02:55:00
  echo "Done — back to normal: runs 3:00am daily, Mac wakes at 2:55am."
  exit 0
fi

# --- arm ----------------------------------------------------------------
LEAD="${1:-3}"
if ! [[ "$LEAD" =~ ^[0-9]+$ ]] || [ "$LEAD" -lt 2 ]; then
  echo "Give a number of minutes >= 2 (default 3). Got: $LEAD"
  exit 1
fi

RUN_HOUR=$((10#$(date -v+"${LEAD}"M +%H)))
RUN_MIN=$((10#$(date -v+"${LEAD}"M +%M)))
WAKE_AT="$(date -v+"$((LEAD-1))"M '+%m/%d/%y %H:%M:%S')"

echo "Arming a real FULL run at $(date -v+"${LEAD}"M '+%-I:%M %p')..."
sudo -v
write_plist "$RUN_HOUR" "$RUN_MIN"
sudo pmset schedule wake "$WAKE_AT"

echo ""
echo "============================================"
echo " The Mac will SLEEP now and WAKE ITSELF in about $((LEAD-1)) min, then run."
echo " Watch for: the screen wakes on its own + activity — that proves the wake"
echo " and the job firing. The FULL scrape then runs (can take a while, it pauses"
echo " between books) and pushes at the end. Confirm with the log or dashboard:"
echo "   tail -f \"$LOG\""
echo "   https://fisherapps.github.io/bookTracker/dashboard.html"
echo ""
echo " >>> ONCE YOU'VE CONFIRMED IT WORKED, restore the normal schedule:"
echo "       bash ~/BookTracker/local/test_now.sh restore"
echo "============================================"
echo "Sleeping in 8 seconds...  (press Ctrl-C now to cancel)"
sleep 8
sudo pmset sleepnow
