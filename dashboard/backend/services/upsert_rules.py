"""Columns a sync must not blindly overwrite.

Both sync paths (services/excel_sync.py and services/ebay_data.py) build their own
`ON CONFLICT ... DO UPDATE SET` clause, and both would otherwise put a fuzzy-matched
value back over one a person corrected. The rule lives here so the two cannot
disagree about which columns are protected.
"""

# column -> the boolean column that protects it, per table. Adding an entry is all
# it takes to make another field hand-editable and sync-proof.
LOCKED_COLUMNS: dict[str, dict[str, str]] = {
    "active_listings": {
        "card": "card_locked",
        # Derived FROM card (see ebaypricer.cards.card_number) purely so it can be a
        # sort key - it must ride along under the same lock or a locked row's number
        # would keep drifting to match each sync's freshly re-derived (but ignored)
        # card guess, disagreeing with the card actually still in effect.
        "number": "card_locked",
    },
}


def lock_column_for(table: str, column: str) -> str | None:
    return LOCKED_COLUMNS.get(table, {}).get(column)


def has_column(conn, table: str, column: str) -> bool:
    """Whether the migration adding a lock column has actually been run.

    Checked rather than assumed: referencing a missing column would abort the whole
    upsert, and a sync that dies because migration 0013 is outstanding is far worse
    than one that simply doesn't honour locks yet.
    """
    return bool(
        conn.execute(
            "SELECT EXISTS (SELECT 1 FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = %s AND column_name = %s) AS ok",
            [table, column],
        ).fetchone()["ok"]
    )


def existing_columns(conn, table: str) -> set[str]:
    """Every column a table actually has, in one query.

    For code that must degrade across several hand-applied migrations at once:
    asking per column turns into a query per optional field, and a tuple of
    hand-written fallback SELECTs turns into 2^n of them.
    """
    return {
        r["column_name"]
        for r in conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = %s",
            [table],
        ).fetchall()
    }


def set_clause(conn, table: str, column: str) -> str:
    """One column's assignment inside DO UPDATE SET.

    Protected columns keep the stored value while their lock is set; everything else
    takes the incoming value as before.
    """
    lock = lock_column_for(table, column)
    if lock and has_column(conn, table, lock):
        return (
            f"{column} = CASE WHEN {table}.{lock} "
            f"THEN {table}.{column} ELSE EXCLUDED.{column} END"
        )
    return f"{column} = EXCLUDED.{column}"
