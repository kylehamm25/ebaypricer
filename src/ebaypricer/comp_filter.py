"""Comp-pool matching: does this eBay search result actually describe the card we're pricing?

Browse matches on words, not on identity. Searching "Charmander 46 Base" returns
graded slabs, print-error one-offs, two-card bundles, foreign-market listings and
Shadowless prints alongside the ordinary Unlimited copies we actually want to price
against - all of them carrying the right card name and the right card number. Measured
against the stored pool before this module existed, that pool spanned $0.99 to $1500
for a card we list at $5.24, and "Charizard ex 105 FireRed & LeafGreen" spanned $13 to
$15,000.

Every aggregate downstream inherits that. `avg_price` is the margin anchor and
`p25_price` the competitive one, so a single $15,000 slab drags a whole card's
suggestion, and one mispriced $13 outlier drags the floor the other way.
`MAX_ANCHOR_RATIO` in suggested_price.py was the only defense, and it is a blunt one:
it withholds the suggestion entirely rather than fixing the pool.

Two tiers, because they fail differently:

  HARD - the listing is definitely not the thing we're pricing (a slab, a bundle, a
         defect one-off, another country's market). Always dropped. There is no
         sample size small enough to make a $15,000 graded card a useful comp.
  SOFT - the listing looks like a different print or a different card (number
         mismatch, name absent, reverse/Shadowless variant mismatch). Dropped when
         the pool can afford it, restored when dropping them would leave too few
         comps to reason about - the same trade-off research_card_active already
         makes for self-exclusion, and for the same reason: a band computed off 1-2
         comps is worse than a slightly impure one.

Pure by design - no network, no DB, no file IO. The card's structured identity is
resolved by `cards.card_identity()` and passed in, so this module stays testable on
plain dicts and the caller keeps the IO.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Print-defect / novelty variants. Shared with suggested_price.py, which uses the same
# list on OUR OWN titles to decline suggesting a price at all - a defect card trades on
# the defect, not on the card's normal market. The same logic makes them useless as
# comps: this is the "MAJOR PRINT ERROR Ink Hickey" copy of a $4 Charmander listed at
# $1500, and the "ERROR NON HOLO MISPRINT" Naveen at $500 against a $4 pool.
EXCLUDED_TITLE_KEYWORDS = ("holo bleed", "swirl", "miscut", "error")

# Applied to comps only, not to our own titles - widening the shared list above would
# change which of OUR listings get declined, which is a separate decision from which
# comps are usable.
COMP_DEFECT_KEYWORDS = ("misprint", "ink hickey")

# eBay returns the seller's localized condition text for listings surfaced from
# non-US sites even on an EBAY_US search ("Non gradata", "Nicht bewertet",
# "Sin clasificar"). Those are a different market with different prices, so they are
# dropped. An allowlist rather than a foreign-word blocklist: an unrecognized value
# should be visible in the drop counts, not silently trusted.
ENGLISH_CONDITIONS = {
    "ungraded", "graded", "used", "new", "brand new", "new (other)", "open box/used",
    "like new", "very good", "good", "acceptable", "for parts or not working",
    "unknown", "unspecified", "",
}

# Graded slabs. The Browse query already appends "-PSA -BGS -CGC -SGC -graded -slab",
# but negative keywords only see the title, and a slab whose title reads "TAG 9 - 936 -
# MINT" carries none of those words. eBay's own condition field says "Graded" for it,
# which is the reliable signal and was going unused.
GRADED_CONDITIONS = {"graded", "valutata", "bewertet"}
_GRADED_TITLE_RE = re.compile(
    r"\b(?:psa|bgs|cgc|sgc|tag|ace|hga|gma|csg)\s*\d{1,2}(?:\.\d)?\b"
    r"|\bgraded?\s*\d"
    r"|\bslab(?:bed)?\b",
    re.IGNORECASE,
)

# Multi-card listings. A two-card bundle priced at the sum of both cards is not a comp
# for either one ("Venusaur Ex 112 Charizard Ex 105 + Blastoise Ex 104" at $1550).
# Deliberately does NOT treat "&" as a separator: set names contain it routinely
# ("Scarlet & Violet", "FireRed & LeafGreen", "Black & White"). A spaced "+" does not
# appear in set names, and condition shorthand like "PL++" has no leading space.
_LOT_RE = re.compile(
    r"\blot\b|\bbundle\b|\bplayset\b|\bjob\s*lot\b|\bset of\s*\d|\bx\s?\d{1,2}\b|\s\+\s",
    re.IGNORECASE,
)

# Card numbers as they appear in titles: "102/086", "#46/102", "TG12/TG30", "#112",
# and bare promo codes like "SVP145" / "SWSH231". Bare digit runs are deliberately NOT
# extracted - titles are full of years ("1999", "2004"), HP values ("50 HP", "270 HP")
# and set sizes, and treating those as card numbers makes every title look like a lot.
_SLASH_NUM_RE = re.compile(r"\b([A-Za-z]{0,4}\d{1,4})\s*/\s*[A-Za-z]{0,4}\d{1,4}\b")
_HASH_NUM_RE = re.compile(r"#\s*([A-Za-z]{0,4}\d{1,4})\b")
_PROMO_NUM_RE = re.compile(r"\b((?:SVP|SWSH|SM|XY|BW|HGSS|DP|TG|GG|SV|ME)\d{1,4})\b", re.IGNORECASE)

# Non-English prints. A Japanese Charizard 010/071 (S10b) carries the same Pokemon and
# a card number that normalizes to the same "10" as the English print, so neither the
# name nor the number check separates them - but it is a different card in a different
# market. Every card_query in this system resolves against TCGdex's English catalog, so
# a foreign-language comp in an English card's pool is always a mismatch.
_FOREIGN_PRINT_RE = re.compile(
    r"\b(?:japanese|japan|jpn|korean|chinese|german|french|italian|spanish|portuguese)\b",
    re.IGNORECASE,
)

# Pokemon Center promos share the card name and number of the ordinary print but are a
# separate product with its own price, so they contaminate a normal promo's pool (and
# vice versa). Symmetric with the reverse rule below: a PC comp is wrong for a normal
# card, and a normal comp is equally wrong when the search asked for a PC one.
_POKEMON_CENTER_RE = re.compile(r"pok[eé]mon\s*cent(?:er|re)|\bpoke\s*cent(?:er|re)\b|\bpokecent(?:er|re)\b", re.IGNORECASE)

_REVERSE_RE = re.compile(r"\breverse\b", re.IGNORECASE)
# Master Ball / Poke Ball reverse-holo patterns (151, Prismatic Evolutions, Black Bolt,
# White Flare): two more separately-priced prints of the same card+number, on top of
# plain reverse holo and the regular/non-holo pull. A ball-pattern pull is always worth
# advertising, so unlike plain reverse a comp's title is trusted to say nothing when it
# doesn't have one - see _title_pattern below.
_POKE_BALL_RE = re.compile(r"\bpoke\s*-?\s*ball\b", re.IGNORECASE)
_MASTER_BALL_RE = re.compile(r"\bmaster\s*-?\s*ball\b", re.IGNORECASE)
# Distinct, materially pricier prints of the same card+number. A Shadowless Base Set
# Charmander runs $6-90 against $0.99-4 for the Unlimited print we actually hold.
_SPECIAL_PRINT_RE = re.compile(
    r"\bshadowless\b|\b1st\s*ed(?:ition)?\b|\bfirst\s*edition\b", re.IGNORECASE
)

# Below this many surviving comps, soft drops are restored (see module docstring).
# Matches the threshold research_card_active already uses for self-exclusion.
MIN_FILTERED_COMPS = 3


@dataclass(frozen=True)
class Verdict:
    """Why one comp was kept or dropped. `tier` is "" when kept."""
    keep: bool
    reason: str = ""
    tier: str = ""  # "hard" | "soft"


def _norm_num(tok: str) -> str:
    """'086' -> '86', 'SVP046' -> 'svp46'. Strips leading zeros from the digit run so
    the zero-padded forms sellers use ('102/086') compare equal to the catalog's."""
    tok = (tok or "").strip().lower()
    m = re.match(r"^([a-z]*)0*(\d+)$", tok)
    if not m:
        return tok
    return f"{m.group(1)}{m.group(2)}"


def _numeric_part(tok: str) -> str:
    """Trailing digit run of a card number, leading zeros stripped ('svp46' -> '46')."""
    m = re.search(r"(\d+)$", tok or "")
    return m.group(1).lstrip("0") or "0" if m else ""


def title_card_numbers(title: str) -> set[str]:
    """Every card number a title states, normalized. Includes both the full code and
    its bare numeric part, so a catalog number of 'SVP46' matches a title writing it as
    'SVP046', '46/191' or '#46'."""
    found: set[str] = set()
    for rx in (_SLASH_NUM_RE, _HASH_NUM_RE, _PROMO_NUM_RE):
        for m in rx.finditer(title or ""):
            norm = _norm_num(m.group(1))
            if norm:
                found.add(norm)
                num = _numeric_part(norm)
                if num:
                    found.add(num)
    return found


def distinct_card_count(title: str) -> int:
    """How many different cards a title appears to name, by numeric part only.
    '102/086' is one card; '33/108 & 8/18' is two; '#112 and #116' is two."""
    nums = set()
    for rx in (_SLASH_NUM_RE, _HASH_NUM_RE):
        for m in rx.finditer(title or ""):
            num = _numeric_part(_norm_num(m.group(1)))
            if num:
                nums.add(num)
    return len(nums)


def is_multi_card(title: str) -> bool:
    return distinct_card_count(title) > 1 or bool(_LOT_RE.search(title or ""))


def is_graded(title: str, condition: str | None) -> bool:
    if (condition or "").strip().lower() in GRADED_CONDITIONS:
        return True
    return bool(_GRADED_TITLE_RE.search(title or ""))


def is_defect_variant(title: str) -> bool:
    key = (title or "").lower()
    return any(k in key for k in EXCLUDED_TITLE_KEYWORDS + COMP_DEFECT_KEYWORDS)


def is_foreign_market(title: str, condition: str | None) -> bool:
    """Foreign either way it shows up: a localized condition string (a non-US seller,
    even when the title is in English) or a title naming a non-English print."""
    if (condition or "").strip().lower() not in ENGLISH_CONDITIONS:
        return True
    return bool(_FOREIGN_PRINT_RE.search(title or ""))


def _title_pattern(title: str) -> str | None:
    """Which ball pattern, if any, a title claims. Master Ball checked first: a title
    naming both ("Poke Ball & Master Ball set") is a multi-card bundle already caught
    upstream, but if one ever slipped through, the pricier claim is the one that must
    not be mistaken for the cheaper one."""
    if _MASTER_BALL_RE.search(title):
        return "master_ball"
    if _POKE_BALL_RE.search(title):
        return "poke_ball"
    return None


def evaluate_comp(comp: dict, identity: dict | None) -> Verdict:
    """Judge one parsed Browse result against the card being priced.

    comp     - a parse_active_item() dict (title, condition, ...)
    identity - cards.card_identity() output: {name, number, set_name, reverse,
               pattern}, or None when the card could not be resolved, in which case
               only the identity-free hard checks apply.
    """
    title = comp.get("title") or ""
    condition = comp.get("condition") or ""

    # --- Hard: definitely not the thing we're pricing ---------------------------
    if is_graded(title, condition):
        return Verdict(False, "graded", "hard")
    if is_multi_card(title):
        return Verdict(False, "multi_card", "hard")
    if is_defect_variant(title):
        return Verdict(False, "defect_variant", "hard")
    if is_foreign_market(title, condition):
        return Verdict(False, "foreign_market", "hard")

    if not identity:
        return Verdict(True)

    # --- Soft: looks like a different card or a different print -----------------
    name = (identity.get("name") or "").strip()
    primary = re.split(r"[\s\-]+", name)[0].lower() if name else ""
    if primary and not re.search(rf"\b{re.escape(primary)}", title.lower()):
        return Verdict(False, "name_mismatch", "soft")

    expected = identity.get("number") or ""
    if expected:
        wanted = {_norm_num(expected), _numeric_part(_norm_num(expected))} - {""}
        stated = title_card_numbers(title)
        # A title that states no number at all is kept: plenty of legitimate listings
        # omit it, and the name check above already ran.
        if stated and wanted and not (wanted & stated):
            return Verdict(False, "number_mismatch", "soft")

    # A ball-pattern title (below) also usually says "reverse holo", but not always -
    # sellers who have the rarer pull tend to lead with its name and can drop the
    # generic word entirely. Skip the plain check for those titles rather than have it
    # reject a real Poke Ball / Master Ball comp for not also saying "reverse"; the
    # pattern check just below is the one that actually judges them.
    title_pattern = _title_pattern(title)

    # bool() on both sides is load-bearing: re.search returns a Match or None, and
    # `Match != False` is always True, which silently rejected every comp in every pool
    # and made the soft-restore path fire universally.
    if title_pattern is None and bool(_REVERSE_RE.search(title)) != bool(identity.get("reverse")):
        # Reverse holos and their regular counterparts are separately priced prints.
        return Verdict(False, "reverse_mismatch", "soft")

    if title_pattern != identity.get("pattern"):
        # Each ball pattern trades separately from the other and from a plain reverse
        # holo of the same card - see _BALL_PATTERN_TOKENS in cards.py.
        return Verdict(False, "pattern_mismatch", "soft")

    if bool(_POKEMON_CENTER_RE.search(title)) != bool(identity.get("pokemon_center")):
        return Verdict(False, "pokemon_center_mismatch", "soft")

    if _SPECIAL_PRINT_RE.search(title) and not _SPECIAL_PRINT_RE.search(name):
        return Verdict(False, "special_print", "soft")

    return Verdict(True)


def filter_comps(
    comps: list[dict], identity: dict | None, min_comps: int = MIN_FILTERED_COMPS
) -> tuple[list[dict], dict]:
    """Split a comp pool into what's usable and a record of what was dropped and why.

    Returns (kept, quality). `quality` is persisted to active_price_snapshots.pool_quality
    so pool contamination is visible per card over time rather than only showing up as a
    suggestion that looks wrong.

    Hard drops are never restored. Soft drops are restored together, not one by one,
    when keeping them would leave fewer than `min_comps` - partial restoration would
    make the pool depend on the order the results happened to arrive in.
    """
    kept: list[dict] = []
    soft_dropped: list[dict] = []
    reasons: dict[str, int] = {}

    for comp in comps:
        verdict = evaluate_comp(comp, identity)
        if verdict.keep:
            kept.append(comp)
            continue
        reasons[verdict.reason] = reasons.get(verdict.reason, 0) + 1
        if verdict.tier == "soft":
            soft_dropped.append(comp)

    restored = False
    if len(kept) < min_comps and soft_dropped:
        kept = kept + soft_dropped
        restored = True

    return kept, {
        "in": len(comps),
        "kept": len(kept),
        "dropped": len(comps) - len(kept),
        "reasons": reasons,
        "soft_restored": restored,
        # Whether a real card was recovered, not merely whether an identity dict exists:
        # a free-text search yields flags but no name or number, so the identity-based
        # checks below it are mostly inert and the pool deserves to say so.
        "identified": bool(identity and identity.get("parsed", True)),
    }
