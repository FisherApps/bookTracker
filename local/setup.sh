#!/bin/bash
# One-time setup for running the BSR scraper on this Mac (the Mac mini).
#
# Run it with a single command in Terminal (see local/README.md):
#   curl -fsSL https://raw.githubusercontent.com/FisherApps/bookTracker/main/local/setup.sh -o /tmp/bt-setup.sh && bash /tmp/bt-setup.sh
#
# It is safe to re-run. It will:
#   1. Install uv (manages its own Python + virtualenv — no system Python needed)
#   2. Clone the repo to ~/BookTracker and install dependencies
#   3. Store a GitHub token so the 3am job can push results unattended
#   4. Install a launch agent that scrapes every day at 3:00am
#   5. Tell the Mac to wake itself at 2:55am so the job can run
#   6. Put an "Update Books" shortcut on the Desktop for manual runs
#   7. Do a quick test to confirm scraping and pushing both work

set -euo pipefail

REPO_URL="https://github.com/FisherApps/bookTracker.git"
INSTALL_DIR="$HOME/BookTracker"
LABEL="com.fisherapps.booktracker"
PLIST="/Library/LaunchDaemons/$LABEL.plist"   # system-level: runs for any account
RUN_USER="$(id -un)"
LOG="$HOME/Library/Logs/booktracker.log"
RUN_HOUR=3
RUN_MIN=0
WAKE_TIME="02:55:00"

echo "============================================"
echo " BookTracker — Mac setup"
echo "============================================"

# --- 1. uv --------------------------------------------------------------
if ! command -v uv >/dev/null 2>&1; then
  echo "[1/7] Installing uv..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
else
  echo "[1/7] uv already installed."
fi
export PATH="$HOME/.local/bin:$PATH"

# --- 2. clone + dependencies -------------------------------------------
if [ -d "$INSTALL_DIR/.git" ]; then
  echo "[2/7] Repo already present, updating..."
  git -C "$INSTALL_DIR" pull --rebase --autostash || true
else
  echo "[2/7] Cloning repo to $INSTALL_DIR..."
  git clone "$REPO_URL" "$INSTALL_DIR"
fi
cd "$INSTALL_DIR"
echo "      Creating Python environment + installing dependencies..."
uv venv --python 3.12 .venv
uv pip install -r requirements.txt
chmod +x "$INSTALL_DIR/local/scrape_local.sh"

# --- 3. git identity + push token --------------------------------------
echo "[3/7] Configuring git push..."
git config user.name "BookTracker (Mac mini)"
git config user.email "brianpfisher98@gmail.com"

# Only ask for a token if push isn't already working.
if git push --dry-run origin HEAD >/dev/null 2>&1; then
  echo "      Push already works — keeping existing credentials."
else
  echo ""
  echo "      Paste a GitHub token with Contents read/write on FisherApps/bookTracker."
  echo "      (See local/README.md for how to create one. Input is hidden.)"
  read -rsp "      Token: " TOKEN
  echo ""
  if [ -z "$TOKEN" ]; then
    echo "      ERROR: no token entered. Re-run setup when you have one."
    exit 1
  fi
  git remote set-url origin "https://${TOKEN}@github.com/FisherApps/bookTracker.git"
  if git push --dry-run origin HEAD >/dev/null 2>&1; then
    echo "      Token works."
  else
    echo "      ERROR: push still failing with that token. Check its scope/expiry."
    exit 1
  fi
fi

# --- 4 & 5 need admin rights; ask for the password once, up front. -----
echo ""
echo "The next two steps need an admin password ONCE (so the job runs for any"
echo "account, even when nobody is logged in). You won't be asked again."
sudo -v

# --- 4. system launch daemon (3am daily, any account) ------------------
echo "[4/7] Installing the daily 3am job (system-wide)..."
mkdir -p "$(dirname "$LOG")"
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
    </array>
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
        <integer>${RUN_HOUR}</integer>
        <key>Minute</key>
        <integer>${RUN_MIN}</integer>
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
echo "      Scheduled for ${RUN_HOUR}:$(printf '%02d' "$RUN_MIN") every day, runs as ${RUN_USER}."

# --- 5. wake schedule --------------------------------------------------
echo "[5/7] Telling the Mac to wake at ${WAKE_TIME}..."
sudo pmset repeat wakeorpoweron MTWRFSU "$WAKE_TIME"

# --- 6. desktop shortcut -----------------------------------------------
echo "[6/7] Creating the 'Update Books' Desktop shortcut..."
CMD="$HOME/Desktop/Update Books.command"
cat > "$CMD" <<CMD_EOF
#!/bin/bash
# Double-click to run a BSR scrape on this Mac right now.
caffeinate -i /bin/bash "$INSTALL_DIR/local/scrape_local.sh"
echo ""
echo "Finished. You can close this window."
read -n 1 -s -r -p "Press any key to close..."
CMD_EOF
chmod +x "$CMD"

# --- 7. quick test -----------------------------------------------------
echo "[7/7] Quick test (one book, no data written)..."
SAMPLE_ASIN="$("$INSTALL_DIR/.venv/bin/python" - <<'PY'
import json
books = [b for b in json.load(open("books.json")) if b.get("active", True)]
print(books[0]["asin"] if books else "")
PY
)"
if [ -n "$SAMPLE_ASIN" ]; then
  "$INSTALL_DIR/.venv/bin/python" -m src.scrape --asin "$SAMPLE_ASIN" --dry-run --no-retry \
    && echo "      Scrape test OK (Amazon reachable from this IP)." \
    || echo "      WARNING: scrape test failed — check the output above."
fi

echo ""
echo "============================================"
echo " Done. You can walk away."
echo "  - Runs automatically every day at 3:00am."
echo "  - Manual run: double-click 'Update Books' on the Desktop."
echo "  - Logs: $LOG"
echo "============================================"
