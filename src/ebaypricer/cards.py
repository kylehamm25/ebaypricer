from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any

import requests
from rapidfuzz import fuzz, process as fuzz_process

from .api_counter import track
from .paths import CACHE_FILE, PRICING_CACHE, TCGDEX_SET_MAP

GITHUB_BASE = "https://raw.githubusercontent.com/PokemonTCG/pokemon-tcg-data/master"
TCGDEX_API = "https://api.tcgdex.net/v2/en"

POKEMON_NOISE = {
    "pokemon", "pokemon", "tcg", "card", "cards", "nm", "lp", "mp", "hp",
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

SET_PREFIX_RE = re.compile(r"\b(s[vv]\d{2}|swsh\d{2?}|bw\d{2?}|xy\d{2?}|sm\d{2?})\b", re.IGNORECASE)
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


_STOPWORDS = {"with", "and", "the", "for", "from", "in", "of", "to", "a", "an", "its"}

_REVERSE_RE = re.compile(r'\breverse\b', re.IGNORECASE)


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9\s]", "", s.lower()).strip()


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
    track("tcgdex")
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
            track("tcgdex")
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
        track("tcgdex")
        resp.raise_for_status()
        return resp.json()

    def _fetch_set_cards(self, set_id: str) -> list[dict]:
        resp = requests.get(f"{GITHUB_BASE}/cards/en/{set_id}.json", timeout=30)
        track("tcgdex")
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
        if sn in title_norm:
            return True
        expanded = _expand_set_abbrevs(title_norm)
        if expanded != title_norm and sn in expanded:
            return True
        tokens = _significant_tokens(set_name)
        if len(tokens) >= 2:
            return sum(t in title_norm for t in tokens) >= 2
        return bool(tokens) and tokens[0] in title_norm

    def _match_exact(self, title: str) -> dict | None:
        for name in self.name_list_by_len:
            if re.search(r'\b' + re.escape(name) + r'\b', title, re.IGNORECASE):
                return dict(self.name_to_card[name])
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
        desc = _norm(title)
        matched_by_set = [c for c in candidates if self._title_matches_set(desc, c["set_name"])]
        if matched_by_set:
            if len(matched_by_set) == 1:
                return dict(matched_by_set[0])
            for c in matched_by_set:
                if re.search(r'\b' + re.escape(c["name"]) + r'\b', title, re.IGNORECASE):
                    return dict(c)
            return dict(matched_by_set[0])
        matched_by_series = [c for c in candidates if self._title_matches_set(desc, c["set_series"])]
        if matched_by_series:
            if len(matched_by_series) == 1:
                return dict(matched_by_series[0])
            for c in matched_by_series:
                if re.search(r'\b' + re.escape(c["name"]) + r'\b', title, re.IGNORECASE):
                    return dict(c)
            return dict(matched_by_series[0])
        for c in candidates:
            if re.search(r'\b' + re.escape(c["name"]) + r'\b', title, re.IGNORECASE):
                return dict(c)
        return None

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
            if len(candidates) == 1:
                return dict(candidates[0])
            if candidates:
                desc = _norm(title)
                for c in candidates:
                    if self._title_matches_set(desc, c["set_name"]):
                        return dict(c)
                for c in candidates:
                    if re.search(r'\b' + re.escape(c["name"]) + r'\b', title, re.IGNORECASE):
                        return dict(c)
                return dict(candidates[0])

        stripped = digits_str.lstrip("0")
        compound = f"{set_id}-{stripped}"
        candidates = self.by_number.get(compound, [])
        if len(candidates) == 1:
            return dict(candidates[0])
        return None

    def _match_fuzzy(self, title: str) -> dict | None:
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
            card = self.name_to_card[candidate_name]
            if self._subtypes_match(title, card.get("subtypes", [])):
                return dict(card)
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
