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
- ask for an **admin password once** (to install the system job + 2:55am wake),
- install the 3am job, then verify the whole flow with one real scrape + push.

That's it. ~2 minutes, then you can leave. **It leaves nothing visible on the
Mac** — no icons, no windows. Your dad never has to do anything.

The job is installed **system-wide**, so it runs at 3am no matter which account
(Dad's or Mom's) is logged in — or if nobody is. Run setup once, from whichever
account you like.

## Daily use (for Dad)

- Nothing to do — it updates itself overnight, silently.
- To view the books: the usual dashboard at
  <https://fisherapps.github.io/bookTracker/dashboard.html>.

If you ever need to force a run yourself, from Terminal:
`bash ~/BookTracker/local/scrape_local.sh`

## Troubleshooting (for you)

- **Logs:** `~/Library/Logs/booktracker.log` (under the account setup ran from)
- **Re-run setup safely:** paste the same command again; it won't duplicate anything.
- **Check the job is installed:** `sudo launchctl list | grep booktracker`
- **Run it by hand from Terminal:** `bash ~/BookTracker/local/scrape_local.sh`
- **Check the wake schedule:** `pmset -g sched`

## Uninstall

```sh
sudo launchctl bootout "system/com.fisherapps.booktracker"
sudo rm /Library/LaunchDaemons/com.fisherapps.booktracker.plist
sudo pmset repeat cancel
rm -rf ~/BookTracker "$HOME/Desktop/Update Books.command"
```
