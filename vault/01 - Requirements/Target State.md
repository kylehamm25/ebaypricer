Multi-user SaaS where each user connects their own eBay account. Data in Supabase (Postgres + Auth + RLS), dashboard deployed remotely, workbook dependency removed.

___
### Target Pieces
- Supabase Auth (email/password), RLS: user-owned tables check `user_id = auth.uid()`, shared tables readable by any authenticated user
- Per-user eBay OAuth (PKCE), refresh tokens encrypted at rest
- Per-user sync replaces `append_sold_orders.py` / `excel_sync.py`
- Shared snapshot jobs stay server-side
- Workbook retired, derived columns recomputed server-side from shared snapshots

___
### Migration Phases
- Phase 1 - Platform: Supabase project, DDL + RLS, psycopg pool, JWT auth
- Phase 2 - Data migration: SQLite to Supabase
- Phase 3 - Shared price research - done
- Phase 4 - Deploy: FastAPI + built frontend on one host
- Phase 5 - eBay OAuth per user
- Phase 6 - Per-user sync - done
- Phase 7 - Retire workbook - done Oct 2026 (parity-verified, legacy chain deleted)

Full phase table lives in `docs/SOFTWARE_PLAN.md` section 7, schema in section 6.

___
### Related
- [[System Architecture]]
- [[Project Dashboard]]
