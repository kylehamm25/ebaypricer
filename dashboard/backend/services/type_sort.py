"""Sort listings by card type ("Fire", "Grass", "Trainer", ...) in Python.

Type has no column anywhere - the catalog lives in a local file, not a joinable
table - so it can never be an ORDER BY key. Both callers (inventory, which has no
pagination, and active, which sorts the whole filtered set before slicing the
page) therefore fetch first and sort here, keyed off `card_type_label()` with one
catalog lookup per distinct card and no network.

One copy on purpose: the grouping rule (by type, then card number, unknowns
last) has to read the same on every page that offers it.
"""

from ebaypricer.cards import card_type_label


def sort_by_card_type(items, *, direction, query_of, number_of, id_of):
    """Groups by type, and within one type orders by card number - "all the Fire
    cards together, in card-number order" rather than type alone leaving
    same-type cards in whatever order they happened to arrive.

    The key functions adapt the helper to each caller's row shape: `query_of`
    returns the card_query string (None when the row isn't a catalog card),
    `number_of` the card number (None when unknown), `id_of` the row's identity
    for the final tiebreak.

    Three layered stable sorts, least significant first: id DESC (final tiebreak),
    then card number ascending - always ascending regardless of `direction`, since
    reversing numbers within a type has no obvious reading order to prefer - then
    type itself per `direction`. A card whose type can't be resolved sorts last
    regardless of direction (the Python equivalent of `NULLS LAST`). Python's sort
    is stable, so `reverse` on the outermost (type) pass only flips which type
    comes first - it doesn't disturb the number/id order already established
    within a type.
    """
    types = {q: card_type_label(q) for q in {query_of(i) for i in items if query_of(i)}}
    by_id = sorted(items, key=lambda i: id_of(i), reverse=True)
    by_number = sorted(by_id, key=lambda i: (number_of(i) is None, number_of(i) or ""))
    known = [i for i in by_number if types.get(query_of(i))]
    unknown = [i for i in by_number if not types.get(query_of(i))]
    known.sort(key=lambda i: types[query_of(i)], reverse=(direction != "asc"))
    return known + unknown
