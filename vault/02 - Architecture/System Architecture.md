Automated eBay selling pipeline for a Pokemon card business, plus a dashboard to view the data. Two halves that share a database but run independently.

___
### Halves
- **Sync pipeline** (`src/ebaypricer/` + `services/ebay_data.py`) - per-user OAuth sync, eBay APIs straight into Postgres, scheduler + on demand
- **Dashboard** (`dashboard/backend` FastAPI + `dashboard/frontend` React/Vite) - reads Postgres/Supabase, displays sold orders, active listings, pricing

___
### Data Flow (retired Oct 2026)
- Legacy `scripts/main.py` chain (`append_sold_orders -> get_active -> avg_active_price`) over the Excel workbook is deleted
- Local SQLite (`db/pokemon_prices.db`), `services/excel_sync.py`, `services/pipeline_runner.py`, hourly Task Scheduler task removed
- Workbook kept as archive only; lot L0038's cost was migrated into `lots` before retirement

___
### Data Flow (current)
- Per-user OAuth sync (`services/ebay_data.py`) replaces the workbook for connected users
- Page-level refresh runs one slice without a full pipeline (`services/stage_runner.py`)
- Migrations in `db/migrations/` are numbered, idempotent, applied by hand in Supabase SQL editor

___
### Related
- [[Pricing Model]]
- [[eBay APIs]]
- [[Project Dashboard]]
- [[Target State]]
