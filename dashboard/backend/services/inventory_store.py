"""The one inventory INSERT/UPDATE builder.

Extracted from routers/inventory.py because the scan importer has to create an
inventory row and mark its import confirmed in the same transaction. Opening a second
connection there would make a crash between the two writes leave a real row behind an
import that still looks pending - and retrying it would create a duplicate. The
service deliberately takes the caller's connection; it never opens or commits one.

The column set is built from `existing_columns` for the same reason the read path is:
each later migration adds optional columns, and hand-written fallback statements would
double on every one. A value supplied for a column this database lacks is refused with
the migration that adds it, never silently dropped.
"""

from dashboard.backend.services.upsert_rules import existing_columns

MIGRATION_HINT = "Unlisted inventory needs db/migrations/0011_inventory.sql to be run first"

# Columns every install has (0011). Order is only for readability - the statements
# below are built from these names, so nothing has to be kept in step by hand.
WRITE_COLUMNS = (
    "name", "card_query", "set_name", "number", "condition", "quantity",
    "location", "sku", "cost", "notes",
)

# Columns a later migration added, written only when the database has them. Each one
# names the migration to run, because a value supplied for a missing column is refused
# out loud rather than silently dropped - a stated price that vanished would show the
# row as unpriced with no explanation, and photos that vanished would come back as an
# empty prefill cell.
OPTIONAL_WRITE_COLUMNS = {
    "manual_value":
        "A stated price needs db/migrations/0012_inventory_manual_value.sql to be run first",
    "photo_urls":
        "Photos need db/migrations/0016_inventory_photo_urls.sql to be run first",
}


class InventoryWriteError(RuntimeError):
    """A write the router should report as a 503 with this message."""

    def __init__(self, message: str, status: int = 503):
        super().__init__(message)
        self.status = status


def write(db, params: dict, item_id: int | None = None):
    """Insert or update a row on the caller's connection.

    `params` carries the columns plus `uid`; `item_id` switches from INSERT to UPDATE
    and adds the id. A miss on UPDATE (gone or another user's) returns None, exactly
    as the router's 404 handling expects.
    """
    present = existing_columns(db, "inventory")
    if not present:
        raise InventoryWriteError(MIGRATION_HINT)

    params = dict(params)
    columns = list(WRITE_COLUMNS)
    for column, hint in OPTIONAL_WRITE_COLUMNS.items():
        if column in present:
            columns.append(column)
        elif params.get(column) is not None:
            raise InventoryWriteError(hint)

    if item_id is None:
        sql = (
            f"INSERT INTO inventory (user_id, {', '.join(columns)}) "
            f"VALUES (%(uid)s, {', '.join(f'%({c})s' for c in columns)}) "
            "RETURNING id"
        )
    else:
        params["id"] = item_id
        sql = (
            f"UPDATE inventory SET {', '.join(f'{c} = %({c})s' for c in columns)}, "
            "updated_at = now() WHERE id = %(id)s AND user_id = %(uid)s RETURNING id"
        )
    return db.execute(sql, params).fetchone()
