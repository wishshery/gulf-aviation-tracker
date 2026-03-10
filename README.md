# ✈️ Gulf Aviation Route Tracker

A fully automated aviation dashboard tracking airline routes, disruptions, and operational updates for the 8 major Gulf hub airports. The site updates every morning without manual work.

---

## What it does

- Tracks **new routes**, **suspended routes**, **resumed routes**, and **flight disruptions** affecting Gulf airports
- Collects updates from airline press releases, airport notices, and aviation news sources
- Auto-updates every morning via a scheduled task or GitHub Actions
- Deploys automatically to Vercel, Netlify, or Cloudflare Pages on every data push

---

## Quick start (5 minutes)

### 1. Clone and open

```bash
git clone https://github.com/YOUR_USERNAME/gulf-aviation-tracker.git
cd gulf-aviation-tracker
```

### 2. Open locally

```bash
# Any of these work:
python -m http.server 8000
npx serve .
open index.html   # Mac (file:// mode — fetch() may not work for local JSON)
```

Visit `http://localhost:8000` in your browser. The site reads from `data/*.json`.

### 3. Set up API keys

```bash
cp .env.example .env
# Edit .env and add:
#   ANTHROPIC_API_KEY=sk-ant-...
#   SERPER_API_KEY=...   (optional but recommended)
```

Get a **free Serper.dev key** at https://serper.dev (100 searches/month free) for much better news results.

### 4. Install Python dependencies

```bash
pip install -r requirements.txt
```

### 5. Run a test update

```bash
python scripts/update.py --dry-run   # preview without writing files
python scripts/update.py             # run and update data files
```

---

## Deployment

### Option A — Vercel (recommended, free)

1. Push repo to GitHub
2. Go to [vercel.com/new](https://vercel.com/new) and import the repo
3. Framework: **Other** (static site)
4. Root directory: `/`
5. Deploy — Vercel detects `vercel.json` automatically

Add these secrets in Vercel → Settings → Environment Variables:
- `ANTHROPIC_API_KEY`
- `SERPER_API_KEY` (optional)

### Option B — Netlify (free)

1. Push repo to GitHub
2. Go to [app.netlify.com/start](https://app.netlify.com/start) and connect repo
3. Build command: leave blank
4. Publish directory: `.`
5. Deploy — `netlify.toml` handles headers and caching

### Option C — Cloudflare Pages (free)

1. Push repo to GitHub
2. Cloudflare Dashboard → Pages → Create project → Connect GitHub
3. Build command: leave blank, Output: `/`
4. Deploy

### Option D — GitHub Pages (free)

1. Repo → Settings → Pages → Branch: main, folder: / (root)
2. Done — available at `https://username.github.io/gulf-aviation-tracker`

---

## Automation

### Method 1 — Cowork Scheduled Task (already created)

The Cowork scheduled task `gulf-aviation-daily-update` is already configured to run every morning at 06:05. It searches for aviation news, updates the JSON data files, and saves them to your outputs folder. No additional setup needed.

To trigger manually: open the Scheduled section in Claude's sidebar and click Run Now.

### Method 2 — GitHub Actions (CI/CD in the cloud)

The workflow in `.github/workflows/daily-update.yml` runs automatically every day at 06:00 UTC.

Add these secrets in GitHub → Repo → Settings → Secrets → Actions:
- `ANTHROPIC_API_KEY` — required for LLM extraction
- `SERPER_API_KEY` — optional, improves search quality

The workflow will:
1. Search aviation sources
2. Extract and structure new data
3. Commit updated JSON files
4. Push to main — triggering automatic redeployment on Vercel/Netlify

### Method 3 — Run locally on a schedule

```bash
# macOS/Linux crontab — runs daily at 06:00 local time
crontab -e
# Add:
0 6 * * * cd /path/to/gulf-aviation-tracker && python scripts/update.py >> logs/update.log 2>&1
```

```bash
# Windows Task Scheduler
schtasks /create /tn "GulfAviationUpdate" /tr "python C:\path\update.py" /sc daily /st 06:00
```

---

## File structure

```
gulf-aviation-tracker/
├── index.html                    ← main website (single-file, no build needed)
├── data/
│   ├── disruptions.json          ← active disruptions & status table
│   ├── routes.json               ← new / suspended / resumed routes
│   ├── advisories.json           ← traveler advisories & operational notices
│   └── airports.json             ← Gulf airport cards & stats
├── scripts/
│   └── update.py                 ← automation engine (search → extract → update → git push)
├── .github/workflows/
│   ├── daily-update.yml          ← GitHub Actions daily automation
│   └── deploy-vercel.yml         ← Vercel auto-deploy on push
├── vercel.json                   ← Vercel config (headers, caching)
├── netlify.toml                  ← Netlify config
├── requirements.txt              ← Python dependencies
├── .env.example                  ← environment variable template
└── .gitignore
```

---

## Data format

### disruptions.json

```json
{
  "last_updated": "2026-03-10T06:00:00Z",
  "disruptions": [
    {
      "id": "d001",
      "airline": "Emirates",
      "origin": "London Heathrow",
      "destination": "Dubai",
      "route": "London Heathrow → Dubai",
      "status": "rerouted",
      "effective_date": "2026-03-08",
      "notes": "Flights rerouted south via Arabian Sea…",
      "source": "https://www.emirates.com/…",
      "added_date": "2026-03-10"
    }
  ]
}
```

**Status values:** `operating` | `delayed` | `diverted` | `rerouted` | `suspended` | `cancelled`

### routes.json

```json
{
  "last_updated": "2026-03-10T06:00:00Z",
  "routes": [
    {
      "id": "r001",
      "airline": "Qatar Airways",
      "origin": "Doha",
      "destination": "Lisbon",
      "status": "new",
      "start_date": "2026-06-10",
      "frequency": "4x weekly",
      "aircraft": "Airbus A350-900",
      "description": "Qatar Airways launches non-stop Doha–Lisbon service.",
      "source": "https://…",
      "added_date": "2026-03-05"
    }
  ]
}
```

**Status values:** `new` | `upcoming` | `suspended` | `cancelled` | `resumed` | `relaunched`

### advisories.json

```json
{
  "advisories": [
    {
      "id": "adv001",
      "type": "warning",
      "title": "Airspace Advisory: Extended Routing",
      "body": "Full advisory text…",
      "airline": "Emirates, Qatar Airways",
      "airports": "DXB, DOH, AUH",
      "effective_date": "2026-03-08",
      "expiry_date": "2026-03-25",
      "source": "https://…",
      "added_date": "2026-03-08"
    }
  ]
}
```

**Type values:** `info` | `warning` | `critical`

---

## Tracked airports

| IATA | Airport | Country |
|------|---------|---------|
| DXB  | Dubai International Airport | UAE |
| AUH  | Zayed International Airport | UAE |
| DOH  | Hamad International Airport | Qatar |
| JED  | King Abdulaziz International Airport | Saudi Arabia |
| RUH  | King Khalid International Airport | Saudi Arabia |
| MCT  | Muscat International Airport | Oman |
| KWI  | Kuwait International Airport | Kuwait |
| BAH  | Bahrain International Airport | Bahrain |

## Tracked airlines

Emirates · Qatar Airways · Etihad Airways · Flydubai · Air Arabia · Saudia · Gulf Air · Oman Air · Kuwait Airways · SalamAir · Jazeera Airways · flyadeal · Flynas + international carriers announcing Gulf routes

---

## Customization

To add a new airline to track, edit `scripts/update.py`:

```python
TRACKED_AIRLINES = [
    "Emirates", "Qatar Airways", ...
    "Your New Airline",  # add here
]
```

To add a new search query:

```python
SEARCH_QUERIES = [
    ...
    "Your custom aviation query 2026",
]
```

To change the data retention period (default 45 days):

```bash
# In .env
MAX_AGE_DAYS=60
```

---

## License

MIT — free to use, modify, and deploy.

Data is sourced from public airline press releases, airport announcements, and aviation news outlets. Always verify critical travel information with your airline before travel.
