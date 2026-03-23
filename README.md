# 🎬 BookMyShow IMAX Alert System
### Automated notifier for *Project Hail Mary* IMAX bookings in Chennai

Runs on **GitHub Actions** (free tier) every 5 minutes. Sends a **Telegram message** the moment IMAX tickets go live on BookMyShow.

---

## How It Works

```
GitHub Actions (cron: every 5 min)
        │
        ▼
check_bms.py
  ├── Calls BMS internal API → searches for "Project Hail Mary" in Chennai
  ├── Fetches showtimes for the movie
  ├── Filters for IMAX shows with booking open
  ├── Checks state file → skips already-alerted shows
  ├── Sends Telegram alert (if new IMAX shows found)
  └── Saves updated state (via GitHub Actions Cache)
```

---

## Setup (15 minutes total)

### Step 1 — Create a Telegram Bot

1. Open Telegram, search for **@BotFather**
2. Send `/newbot` and follow the prompts
3. Copy the **Bot Token** (looks like `123456789:AAF...`)
4. Start a chat with your new bot (send any message to it)
5. Get your **Chat ID**:
   - Visit: `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates`
   - Look for `"chat":{"id": 123456789}` — that number is your Chat ID

### Step 2 — Fork / Create the GitHub Repo

```bash
# Option A: Clone this project
git clone https://github.com/YOUR_USERNAME/bms-alert.git
cd bms-alert

# Option B: Create fresh repo and copy files
mkdir bms-alert && cd bms-alert
git init
# Copy check_bms.py, requirements.txt, .github/ folder here
git add . && git commit -m "Initial BMS alert setup"
git remote add origin https://github.com/YOUR_USERNAME/bms-alert.git
git push -u origin main
```

### Step 3 — Add GitHub Secrets

In your GitHub repo:
1. Go to **Settings → Secrets and variables → Actions**
2. Click **New repository secret** and add:

| Secret Name           | Value                          |
|-----------------------|-------------------------------|
| `TELEGRAM_BOT_TOKEN`  | Your bot token from BotFather |
| `TELEGRAM_CHAT_ID`    | Your Telegram chat ID         |

### Step 4 — Enable GitHub Actions

1. Go to the **Actions** tab in your repo
2. If prompted, click **"I understand my workflows, go ahead and enable them"**
3. Click **"BMS IMAX Alert"** → **"Run workflow"** to test immediately

### Step 5 — Verify It Works

- Click the workflow run to see logs
- You should see output like:
  ```
  Movie not in API listings yet. Trying HTML fallback...
  No IMAX shows found. Booking not open yet.
  ```
- Once Project Hail Mary goes live on BMS, you'll get a Telegram message instantly

---

## Testing Locally

```bash
pip install -r requirements.txt

# Test without sending Telegram (credentials missing = logs only)
python check_bms.py

# Test with real Telegram
export TELEGRAM_BOT_TOKEN="your_token"
export TELEGRAM_CHAT_ID="your_chat_id"
python check_bms.py
```

---

## Customization

### Change the movie or city

Edit `CONFIG` in `check_bms.py`:

```python
CONFIG = {
    "movie_name": "Dune Part Three",   # Change movie name
    "city_code": "MUMB",               # Mumbai
    "city_name": "Mumbai",
    "show_type": "IMAX",               # or "4DX", "Dolby", "MX4D"
    ...
}
```

**BMS City Codes:**
| City      | Code  |
|-----------|-------|
| Chennai   | CHEN  |
| Mumbai    | MUMB  |
| Delhi     | NDLS  |
| Bangalore | BANG  |
| Hyderabad | HYDE  |
| Pune      | PUNE  |
| Kolkata   | KOLK  |

### Change check frequency

Edit `.github/workflows/bms_alert.yml`:

```yaml
schedule:
  - cron: "*/10 * * * *"   # Every 10 minutes
  - cron: "*/5 9-23 * * *"  # Every 5 min, only 9am–11pm IST
```

> ⚠️ GitHub Actions free tier allows 2,000 minutes/month. Every-5-min = ~8,640 runs/month. Each run takes ~30s = ~72 minutes/day = ~2,160 min/month. You may occasionally hit the limit near end of month — consider every 10 min to stay safe.

---

## Duplicate Alert Prevention

State is persisted using **GitHub Actions Cache** (`bms-alert-state-v1`). Each detected IMAX show gets a unique MD5 fingerprint. Once alerted, that show is never re-alerted even across workflow runs.

To reset (e.g., to re-alert yourself): delete the cache in **Actions → Caches**.

---

## Alert Message Example

```
🎬 IMAX Booking Open — Project Hail Mary!
📍 City: Chennai
📅 Date: 15 Jun 2025

3 IMAX show(s) found:

🎥 SPI Cinemas - Palazzo (Velachery)
   Format: IMAX 3D
   Time: 10:30 AM
   [Book Now](https://in.bookmyshow.com/...)

🎥 AGS Cinemas (OMR)
   Format: IMAX
   Time: 2:00 PM
   [Book Now](https://in.bookmyshow.com/...)

🔗 View all Chennai IMAX shows
⏰ Detected at: 04:35 UTC
```

---

## Extending to Multiple Movies

Add a list to `check_bms.py`:

```python
WATCHLIST = [
    {"movie_name": "Project Hail Mary", "show_type": "IMAX"},
    {"movie_name": "Avatar 3",          "show_type": "IMAX"},
    {"movie_name": "Thunderbolts",      "show_type": "4DX"},
]

for item in WATCHLIST:
    CONFIG.update(item)
    main()
```

---

## Troubleshooting

| Issue | Fix |
|-------|-----|
| No alerts received | Check Telegram bot — send it `/start` first |
| `401 Unauthorized` in Telegram | Re-check bot token secret spelling |
| Workflow not running | Make sure Actions are enabled in repo settings |
| False negatives | BMS sometimes blocks scrapers — the HTML fallback handles this |
| Rate limited by BMS | Increase cron to `*/10` instead of `*/5` |
