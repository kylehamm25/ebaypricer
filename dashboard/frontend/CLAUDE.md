# Dashboard frontend

Moved out of the root CLAUDE.md so it loads only when you are working in here.
Stack and dependencies are in `package.json`; what follows is what that file can't
tell you.

- `lib/api.ts` — API client, base URL from `VITE_API_BASE` (defaults to local backend).
- `lib/auth.tsx` / `auth-context.ts` — Supabase session provider; `App.tsx` gates all routes except `/login` behind a `Protected` wrapper.
- `lib/theme.tsx` — light/dark theme context; **components must handle both**.
- `pages/` — one file per route: Dashboard, SoldOrders, ActiveListings, ListingDetail, Lots (`/lots`, per-SKU cost/profit; a row opens LotDetail at `/lots/:sku`, which lists that lot's sold and active listings — the pencil button, not the row, opens the cost editor, shared by both as `components/shared/LotEditDialog`), PriceLog (`/log`, reads `GET /active/price-changes`), Settings, Login. (Standalone Pricing and Promotions pages were removed; that data now lives on the Active Listings and Dashboard pages.)
- `components/shared/` — `DataTable`, `KpiCard`, `Skeleton`, `StageRefreshButton` (the page-level refresh control wired to `stage_runner`).
- Linting is **oxlint** (`.oxlintrc.json`), not ESLint.

## Never compute a price here

The suggested price is computed server-side and read through one API field. A
client-side `computeRecommendedPrice` used to live here and produced different
numbers on the list page than on the detail page — that is why it was deleted.
Display `suggested_price` / `suggested_price_basis`; never recompute or adjust
them in the UI. See the `ebay-pricing-rules` skill.
