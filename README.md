# Chrome Hearts Tracker

Watches every shop category on chromehearts.com (Baccarat, Scents,
Boxers & Leggings, Intimates, Socks) and sends a push notification to
your phone for **every** change:

- 🆕 New product listed
- 🔄 Restock (out of stock → available)
- ❌ Sold out
- 💲 Price change
- 🗑️ Product removed

Runs free on GitHub Actions every 20 minutes. No server needed.

## Setup (≈10 minutes)

### 1. Get notifications on your phone (ntfy — free, no account)

1. Install **ntfy** from the App Store / Play Store.
2. In the app, tap **+ Subscribe to topic** and enter a unique,
   hard-to-guess topic name, e.g. `faisal-ch-tracker-x7k2p`.
   (Anyone who knows the topic name can see the notifications, so make
   it random.)
3. That topic name is all you need — remember it for step 3.

### 2. Create the GitHub repo

1. Sign in at github.com → **New repository**.
2. Name it anything (e.g. `ch-tracker`), set it to **Private**, create it.
3. Upload these three files keeping the folder structure:
   - `tracker.py`
   - `README.md`
   - `.github/workflows/tracker.yml`
     (on the upload page you can type the path
     `.github/workflows/tracker.yml` to create the folders)

### 3. Add your topic as a secret

1. In the repo: **Settings → Secrets and variables → Actions →
   New repository secret**.
2. Name: `NTFY_TOPIC`
3. Value: your topic name from step 1 (e.g. `faisal-ch-tracker-x7k2p`).

### 4. Turn it on

1. Go to the **Actions** tab → enable workflows if prompted.
2. Open **Chrome Hearts Tracker → Run workflow** to trigger the first
   run manually.
3. Within a minute you should get a push: *"CH tracker is live —
   now tracking N products."* The first run seeds the baseline; every
   run after that only pings you on actual changes.

## Notes

- Schedule is every 20 minutes (`.github/workflows/tracker.yml`,
  `cron` line). GitHub sometimes delays scheduled runs by a few
  minutes — that's normal.
- Tapping a notification opens the product page directly.
- If the site starts blocking GitHub's servers you'll get a single
  "tracker error" push instead of silence — if that happens
  repeatedly, the fallback is running the same script on any
  always-on machine (Raspberry Pi, cheap VPS) via cron.
- chromehearts.com ships to US addresses only, so plan a forwarder
  or a US address for anything you want to buy.
