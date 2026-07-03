"""
Pokemon Card Database enrichment module.

Sources card data from PokemonTCG/pokemon-tcg-data on GitHub (raw JSON).
Optional pricing from TCGdex API.
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any

import requests
from rapidfuzz import process as fuzz_process

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_FILE = os.path.join(_SCRIPT_DIR, "..", "data", "cards_cache.json")
PRICING_CACHE = os.path.join(_SCRIPT_DIR, "..", "data", "pricing_cache.json")
TCGDEX_SET_MAP = os.path.join(_SCRIPT_DIR, "..", "data", "tcgdex_set_map.json")

GITHUB_BASE = "https://raw.githubusercontent.com/PokemonTCG/pokemon-tcg-data/master"
TCGDEX_API = "https://api.tcgdex.net/v2/en"

POKEMON_NOISE = {
    "pokemon", "pokemon", "tcg", "card", "cards", "nm", "lp", "mp", "hp",
    "near", "mint", "lightly", "played", "damaged", "rare", "ultra", "holo",
    "holofoil", "reverse", "reverseholofoil", "full", "art", "vmax", "vstar",
    "ex", "gx", "v", "tag", "team", "prism", "star", "break", "trainer",
    "gallery", "galarian", "radiant", "amazing", "shiny", "baby",
    "promo", "black", "white", "sword", "shield", "scarlet", "violet",
    "standard", "envelope", "lot", "lot of", "mixed", "common", "uncommon",
    "secret", "illustration", "anime", "japanese", "english", "first", "edition",
    "1st", "ed", "foil", "non", "sv", "swsh", "sm", "xy", "bw", "hgss", "dp",
    "pl", "pop", "np", "holo", "poke", "ball", "energy", "basic", "stage",
    "level", "ancient", "future", "tera", "ex", "v", "vmax", "vstar", "gx",
}

CARD_NUM_RE = re.compile(r"\b(\d{1,4}/\d{2,4})\b")
HEADERS = ["Card"]

RARITY_ABBREV = {
    "illustration rare": "IR",
    "special illustration rare": "SIR",
}


_STOPWORDS = {"with", "and", "the", "for", "from", "in", "of", "to", "a", "an", "its"}


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9\s]", "", s.lower()).strip()


def _significant_tokens(s: str) -> list[str]:
    skip = _STOPWORDS | POKEMON_NOISE
    return [t for t in re.split(r"\W+", s.lower()) if len(t) > 3 and t not in skip]


# ── pricing helpers ───────────────────────────────────────────────────────

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
    """Return {<set_name_lower>: <tcgdex_set_id>}."""
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
    """Return TCGPlayer market price in USD for the best-matching variant."""
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


# ── card database ─────────────────────────────────────────────────────────

@dataclass
class CardDatabase:
    cards: list[dict[str, Any]] = field(default_factory=list)
    by_number: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    name_list: list[str] = field(default_factory=list)
    name_to_card: dict[str, dict[str, Any]] = field(default_factory=dict)
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

        seen = set()
        for c in self.cards:
            key = _norm(c["name"])
            if key not in seen:
                seen.add(key)
                self.name_list.append(c["name"])

    # ── matching ───────────────────────────────────────────────────────────

    def match(self, title: str) -> dict | None:
        result = self._match_by_number(title)
        if result:
            return result
        result = self._match_fuzzy(title)
        return result

    @staticmethod
    def _title_matches_set(title_norm: str, set_name: str) -> bool:
        if not set_name:
            return False
        sn = set_name.lower()
        if sn in title_norm:
            return True
        tokens = _significant_tokens(set_name)
        if len(tokens) >= 2:
            return sum(t in title_norm for t in tokens) >= 2
        return bool(tokens) and tokens[0] in title_norm

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
        desc = _norm(title)
        for c in candidates:
            if self._title_matches_set(desc, c["set_name"]):
                return dict(c)
        for c in candidates:
            if self._title_matches_set(desc, c["set_series"]):
                return dict(c)
        return dict(candidates[0])

    def _match_fuzzy(self, title: str) -> dict | None:
        clean = _norm(title)
        for noise in POKEMON_NOISE:
            clean = clean.replace(noise, " ")
        clean = re.sub(r"\s+", " ", clean).strip()
        if not clean or len(clean) < 3:
            return None
        result = fuzz_process.extractOne(
            clean, self.name_list, score_cutoff=65,
        )
        if result:
            return dict(self.name_to_card[result[0]])
        return None

# ── public API ─────────────────────────────────────────────────────────────

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
    parts.append(m["number"])
    parts.append(m["set_name"])
    return " ".join(parts)


def enrich_rows(rows: list[dict], title_key: str = "Item Title") -> None:
    db = get_db()
    for row in rows:
        title = (row.get(title_key) or "").split(";")[0]
        m = db.match(title)
        row["Card"] = _fmt_card(m)





if __name__ == "__main__":
    db = get_db()
    tests = [
        "Rayquaza V - 100/159 - Ultra Rare - Rapid Strike Near Mint Pokemon Card",
        "Pokemon Archaludon 155/142 Sv07: Stellar Crown Holo",
        "Pikachu ex 063/193 Paldea Evolved PAL English Pokemon Card - NM",
        "Bulbasaur 45/100 Crystal Guardians Regular",
        "ALPS Outdoorz Pursuit Backpack Brand New Never Used",
    ]
    for t in tests:
        m = db.match(t)
        print(f"  {_fmt_card(m):50s} | {t}")
