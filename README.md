# eBay Pokémon Card Price Tracker

Pulls sold listings from the eBay Browse API and builds a local pricing model stored in SQLite.

## Setup

### 1. Get eBay API Credentials
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
Add one card per line to `data/cards_to_track.txt`:
```
Charizard Base Set Holo
Pikachu 25th Anniversary
```

### 5. Run it
```bash
python main.py
```

Point it at a different card list:
```bash
python main.py my_cards.txt
```

## Project Layout

```
├── ebaypricer/               # core package
│   ├── config.py             # env vars, CLI args, constants
│   ├── api.py                # eBay OAuth + Browse API search
│   ├── db.py                 # SQLite init, inserts, price snapshots
│   ├── models.py             # item parsing
│   └── report.py             # console table + JSON export
├── scripts/
│   ├── gen_access_token.py   # OAuth user token generator
│   └── pull_active.py        # fetch your active eBay listings
├── data/                     # local-only runtime files
│   ├── cards_to_track.txt
│   ├── active_listings.txt
│   └── pokemon_prices.db
├── main.py                   # entry point
├── .env.example
└── requirements.txt
```

## Output

### Console report
Prints a pricing table on every run:
```
Card                                Wtd Avg    Median       Avg     Min     Max    n
Charizard Base Set Holo            $245.00   $230.00   $238.00  $80.00 $450.00   42
```

### SQLite database (`data/pokemon_prices.db`)
Two tables:
- **`sold_listings`** — raw sold data (deduplicated by eBay item ID)
- **`price_snapshots`** — daily pricing model per card

### JSON export (`data/price_report.json`)
Today's snapshot exported for use in spreadsheets or other tools.

## Pricing Model Logic

| Factor | How it's handled |
|---|---|
| Recency | Last 14 days weighted 2× vs older sales |
| Outliers | Prices beyond 2 std deviations removed |
| Low liquidity | Flagged by low `sample_size` — treat with caution |

The **`weighted_avg`** column is your primary recommended list price.
