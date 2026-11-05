### Pipeline (Python, from repo root)
`pip install -e .` - required, installs `src/ebaypricer` as editable package
`python scripts/gen_access_token.py` - one-time OAuth consent flow, writes tokens to `.env`

- Legacy chain (`scripts/main.py`, `price_active_listings.py --force`) deleted Oct 2026 with the pipeline retirement; sync runs in the backend scheduler

No test suite exists in this repo currently.

### Dashboard Backend (FastAPI, from repo root)
`python -m uvicorn dashboard.backend.main:app --host 127.0.0.1 --port 8000 --reload` - backend on :8000

Frontend commands are the standard `npm run` scripts in `dashboard/frontend/package.json`.

### Full Stack Shortcuts
`start-dashboard.bat` - backend (:8000) + frontend dev server (:5173) in separate windows, dev mode
`start-prod.bat` - builds frontend if needed, serves everything from FastAPI on :8000

### Database Migrations
- `db/migrations/NNNN_*.sql` are numbered, idempotent, applied by hand in the Supabase SQL editor
- No migration runner - code that depends on a new table must degrade rather than crash if it hasn't been run
