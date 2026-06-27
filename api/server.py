import sqlite3
from datetime import timezone, date
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from ebaypricer.config import DB_PATH
from ebaypricer.db import init_db

app = FastAPI(title="eBay Price Tracker API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_db() -> sqlite3.Connection:
    conn = init_db(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


@app.get("/api/cards")
def list_cards():
    conn = get_db()
    try:
        today = date.today().isoformat()
        rows = conn.execute(
            "SELECT card_query, snapshot_date, sample_size, avg_price, median_price, "
            "min_price, max_price, std_dev, weighted_avg "
            "FROM price_snapshots WHERE snapshot_date = ? ORDER BY weighted_avg DESC",
            (today,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


@app.get("/api/cards/{card_query}/history")
def card_history(card_query: str):
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT * FROM price_snapshots WHERE card_query = ? ORDER BY snapshot_date ASC",
            (card_query,),
        ).fetchall()
        if not rows:
            raise HTTPException(status_code=404, detail="Card not found")
        return [dict(r) for r in rows]
    finally:
        conn.close()


@app.get("/api/cards/{card_query}/listings")
def card_listings(card_query: str):
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT item_id, title, price, currency, condition, listing_type, sold_date, url "
            "FROM sold_listings WHERE card_query = ? "
            "ORDER BY sold_date DESC LIMIT 100",
            (card_query,),
        ).fetchall()
        if not rows:
            raise HTTPException(status_code=404, detail="No listings found")
        return [dict(r) for r in rows]
    finally:
        conn.close()
