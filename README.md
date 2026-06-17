# eBay Pokémon Card Price Tracker

Pulls sold listings from the eBay Browse API and builds a local pricing model stored in SQLite.

---

## Setup

### 1. Get eBay API Credentials (free)
1. Go to [developer.ebay.com](https://developer.ebay.com) and create an account
2. Create a new app under **My Account → Application Keysets**
3. Copy your **App ID (Client ID)** and **Client Secret**

### 2. Install dependencies
```bash
pip install -r requirements.txt
```

### 3. Configure your credentials
```bash
cp .env.example .env
# Open .env and paste your App ID and Secret
```

### 4. Add your cards to track
Open `ebay_pull.py` and edit the `CARDS_TO_TRACK` list:
```python
CARDS_TO_TRACK = [
    "Charizard Base Set Holo",
    "Pikachu 25th Anniversary",
    # Add any card + set combo here
]
```

### 5. Run it
```bash
python ebay_pull.py
```

---

## Output

### Console report
Prints a pricing table on every run:
```
Card                                Wtd Avg    Median       Avg     Min     Max    n
Charizard Base Set Holo            $245.00   $230.00   $238.00  $80.00 $450.00   42
```

### SQLite database (`pokemon_prices.db`)
Two tables:
- **`sold_listings`** — raw sold data (deduplicated by eBay item ID)
- **`price_snapshots`** — daily pricing model per card

Query example:
```sql
SELECT card_query, weighted_avg, median_price, sample_size
FROM price_snapshots
WHERE snapshot_date = date('now')
ORDER BY weighted_avg DESC;
```

### JSON export (`price_report.json`)
Today's snapshot exported for use in spreadsheets or other tools.

---

## Pricing Model Logic

| Factor | How it's handled |
|---|---|
| Listing type | Auctions adjusted +12% toward BIN fair value |
| Recency | Last 14 days weighted 2× vs older sales |
| Outliers | Prices beyond 2 std deviations removed |
| Low liquidity | Flagged by low `sample_size` — treat with caution |

The **`weighted_avg`** column is your primary recommended list price.

---

## Automate with a schedule

### Mac/Linux (cron)
```bash
# Run every Monday at 9am
crontab -e
0 9 * * 1 cd /path/to/folder && python ebay_pull.py >> ebay.log 2>&1
```

### Windows (Task Scheduler)
1. Open Task Scheduler → Create Basic Task
2. Set trigger: Weekly
3. Action: `python C:\path\to\ebay_pull.py`

### Free cloud option (GitHub Actions)
Push this folder to a private GitHub repo and add `.github/workflows/pull.yml`:
```yaml
name: Weekly eBay Pull
on:
  schedule:
    - cron: '0 9 * * 1'
jobs:
  pull:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - run: pip install -r requirements.txt
      - run: python ebay_pull.py
        env:
          EBAY_APP_ID: ${{ secrets.EBAY_APP_ID }}
          EBAY_SECRET: ${{ secrets.EBAY_SECRET }}
```

---

## Tips for better results

- **Be specific with card names** — include set name and variant (Holo, Reverse Holo, 1st Edition)
- **Check `sample_size`** — fewer than 5 comps means the price is unreliable
- **PSA/BGS graded cards** — add the grade to the query, e.g. `"Charizard Base Set PSA 10"`
- **Lots** — eBay lots will skew prices; the category filter (2536) helps exclude most but not all