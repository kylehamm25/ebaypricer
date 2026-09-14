from __future__ import annotations

import json
import os
import re
import unicodedata
import time
from dataclasses import dataclass, field
from typing import Any

import requests
from rapidfuzz import fuzz, process as fuzz_process

from .paths import CACHE_FILE, CARD_QUERY_LOOKUP, PRICING_CACHE, TCGDEX_SET_MAP

GITHUB_BASE = "https://raw.githubusercontent.com/PokemonTCG/pokemon-tcg-data/master"
TCGDEX_API = "https://api.tcgdex.net/v2/en"

POKEMON_NOISE = {
    "pokemon", "tcg", "card", "cards", "nm", "lp", "mp", "hp",
    "near", "mint", "lightly", "played", "damaged", "rare", "ultra", "holo",
    "holofoil", "reverse", "reverseholofoil", "full", "art",
    "tag", "team", "prism", "star", "break", "trainer",
    "gallery", "galarian", "radiant", "amazing", "shiny", "baby",
    "promo", "black", "white", "sword", "shield", "scarlet", "violet",
    "standard", "envelope", "lot", "lot of", "mixed", "common", "uncommon",
    "secret", "illustration", "anime", "japanese", "english", "first", "edition",
    "1st", "ed", "foil", "non", "hgss", "dp",
    "pl", "pop", "np", "poke", "ball", "energy", "basic", "stage",
    "level", "ancient", "future", "tera",
}

SET_ABBREV = {
    "pal": "paldea evolved",
    "svi": "scarlet violet",
    "obf": "obsidian flames",
    "par": "paradox rift",
    "paf": "paldean fates",
    "tef": "temporal forces",
    "twm": "twilight masquerade",
    "scr": "stellar crown",
    "ssp": "surging sparks",
    "pre": "prismatic evolutions",
    "jtg": "journey together",
    "mew": "151",
    "crz": "crown zenith",
    "sit": "silver tempest",
    "lor": "lost origin",
    "asr": "astral radiance",
    "brs": "brilliant stars",
    "fst": "fusion strike",
    "evs": "evolving skies",
    "cre": "chilling reign",
    "bst": "battle styles",
    "viv": "vivid voltage",
    "daa": "darkness ablaze",
    "rcl": "rebel clash",
    "ssh": "sword shield",
    "cec": "cosmic eclipse",
    "unm": "unified minds",
    "unb": "unbroken bonds",
    "lot": "lost thunder",
    "ces": "celestial storm",
    "fli": "forbidden light",
    "gri": "guardians rising",
    "sum": "sun moon",
    "det": "detective pikachu",
    "cel": "celestial storm",
    "drm": "dragon majesty",
}

SET_PREFIX_RE = re.compile(r"\b(sv\d{2}|swsh\d{1,2}|bw\d{1,2}|xy\d{1,2}|sm\d{1,2})\b", re.IGNORECASE)
CARD_NUM_RE = re.compile(r"\b(\d{1,4}/\d{2,4})\b")

PROMO_NUM_RE = re.compile(r"\b(SVP|MEP|SWSH|BW|SM|XY|DP|HGSS|POP)\s*(\d{1,4})\b", re.IGNORECASE)

_PROMO_PREFIX_MAP: dict[str, tuple[str, int]] = {
    "svp":  ("svp",   0),
    "mep":  ("svp",   0),
    "swsh": ("swshp", 3),
    "bw":   ("bwp",   0),
    "sm":   ("smp",   0),
    "xy":   ("xyp",   0),
    "dp":   ("dpp",   0),
    "hgss": ("hsp",   0),
    "pop":  ("pop",   0),
}

HEADERS = ["Card"]

# How long a downloaded card catalog stays usable before ensure_loaded() refreshes it.
# New sets and promos appear upstream far faster than this; a fortnight keeps recent
# promos findable without downloading ~20k cards on any regular cadence.
CACHE_MAX_AGE_DAYS = 14

_PROMO_SET_TO_PREFIX = {
    "svp": "SVP",
}

# Cards the upstream pokemon-tcg-data repo (GITHUB_BASE) is simply missing. Found by
# scanning each Black Star Promos series for a gap in its own numbering - swshp runs
# 1-307 but only had 304 cards, with 299/300/301 absent between "Hisuian Zoroark
# VSTAR Promo" (298) and "Klara Promo" (302). Verified against Pokemon's own TCG card
# database (pokemon.com/us/pokemon-tcg/pokemon-cards/series/swshp/SWSH2{99,300,301}/,
# duplicated by TCGplayer/Cardmarket/pkmn.gg) rather than guessed from the gap alone -
# a wrong name here would be a wrong catalog entry, not just a missing one.
#
# Appended after every fetch in _build_cache() rather than hand-patched into
# data/cards_cache.json, because that file is regenerated wholesale (14-day TTL, or a
# manual rebuild) and a hand-edit would be silently lost on the next one. Safe to
# leave in place if upstream ever adds these itself - _build_cache() below only
# appends an id that didn't already come from the fetch.
_MISSING_PROMO_CARDS: list[dict] = [
    {
        "id": "swshp-SWSH299", "name": "Jirachi V", "number": "SWSH299",
        "rarity": "Promo", "supertype": "Pokémon", "subtypes": ["Basic", "V"],
        "set_id": "swshp", "set_name": "SWSH Black Star Promos",
        "set_series": "Sword & Shield", "set_release": "2019/11/15",
    },
    {
        "id": "swshp-SWSH300", "name": "Unown V", "number": "SWSH300",
        "rarity": "Promo", "supertype": "Pokémon", "subtypes": ["Basic", "V"],
        "set_id": "swshp", "set_name": "SWSH Black Star Promos",
        "set_series": "Sword & Shield", "set_release": "2019/11/15",
    },
    {
        "id": "swshp-SWSH301", "name": "Lugia V", "number": "SWSH301",
        "rarity": "Promo", "supertype": "Pokémon", "subtypes": ["Basic", "V"],
        "set_id": "swshp", "set_name": "SWSH Black Star Promos",
        "set_series": "Sword & Shield", "set_release": "2019/11/15",
    },
]

RARITY_ABBREV = {
    "illustration rare": "IR",
    "special illustration rare": "SIR",
}

# Keywords found in listing titles that signal a particular rarity, used to
# disambiguate between multiple prints of the same card name/number.
RARITY_SIGNALS: dict[str, str] = {
    "special illustration rare": "Special Illustration Rare",
    "sir": "Special Illustration Rare",
    "illustration rare": "Illustration Rare",
    "art rare": "Illustration Rare",
    "ir": "Illustration Rare",
    "ar": "Illustration Rare",
    "hyper rare": "Hyper Rare",
    "secret rare": "Secret Rare",
    "double rare": "Double Rare",
    "ultra rare": "Ultra Rare",
    "shiny rare": "Rare Shiny",
    "vmax": "Rare Holo VMAX",
    "vstar": "Rare Holo VSTAR",
}

# Words that indicate a title is plausibly describing a Pokemon TCG card.
# Used to guard the fuzzy-match fallback against unrelated listings (e.g.
# shoes, apparel) that would otherwise get force-matched to a random card.
_SIGNAL_RE = re.compile(
    r"\b(pokemon|pok[eé]mon|tcg|holo|holofoil|promo|reverse|vmax|vstar|gx|ex|"
    r"illustration|rare|common|uncommon|secret|trainer|energy|basic|stage|"
    r"radiant|amazing|shiny|edition|unlimited|nm|lp|mp|hp|mint|played)\b",
    re.IGNORECASE,
)

_STOPWORDS = {"with", "and", "the", "for", "from", "in", "of", "to", "a", "an", "its"}

_REVERSE_RE = re.compile(r'\breverse\b', re.IGNORECASE)

# Digit run not glued to other digits, allowing letter prefixes/suffixes,
# e.g. matches "010" inside "SV010" or "45" inside "XY45".
_BARE_NUM_RE = re.compile(r"(?<!\d)0*(\d{1,4})(?!\d)")


# Symbols the catalog uses to mark card variants. Folded to the words people actually
# type: nobody searches for "Pikachu δ" by pasting a delta.
_SYMBOL_WORDS = {
    "δ": " delta ", "α": " alpha ", "β": " beta ", "γ": " gamma ",
    "★": " star ", "◇": " prism star ", "♂": " male ", "♀": " female ",
}

# Every dash variant the catalog contains, plus the plain hyphen. "HS—Undaunted" uses an
# em dash (290 of them across the catalog - more common than accented characters), which
# is not on a keyboard, so it has to compare equal to a space or a hyphen.
_DASH_RE = re.compile("[\u2010-\u2015-]")


def _fold(text: str) -> str:
    """Reduce a string to what someone would plausibly type.

    Strips the typographic differences between how the catalog stores a name and how it
    gets typed: accents ("Pokémon" -> "pokemon"), dashes ("HS—Undaunted" -> "hs
    undaunted"), and variant symbols ("Pikachu δ" -> "pikachu delta"). Applied to both
    the search index and the query, so the two always meet in the same alphabet.
    """
    s = (text or "").lower()
    for sym, word in _SYMBOL_WORDS.items():
        if sym in s:
            s = s.replace(sym, word)
    # NFKD splits an accented character into base + combining mark; dropping the marks
    # leaves the bare letter.
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = _DASH_RE.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip()


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9\s]", "", s.lower()).strip()


def _norm_name(s: str) -> str:
    """Normalize a card name/title fragment for loose comparison: lowercase,
    treat hyphens the same as spaces (handles 'Tyranitar-EX' vs 'Tyranitar EX'),
    and collapse whitespace."""
    s = re.sub(r"[-\u2013\u2014]", " ", s.lower())
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _name_in_title(name: str, title: str) -> bool:
    """Check whether a card name appears in a listing title, tolerant of
    hyphen/space differences (e.g. DB name 'Tyranitar-EX' should match a
    title written as 'Tyranitar EX')."""
    name_n = _norm_name(name)
    title_n = _norm_name(title)
    if not name_n:
        return False
    return re.search(r"\b" + re.escape(name_n) + r"\b", title_n) is not None


def _numeric_suffix(num_str: str) -> str:
    """Extract the trailing digit run of a card number field (e.g. 'SV010' ->
    '10', '042' -> '42'), stripped of leading zeros."""
    m = re.search(r"(\d+)$", num_str or "")
    if not m:
        return ""
    return m.group(1).lstrip("0") or "0"


def _extract_bare_numbers(title: str) -> set[str]:
    """Pull standalone-ish digit runs out of a title (leading zeros stripped),
    tolerant of letter prefixes like 'SV010' or 'ME012'."""
    nums = set()
    for m in _BARE_NUM_RE.finditer(title):
        n = m.group(1).lstrip("0") or "0"
        nums.add(n)
    return nums


def _rarity_signal(title: str) -> str | None:
    """Look for a rarity-indicating keyword/abbreviation in the title (as a
    standalone word), returning the canonical rarity string it implies."""
    title_l = title.lower()
    # Check longer/more specific phrases first so e.g. "special illustration
    # rare" wins over "illustration rare".
    for phrase in sorted(RARITY_SIGNALS, key=len, reverse=True):
        if re.search(r"\b" + re.escape(phrase) + r"\b", title_l):
            return RARITY_SIGNALS[phrase]
    return None



def _significant_tokens(s: str) -> list[str]:
    skip = _STOPWORDS | POKEMON_NOISE
    return [t for t in re.split(r"\W+", s.lower()) if len(t) > 3 and t not in skip]


def _expand_set_abbrevs(title_norm: str) -> str:
    result = title_norm
    for abbr, full in SET_ABBREV.items():
        result = result.replace(abbr, full)
    m = SET_PREFIX_RE.search(title_norm)
    if m:
        prefix = m.group(1).lower()
        if prefix not in SET_ABBREV:
            series_map = {"sv": "scarlet violet", "swsh": "sword shield", "sm": "sun moon", "xy": "xy", "bw": "black white"}
            for series_prefix, series_name in series_map.items():
                if prefix.startswith(series_prefix):
                    result = result.replace(prefix, series_name)
                    break
    return result


def _load_json(path: str) -> dict:
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save_json(path: str, data: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp, path)


def _fetch_tcg_set_map() -> dict[str, str]:
    path = TCGDEX_SET_MAP
    if os.path.isfile(path):
        return _load_json(path)
    print("  Fetching TCGdex set map for pricing ...")
    resp = requests.get(f"{TCGDEX_API}/sets", timeout=30)
    resp.raise_for_status()
    mapping: dict[str, str] = {}
    for s in resp.json():
        name = s.get("name", "").lower()
        mapping[name] = s["id"]
    _save_json(path, mapping)
    return mapping


_SET_MAP: dict[str, str] | None = None


def _get_set_map() -> dict[str, str]:
    global _SET_MAP
    if _SET_MAP is None:
        _SET_MAP = _fetch_tcg_set_map()
    return _SET_MAP


def _lookup_price(card_name: str, set_name: str, number: str, variant: str) -> float | None:
    set_map = _get_set_map()
    tcg_set_id = set_map.get(set_name.lower())
    if not tcg_set_id:
        return None

    # TCGdex's local card IDs use the number as printed, not zero-padded (e.g.
    # "dv1-6", not "dv1-006" - the latter 404s). Confirmed against the live API.
    card_id = f"{tcg_set_id}-{number}"

    cache = _load_json(PRICING_CACHE)
    if card_id in cache:
        prices = cache[card_id]
    else:
        url = f"{TCGDEX_API}/cards/{card_id}"
        try:
            resp = requests.get(url, timeout=10)
            if resp.status_code != 200:
                cache[card_id] = None
                _save_json(PRICING_CACHE, cache)
                return None
            data = resp.json()
            pricing = data.get("pricing", {}) or {}
        except requests.RequestException:
            cache[card_id] = None
            _save_json(PRICING_CACHE, cache)
            return None

        tcg = pricing.get("tcgplayer") if isinstance(pricing, dict) else None
        if tcg and isinstance(tcg, dict):
            # TCGdex's variant keys aren't consistently cased/hyphenated (e.g.
            # "reverse-holofoil" rather than "reverseHolofoil") - normalize every
            # key present so the lookup below matches regardless of TCGdex's spelling.
            prices = {}
            for v, info in tcg.items():
                if isinstance(info, dict) and info.get("marketPrice") is not None:
                    norm_key = v.lower().replace("-", "").replace(" ", "")
                    prices[norm_key] = info["marketPrice"]
        else:
            prices = {}
        cache[card_id] = prices if prices else None
        _save_json(PRICING_CACHE, cache)
        time.sleep(0.1)

    if not prices:
        return None

    variant_key = variant.lower().replace(" ", "").replace("-", "")
    for key in [variant_key, "holofoil", "normal", "reverseholofoil"]:
        if key in prices and prices[key] is not None:
            return round(float(prices[key]), 2)
    return None


@dataclass
class CardDatabase:
    cards: list[dict[str, Any]] = field(default_factory=list)
    by_number: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    name_list: list[str] = field(default_factory=list)
    name_to_card: dict[str, dict[str, Any]] = field(default_factory=dict)
    name_to_cards: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    name_list_by_len: list[str] = field(default_factory=list)
    # (name_lower, haystack, card) per printing, built once. Powers search_cards.
    search_index: list[tuple[str, str, dict[str, Any]]] = field(default_factory=list)
    _loaded: bool = False

    def ensure_loaded(self) -> None:
        if self._loaded:
            return
        if os.path.isfile(CACHE_FILE):
            age_days = (time.time() - os.path.getmtime(CACHE_FILE)) / 86400
            if age_days > CACHE_MAX_AGE_DAYS:
                # Cards are added upstream constantly - new promo sets especially. This
                # used to only rebuild when the file was MISSING, so a cache built once
                # was kept forever: at 30 days old it had 165 Scarlet & Violet promos
                # (SVP210 did not exist) and no Mega Evolution promo set at all, and
                # those cards were simply unfindable.
                print(f"  Card cache is {age_days:.0f} days old -- refreshing (~1 min) ...")
                try:
                    self._build_cache()
                except Exception as e:
                    # A refresh failure must not take the catalog down with it. The old
                    # cache is still on disk and still mostly right.
                    print(f"  Refresh failed ({e}) -- using the existing cache")
                    self._load_cache()
            else:
                print(f"  Loading card database from cache ({age_days:.0f} days old) ...")
                self._load_cache()
        else:
            print("  No card cache -- downloading from GitHub (~1 min) ...")
            self._build_cache()
        self._build_index()
        self._loaded = True

    def _build_cache(self) -> None:
        sets = self._fetch_sets()
        all_cards: list[dict] = []
        total = len(sets)

        for i, s in enumerate(sets, 1):
            sid = s["id"]
            sname = s.get("name", sid)
            series = s.get("series", "")
            release = s.get("releaseDate", "")
            cards = self._fetch_set_cards(sid)
            for c in cards:
                all_cards.append({
                    "id": c.get("id", ""),
                    "name": c.get("name", ""),
                    "number": c.get("number", ""),
                    "rarity": c.get("rarity", ""),
                    "supertype": c.get("supertype", ""),
                    "subtypes": c.get("subtypes", []),
                    # Elemental type(s) - "Fire", "Grass", ... - present only on
                    # Pokemon cards; Trainer and Energy cards carry none upstream.
                    # Only card_type_label() reads this, to sort/group the Inventory
                    # page by "Fire"/"Grass"/.../"Trainer"/"Energy".
                    "types": c.get("types") or [],
                    "set_id": sid,
                    "set_name": sname,
                    "set_series": series,
                    # "YYYY/MM/DD" from the set record. Cards carry no date of their own,
                    # and search_cards needs one to put recent printings first.
                    "set_release": release,
                })
            if i % 25 == 0:
                print(f"    ... {i}/{total} sets ({len(all_cards)} cards)")

        have_ids = {c["id"] for c in all_cards}
        all_cards.extend(c for c in _MISSING_PROMO_CARDS if c["id"] not in have_ids)

        # Written once, at the end, and atomically (_save_cache writes a temp file then
        # os.replace). Previously this also saved every 25 sets, which was fine when a
        # build only ever ran against a missing cache - but now that age can trigger a
        # rebuild, a mid-download failure would leave a TRUNCATED catalog carrying a
        # fresh mtime, so it would look current and never retry.
        self._save_cache(all_cards)
        self.cards = all_cards
        print(f"    Cached {len(all_cards)} cards from {total} sets")

    def _fetch_sets(self) -> list[dict]:
        resp = requests.get(f"{GITHUB_BASE}/sets/en.json", timeout=30)
        resp.raise_for_status()
        return resp.json()

    def _fetch_set_cards(self, set_id: str) -> list[dict]:
        resp = requests.get(f"{GITHUB_BASE}/cards/en/{set_id}.json", timeout=30)
        resp.raise_for_status()
        return resp.json()

    def _save_cache(self, cards: list[dict]) -> None:
        os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
        tmp = CACHE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cards, f, ensure_ascii=False)
        os.replace(tmp, CACHE_FILE)

    def _load_cache(self) -> None:
        with open(CACHE_FILE, encoding="utf-8") as f:
            self.cards = json.load(f)

    def _build_index(self) -> None:
        for c in self.cards:
            num = c["number"]
            self.by_number.setdefault(num, []).append(c)
            snum = f"{c['set_id']}-{num}"
            self.by_number.setdefault(snum, []).append(c)
            self.name_to_card[c["name"]] = c
            self.name_to_cards.setdefault(c["name"], []).append(c)

        seen = set()
        for c in self.cards:
            key = _norm(c["name"])
            if key not in seen:
                seen.add(key)
                self.name_list.append(c["name"])

        self.name_list_by_len = sorted(self.name_list, key=len, reverse=True)

        # One lowercase haystack per printing, so search_cards can scan without
        # rebuilding strings on every keystroke. Number is included twice - bare ("4")
        # and set-qualified ("base-4") - because people search both ways.
        for c in self.cards:
            name_l = _fold(c.get("name") or "")
            self.search_index.append((
                name_l,
                _fold(" ".join((
                    c.get("name") or "",
                    c.get("set_name") or "",
                    c.get("set_series") or "",
                    c.get("rarity") or "",
                    c.get("number") or "",
                    f"{c.get('set_id', '')}-{c.get('number', '')}",
                ))),
                c,
            ))

    def search_cards(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        """Autocomplete over every printing. Purely local - reads the cached card DB and
        makes no network call, which is what lets the valuation UI query on each
        keystroke without touching a rate-limited API.

        Every whitespace-separated token must appear somewhere in the printing's
        haystack, so "charizard base", "charizard 4/102" and "gourgeist ex chaos" all
        narrow the way a person expects. Ranking favours a name the query actually
        starts, because "Charizard" should not be buried under "Charizard & Braixen".
        """
        q = _fold(query)
        if not q:
            return []
        # Card numbers are PRINTED as "4/102" but stored as just "4", so reduce an
        # x/y token to its numerator. Splitting on "/" instead would search for "102",
        # which appears nowhere and silently returns nothing.
        tokens = []
        for raw in q.split():
            m = re.fullmatch(r"([a-z]*\d+)\s*/\s*[a-z]*\d+", raw)
            tokens.append(m.group(1) if m else raw)
        if not tokens:
            return []

        # Tokens with digits are matched on a word boundary, alphabetic ones as a plain
        # substring. A bare "4" as a substring hits any set/rarity that merely contains
        # a 4, which buried the actual 4/102 Charizard; but partial words still need to
        # match loosely so "chariz" finds Charizard while the user is still typing.
        matchers = []
        for t in tokens:
            if any(ch.isdigit() for ch in t):
                matchers.append(re.compile(rf"(?<![a-z0-9]){re.escape(t)}(?![a-z0-9])").search)
            else:
                matchers.append(lambda hay, t=t: t in hay)

        scored: list[tuple[tuple, dict[str, Any]]] = []
        for name_l, hay, card in self.search_index:
            if not all(m(hay) for m in matchers):
                continue
            # Lower sorts first.
            # Match quality still leads - a newer set must not float a worse name match
            # above an exact one. Release date replaces the old alphabetical set tiebreak,
            # so among equally good matches the most recent printing comes first.
            rank = (
                0 if name_l == q else 1 if name_l.startswith(tokens[0]) else 2,
                0 if (card.get("number") or "").lower() in tokens else 1,
                len(name_l),
                _release_key(card),
                card.get("number") or "",
            )
            scored.append((rank, card))
            # Scanning all 20k printings is cheap, but building a huge list is not.
            if len(scored) > 400:
                break

        scored.sort(key=lambda x: x[0])
        return [c for _, c in scored[:limit]]

    def match(self, title: str) -> dict | None:
        result = self._match_by_number(title)
        if result:
            return result
        result = self._match_by_promo_number(title)
        if result:
            return result
        result = self._match_exact(title)
        if result:
            return result
        result = self._match_fuzzy(title)
        return result

    def _title_matches_set(self, title_norm: str, set_name: str) -> bool:
        if not set_name:
            return False
        sn = set_name.lower()
        # Word-boundary phrase match, not naive substring -- otherwise a set
        # named "Dragon" would incorrectly "match" inside "Dragons Exalted".
        if re.search(r'\b' + re.escape(sn) + r'\b', title_norm):
            return True
        expanded = _expand_set_abbrevs(title_norm)
        if expanded != title_norm and re.search(r'\b' + re.escape(sn) + r'\b', expanded):
            return True
        tokens = _significant_tokens(set_name)
        if len(tokens) >= 2:
            return sum(bool(re.search(r'\b' + re.escape(t) + r'\b', title_norm)) for t in tokens) >= 2
        return bool(tokens) and bool(re.search(r'\b' + re.escape(tokens[0]) + r'\b', title_norm))

    def _disambiguate(self, candidates: list[dict], title: str) -> dict | None:
        """Narrow a list of same-name/same-number candidate cards down to one,
        using set name, series, an explicit bare number, or a rarity keyword
        found in the listing title. Returns None if it can't confidently
        settle on a single candidate (better to admit uncertainty than to
        silently guess the wrong print)."""
        if not candidates:
            return None
        if len(candidates) == 1:
            return dict(candidates[0])

        desc = _norm(title)

        by_set = [c for c in candidates if self._title_matches_set(desc, c.get("set_name", ""))]
        if len(by_set) == 1:
            return dict(by_set[0])

        pool = by_set if by_set else candidates

        by_series = [c for c in pool if self._title_matches_set(desc, c.get("set_series", ""))]
        if len(by_series) == 1:
            return dict(by_series[0])

        pool = by_series if by_series else pool

        bare_nums = _extract_bare_numbers(title)
        by_num = [c for c in pool if _numeric_suffix(c.get("number", "")) in bare_nums]
        if len(by_num) == 1:
            return dict(by_num[0])
        if by_num:
            pool = by_num

        rarity = _rarity_signal(title)
        if rarity:
            by_rarity = [c for c in pool if c.get("rarity", "") == rarity]
            if len(by_rarity) == 1:
                return dict(by_rarity[0])
            if by_rarity:
                pool = by_rarity

        if len(pool) == 1:
            return dict(pool[0])
        return None

    def _match_exact(self, title: str) -> dict | None:
        for name in self.name_list_by_len:
            if _name_in_title(name, title):
                candidates = self.name_to_cards.get(name, [])
                if not candidates:
                    return None
                result = self._disambiguate(candidates, title)
                if result:
                    return result
                # Species is confirmed by an exact literal name match even if we
                # can't pin the exact print/rarity -- that's still far better than
                # falling through to fuzzy matching, which has no name anchor at
                # all and can land on a completely different Pokemon. Matches the
                # fallback already used by _match_by_number/_match_by_promo_number/
                # _match_fuzzy below.
                return dict(candidates[0])
        return None

    @staticmethod
    def _subtypes_match(title: str, subtypes: list[str]) -> bool:
        if not subtypes:
            return True
        title_lower = title.lower()
        words = set(re.findall(r"[a-z0-9]+", title_lower))
        for st in subtypes:
            if st.lower() in words:
                return True
        return False

    def _match_by_number(self, title: str) -> dict | None:
        m = CARD_NUM_RE.search(title)
        if not m:
            return None
        num_part = m.group(1).split("/")[0].lstrip("0")
        candidates = self.by_number.get(num_part, [])
        if not candidates:
            return None
        if len(candidates) == 1:
            return dict(candidates[0])

        # Priority 1: the card's actual name literally appears in the title.
        # This is the strongest signal and should win over set-name guessing
        # (a listing can mention several set/series words that only weakly
        # imply the right print, but if "Deino" is in the title, the card is
        # Deino -- not some unrelated same-numbered card from a set whose
        # name happens to overlap).
        name_matches = [c for c in candidates if _name_in_title(c["name"], title)]
        if name_matches:
            result = self._disambiguate(name_matches, title)
            if result:
                return result
            # Species is confirmed even if we can't pin the exact print --
            # that's still far better than guessing a different species.
            return dict(name_matches[0])

        # Priority 2: no literal name match. Only trust a set/series match
        # here if it's unambiguous; otherwise we risk returning a
        # completely different Pokemon that happens to share a card number
        # and coincidentally-matching set text.
        return self._disambiguate(candidates, title)

    def _match_by_promo_number(self, title: str) -> dict | None:
        m = PROMO_NUM_RE.search(title)
        if not m:
            return None
        prefix = m.group(1).lower()
        digits_str = m.group(2)
        info = _PROMO_PREFIX_MAP.get(prefix)
        if not info:
            return None
        set_id, zfill = info

        if zfill > 0:
            padded = digits_str.zfill(zfill)
            full_num = f"{m.group(1).upper()}{padded}"
            candidates = self.by_number.get(full_num, [])
            if not candidates:
                return None
            name_matches = [c for c in candidates if _name_in_title(c["name"], title)]
            pool = name_matches if name_matches else candidates
            result = self._disambiguate(pool, title)
            if result:
                return result
            return dict(pool[0]) if name_matches else None

        stripped = digits_str.lstrip("0")
        compound = f"{set_id}-{stripped}"
        candidates = self.by_number.get(compound, [])
        if len(candidates) == 1:
            return dict(candidates[0])
        return None

    def _match_fuzzy(self, title: str) -> dict | None:
        # Fuzzy matching is the last resort and the riskiest stage -- only
        # attempt it if the title actually looks like it's describing a
        # Pokemon TCG card. Otherwise unrelated listings (shoes, apparel,
        # etc.) can end up force-matched to some random card purely because
        # a couple of words happen to overlap.
        if not _SIGNAL_RE.search(title) and not CARD_NUM_RE.search(title):
            return None

        clean = _norm(title)
        for noise in POKEMON_NOISE:
            clean = clean.replace(noise, " ")
        clean = re.sub(r"\s+", " ", clean).strip()
        if not clean or len(clean) < 3:
            return None
        # The scorer (rapidfuzz's default WRatio) is character-similarity based and
        # can score a name deceptively high purely off generic suffix tokens shared
        # by hundreds of names (e.g. "ex", "gx") even when the actual species word
        # doesn't appear anywhere in the title. Guard against that by requiring at
        # least one of the candidate's own distinguishing (non-generic) tokens to
        # literally appear in the title.
        query_tokens = set(_significant_tokens(title))

        results = fuzz_process.extract(
            clean, self.name_list, score_cutoff=80, limit=5,
        )
        for candidate_name, score, _ in results:
            candidate_tokens = _significant_tokens(candidate_name)
            if candidate_tokens and not query_tokens.intersection(candidate_tokens):
                continue
            cards = self.name_to_cards.get(candidate_name, [self.name_to_card[candidate_name]])
            cards = [c for c in cards if self._subtypes_match(title, c.get("subtypes", []))]
            if not cards:
                continue
            result = self._disambiguate(cards, title)
            if result:
                return result
            return dict(cards[0])
        return None


_DB: CardDatabase | None = None


def get_db() -> CardDatabase:
    global _DB
    if _DB is None:
        _DB = CardDatabase()
        _DB.ensure_loaded()
    return _DB


def _fmt_card(m: dict | None) -> str | None:
    if not m:
        return None
    parts = [m["name"]]
    r = m.get("rarity")
    ra = RARITY_ABBREV.get(r.lower()) if r else None
    if ra:
        parts.append(ra)
    num = m["number"]
    prefix = _PROMO_SET_TO_PREFIX.get(m.get("set_id", ""))
    if prefix and not num.startswith(prefix):
        num = f"{prefix}{num}"
    parts.append(num)
    parts.append(m["set_name"])
    return " ".join(parts)


# The number token _fmt_card synthesizes above is how the card is CATALOGUED, which
# is not always how it is SOLD. For the SVP promos the catalog stores a bare "13" and
# _fmt_card renders "SVP13", but the number is printed on the card - and written in
# listing titles - zero padded to three digits: "SVP 013", "SVP013". Searching the
# catalogued form finds nothing at all.
#
# Measured against live Browse results (raw hits, same query otherwise):
#     Miraidon SVP13   -> 0     Miraidon SVP013   -> 50
#     Squirtle SVP48   -> 1     Squirtle SVP048   -> 40
#     Tinkatink SVP25  -> 0     Tinkatink SVP025  -> 37
#     Annihilape SVP32 -> 2     Annihilape SVP032 -> 40
#
# Padding is applied ONLY to the prefixes this module synthesizes
# (_PROMO_SET_TO_PREFIX). SM/SWSH/XY/BW promo numbers arrive from the catalog already
# in their printed form ("SM26"), and padding those is actively harmful - "Tsareena
# SM26" returns 35 results, "Tsareena SM026" returns 0. SVP numbers of 100 and up are
# already three digits, so this is a no-op for them, which is why only the low-numbered
# SVP promos were ever affected.
_SYNTHESIZED_PREFIXES = tuple(_PROMO_SET_TO_PREFIX.values())
_PADDABLE_NUMBER_RE = re.compile(
    rf"^({'|'.join(_SYNTHESIZED_PREFIXES)})(\d{{1,3}})$"
)


def searchable_card_query(card_query: str) -> str:
    """A card_query rewritten the way sellers actually title the card.

    card_query itself must never change - it keys active_price_snapshots and
    active_listings.card - so this is a read-time transformation applied when building
    a marketplace search, not a different way to format cards. A string with nothing to
    rewrite comes back untouched, which is every non-promo card and every free-text
    valuation query.
    """
    if not card_query:
        return card_query
    out = []
    for token in card_query.split():
        m = _PADDABLE_NUMBER_RE.match(token)
        out.append(f"{m.group(1)}{int(m.group(2)):03d}" if m else token)
    return " ".join(out)


def format_card(match_result: dict | None, title: str | None = None) -> str | None:
    card_str = _fmt_card(match_result)
    if card_str and title and _REVERSE_RE.search(title):
        card_str += " Reverse"
    return card_str


# Card art CDN. The cached card DB deliberately doesn't store the upstream `images`
# field, but this CDN is addressable straight from set_id + number, so the URL is derived
# instead of bloating (and forcing a rebuild of) the 4.2 MB cache. Verified across
# vintage, modern, split-id, promo and letter-numbered promo sets.
CARD_IMAGE_BASE = "https://images.pokemontcg.io"


def _release_key(card: dict) -> int:
    """Sort key placing recently released sets first.

    Release dates are "YYYY/MM/DD", which is already lexicographically ordered, so the
    punctuation is stripped and the result negated - Python sorts ascending, and negating
    turns that into newest-first. Cards from a cache built before set_release existed
    yield 0, which sorts AFTER every real date rather than jumping to the top.
    """
    raw = (card.get("set_release") or "").replace("/", "").replace("-", "")
    return -int(raw) if raw.isdigit() else 0


def card_image_url(card: dict | None) -> str | None:
    """Art URL for a catalog card dict (needs set_id + number)."""
    if not card:
        return None
    set_id, number = card.get("set_id"), card.get("number")
    if not set_id or not number:
        return None
    return f"{CARD_IMAGE_BASE}/{set_id}/{number}.png"


def find_catalog_card(card_query: str) -> dict | None:
    """Resolve a flat card_query string back to the catalog entry it came from.

    Needed because card_query carries the set NAME ("Base") while the art URL needs the
    set ID ("base1"), and card_identity() only recovers the former. Matching is tolerant
    of the two ways _fmt_card() rewrites things on the way out: it can insert a rarity
    abbreviation into the name, and it prefixes promo numbers (catalog "46" is formatted
    as "SVP46"), so the number is compared on its trailing digits as well as verbatim.
    """
    ident = card_identity(card_query)
    if not ident or not ident.get("name"):
        return None
    db = get_db()

    name = ident["name"]
    candidates = db.name_to_cards.get(name) or []
    if not candidates:
        target = _norm_name(name)
        candidates = [c for c in db.cards if _norm_name(c.get("name", "")) == target]
    if not candidates:
        return None

    want_set = _norm_name(ident.get("set_name") or "")
    want_num = (ident.get("number") or "").lower()
    want_suffix = _numeric_suffix(want_num)

    for card in candidates:
        if _norm_name(card.get("set_name", "")) != want_set:
            continue
        num = (card.get("number") or "").lower()
        if num == want_num or (want_suffix and _numeric_suffix(num) == want_suffix):
            return card
    return None


def image_url_for_query(card_query: str) -> str | None:
    """Art URL straight from a card_query string. None when the card can't be resolved."""
    return card_image_url(find_catalog_card(card_query))


def card_type_label(card_query: str | None) -> str | None:
    """What to sort/group a card by: its elemental type ("Fire", "Grass", ...) for a
    Pokemon, or the supertype itself ("Trainer", "Energy") for anything else.

    None when the card can't be resolved (sealed/bulk/free-text rows, same as
    `image_url_for_query`), or - for a Pokemon whose printing predates the `types`
    field being cached - when the type simply isn't known yet; CACHE_MAX_AGE_DAYS
    picks it up on the next scheduled catalog refresh with no other change needed.
    Only ever the first listed type: a handful of Pokemon carry two, and this is a
    single sort bucket, not a full type chart.
    """
    card = find_catalog_card(card_query) if card_query else None
    if not card:
        return None
    supertype = card.get("supertype") or ""
    if supertype and supertype != "Pokémon":
        return supertype
    types = card.get("types") or []
    return types[0] if types else None


# Pokemon Center is a distribution channel, not a set: its promos carry the same card
# name and number as the ordinary print but trade separately. Detected off the whole
# card_query rather than the parsed set name, because on a custom search the phrase can
# land anywhere in the string the seller typed.
_POKEMON_CENTER_RE = re.compile(r"pok[eé]mon\s*center|poke\s*center|pokecenter", re.IGNORECASE)


_BALL_PATTERN_TOKENS = {("poke", "ball"): "poke_ball", ("master", "ball"): "master_ball"}


def card_identity(card_query: str) -> dict | None:
    """Structured identity behind a flat card_query string: name, set_name, number and
    which reverse-family print it is (plain reverse holo, or a Poke Ball / Master Ball
    pattern - see _BALL_PATTERN_TOKENS). Feeds comp_filter.evaluate_comp, which needs to
    know what card we're actually pricing before it can judge a search result.

    Prefers the same title-anchored match enrich_rows() stashed (see lookup_market_price
    - re-deriving from the formatted string is lossy, because the bare number loses its
    "x/y" anchor). Falls back to parsing the flat string for cards that predate the
    cache, since a parsed identity still catches most mismatches and None disables every
    identity-dependent check.
    """
    if not card_query:
        return None

    pokemon_center = bool(_POKEMON_CENTER_RE.search(card_query))

    entry = _load_json(CARD_QUERY_LOOKUP).get(card_query)
    if entry:
        return {
            "name": entry["name"],
            "set_name": entry["set_name"],
            "number": entry["number"],
            "reverse": entry.get("variant") == "reverseHolofoil",
            # The pipeline that populates CARD_QUERY_LOOKUP matches TCGdex's generic
            # variant names, which don't distinguish a ball pattern from a plain
            # reverse holo - so a listing title is still the only way to catch one.
            "pattern": None,
            "pokemon_center": pokemon_center,
            "parsed": True,
        }

    # Fallback: "<name> [RARITY] <number> <set name> [Reverse | Poke Ball | Master
    # Ball]". The number is the first token shaped like a card number, which is also
    # what separates name from set - so "Charizard ex SIR 199 151" resolves to number
    # 199 in set "151", not the reverse.
    tokens = card_query.split()
    pattern = None
    if len(tokens) >= 2 and (tokens[-2].lower(), tokens[-1].lower()) in _BALL_PATTERN_TOKENS:
        pattern = _BALL_PATTERN_TOKENS[(tokens[-2].lower(), tokens[-1].lower())]
        tokens = tokens[:-2]
    # A ball pattern IS a reverse-holo print - counted as reverse too so anything that
    # only checks the boolean (the TCGdex variant lookup in valuation.py, for one)
    # still asks for the closer of the two real prices rather than the plain one.
    reverse = pattern is not None
    if pattern is None and tokens and tokens[-1].lower() == "reverse":
        reverse = True
        tokens = tokens[:-1]

    abbrevs = {a.lower() for a in RARITY_ABBREV.values()}
    for i, tok in enumerate(tokens):
        if i == 0 or not re.fullmatch(r"[A-Za-z]{0,4}\d{1,4}", tok):
            continue
        name = " ".join(t for t in tokens[:i] if t.lower() not in abbrevs)
        return {
            "name": name,
            "set_name": " ".join(tokens[i + 1:]),
            "number": tok,
            "reverse": reverse,
            "pattern": pattern,
            "pokemon_center": pokemon_center,
            "parsed": True,
        }

    # Nothing structured to recover - a free-text search like "tornadus promo sealed"
    # names no card number. Return the flags anyway rather than None: whether the search
    # asked for a Pokemon Center print, or a reverse, is still knowable from the string
    # and is still worth filtering comps on. Callers that need a real card check
    # `parsed`, or simply find name/number empty and skip those checks.
    return {
        "name": "",
        "set_name": "",
        "number": "",
        "reverse": reverse,
        "pattern": pattern,
        "pokemon_center": pokemon_center,
        "parsed": False,
    }


def card_number(card_query: str | None) -> str | None:
    """The card number implied by a card_query string, via card_identity(), or None
    when there isn't one (no card_query, or nothing in it parses as a card).

    Thin wrapper for callers that only need this one field:
    active_listings.number is populated from it (both sync paths, and the manual
    card-correction endpoint) purely so the Active Listings page can sort by card
    number in SQL - card_query itself can't be, since the number is embedded in a
    formatted string rather than a column of its own.
    """
    identity = card_identity(card_query)
    return (identity["number"] or None) if identity else None


def lookup_market_price(card_query: str) -> float | None:
    """TCGdex/TCGPlayer market price for a card previously seen via enrich_rows (looked
    up by the exact card_query string it produced then, not re-derived from it now)."""
    cache = _load_json(CARD_QUERY_LOOKUP)
    entry = cache.get(card_query)
    if not entry:
        return None
    return _lookup_price(entry["name"], entry["set_name"], entry["number"], entry["variant"])


def enrich_rows(rows: list[dict], title_key: str = "Item Title") -> None:
    """Matches each row's title to a card, setting row["Card"]. Also stashes the
    structured match (name/set_name/number/variant) behind the flat card_query string
    it produced, in one batched write at the end, so a later market-price lookup by
    card_query alone (e.g. from price_research.py, which only has the flat string) can
    use the same reliable, title-anchored match instead of re-parsing the lossy
    formatted string - re-matching "Charizard ex 199 Obsidian Flames" on its own picks
    the wrong print, since the bare number lost its "x/y" anchor when the string was
    formatted. Batched (not one read+write per row) both for speed and because rapid
    repeated replace-on-write of the same file is prone to a transient Windows file
    lock (WinError 5) when called on a large batch."""
    db = get_db()
    lookup_updates: dict[str, dict] = {}
    for row in rows:
        title = (row.get(title_key) or "").split(";")[0]
        m = db.match(title)
        card_query = format_card(m, title)
        row["Card"] = card_query
        if m and card_query:
            lookup_updates[card_query] = {
                "name": m["name"],
                "set_name": m["set_name"],
                "number": m["number"],
                "variant": "reverseHolofoil" if _REVERSE_RE.search(title) else "holofoil",
            }
    if lookup_updates:
        cache = _load_json(CARD_QUERY_LOOKUP)
        cache.update(lookup_updates)
        _save_json(CARD_QUERY_LOOKUP, cache)