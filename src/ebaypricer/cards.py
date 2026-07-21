from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any

import requests
from rapidfuzz import fuzz, process as fuzz_process

from .paths import CACHE_FILE, PRICING_CACHE, TCGDEX_SET_MAP

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

_PROMO_SET_TO_PREFIX = {
    "svp": "SVP",
}

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

    local_id = number.zfill(3)
    card_id = f"{tcg_set_id}-{local_id}"

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
            prices = {}
            for v in ("normal", "holofoil", "reverseHolofoil"):
                info = tcg.get(v)
                if isinstance(info, dict) and "marketPrice" in info:
                    prices[v] = info["marketPrice"]
        else:
            prices = {}
        cache[card_id] = prices if prices else None
        _save_json(PRICING_CACHE, cache)
        time.sleep(0.1)

    if not prices:
        return None

    variant_key = variant.lower().replace(" ", "")
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
    _loaded: bool = False

    def ensure_loaded(self) -> None:
        if self._loaded:
            return
        if os.path.isfile(CACHE_FILE):
            age_s = time.time() - os.path.getmtime(CACHE_FILE)
            print(f"  Loading card database from cache ({int(age_s // 86400)} days old) ...")
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
            cards = self._fetch_set_cards(sid)
            for c in cards:
                all_cards.append({
                    "id": c.get("id", ""),
                    "name": c.get("name", ""),
                    "number": c.get("number", ""),
                    "rarity": c.get("rarity", ""),
                    "supertype": c.get("supertype", ""),
                    "subtypes": c.get("subtypes", []),
                    "set_id": sid,
                    "set_name": sname,
                    "set_series": series,
                })
            if i % 25 == 0:
                print(f"    ... {i}/{total} sets ({len(all_cards)} cards)")
                self._save_cache(all_cards)

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
                result = self._disambiguate(candidates, title)
                if result:
                    return result
                # Ambiguous with no disambiguating signal in the title --
                # don't silently return an arbitrary print.
                return None
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
        results = fuzz_process.extract(
            clean, self.name_list, score_cutoff=80, limit=5,
        )
        for candidate_name, score, _ in results:
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


def format_card(match_result: dict | None, title: str | None = None) -> str | None:
    card_str = _fmt_card(match_result)
    if card_str and title and _REVERSE_RE.search(title):
        card_str += " Reverse"
    return card_str


def enrich_rows(rows: list[dict], title_key: str = "Item Title") -> None:
    db = get_db()
    for row in rows:
        title = (row.get(title_key) or "").split(";")[0]
        m = db.match(title)
        row["Card"] = format_card(m, title)