# Running the scraper locally on the Mac mini

The Mac mini is the **primary** scraper. It runs every night at 3:00am from the
home (residential) IP, which Amazon almost never captcha-blocks, and pushes the
results to GitHub — which updates the GitHub Pages dashboard automatically.

The GitHub Actions workflow is now just a **backup**: it checks each day whether
the Mac already pushed today's data, and only runs (with its captcha retries) on
days the Mac failed.

## Setup (do this once, sitting at the Mac mini)

### 1. Create a GitHub token (do this beforehand, on any computer)

1. Go to <https://github.com/settings/tokens?type=beta> → **Generate new token**.
2. **Resource owner:** FisherApps. **Repository access:** Only select repositories → `bookTracker`.
3. **Permissions:** Repository permissions → **Contents: Read and write**.
4. **Expiration:** set to **No expiration** (or it'll silently stop pushing later).
5. Generate, copy the token, keep it handy for step 2.

### 2. Run one command on the Mac mini

Open **Terminal** (Spotlight → type "Terminal") and paste this single line:

```sh
curl -fsSL https://raw.githubusercontent.com/FisherApps/bookTracker/main/local/setup.sh -o /tmp/bt-setup.sh && bash /tmp/bt-setup.sh
```

It will:

- install everything (no manual Python install — `uv` handles it),
- ask you to **paste the token** (hidden input),
- ask for the Mac's **login password** once (to schedule the 2:55am wake),
- install the 3am job, add an **"Update Books"** shortcut to the Desktop, and run
  a quick test.

That's it. ~2 minutes, then you can leave.

### 3. One setting to check before you go

System Settings → **Energy** (or Battery → Options): make sure the Mac is set to
**wake for network access** / not to fully prevent scheduled wake, and that it
**stays logged in** (auto-login on). The 3am job runs in the logged-in user
session, so the Mac should stay logged in (it can sleep — it'll wake itself).

## Daily use (for Dad)

- Nothing to do — it updates itself overnight.
- To force an update now: double-click **"Update Books"** on the Desktop and wait
  for it to finish (it can take a while — it pauses between books on purpose).
- To view the books: the usual dashboard at
  <https://fisherapps.github.io/bookTracker/dashboard.html>.

## Troubleshooting (for you)

- **Logs:** `~/Library/Logs/booktracker.log`
- **Re-run setup safely:** paste the same command again; it won't duplicate anything.
- **Check the job is installed:** `launchctl list | grep booktracker`
- **Run it by hand from Terminal:** `bash ~/BookTracker/local/scrape_local.sh`
- **Check the wake schedule:** `pmset -g sched`

## Uninstall

```sh
launchctl bootout "gui/$(id -u)/com.fisherapps.booktracker"
rm ~/Library/LaunchAgents/com.fisherapps.booktracker.plist
sudo pmset repeat cancel
rm -rf ~/BookTracker "$HOME/Desktop/Update Books.command"
```
