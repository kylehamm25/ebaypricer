"""
Pokémon sprite utility - maps Pokémon names to PokeAPI sprite URLs.

Uses PokeAPI (https://pokeapi.co/) to fetch the National Dex number for each Pokémon,
then constructs the sprite URL from the official PokeAPI sprites repository.

Sprite URL format: https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/{id}.png

This module parses Pokémon names from eBay listing titles by matching against
a comprehensive list of all known Pokémon names.
"""

import json
import os
import re
import time
from typing import Optional

import requests

from ebaypricer.paths import DATA_DIR

POKEAPI_BASE = "https://pokeapi.co/api/v2"
SPRITE_BASE = "https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon"
DEFAULT_SPRITE_URL = f"{SPRITE_BASE}/25.png"  # Pikachu
CACHE_FILE = os.path.join(DATA_DIR, "pokemon_name_to_id.json")
POKEMON_NAMES_FILE = os.path.join(DATA_DIR, "pokemon_names.json")
CACHE_TTL_DAYS = 30

# Common name normalizations for fuzzy matching
NAME_FIXES = {
    "nidoran-f": "nidoran-female",
    "nidoran-m": "nidoran-male",
    "mr. mime": "mr-mime",
    "mime jr.": "mime-jr",
    "ho-oh": "ho-oh",
    "porygon-z": "porygon-z",
    "jangmo-o": "jangmo-o",
    "hakamo-o": "hakamo-o",
    "kommo-o": "kommo-o",
    "tapu koko": "tapu-koko",
    "tapu lele": "tapu-lele",
    "tapu bulu": "tapu-bulu",
    "tapu fini": "tapu-fini",
    "type: null": "type-null",
    "meltan": "meltan",
    "melmetal": "melmetal",
    "wo-chien": "wo-chien",
    "chien-pao": "chien-pao",
    "ting-lu": "ting-lu",
    "chi-yu": "chi-yu",
    "roaring moon": "roaring-moon",
    "iron valiant": "iron-valiant",
    "great tusk": "great-tusk",
    "scream tail": "scream-tail",
    "brute bonnet": "brute-bonnet",
    "flutter mane": "flutter-mane",
    "slither wing": "slither-wing",
    "sandy shocks": "sandy-shocks",
    "iron treads": "iron-treads",
    "iron bundle": "iron-bundle",
    "iron hands": "iron-hands",
    "iron jugulis": "iron-jugulis",
    "iron moth": "iron-moth",
    "iron thorns": "iron-thorns",
    "farfetch'd": "farfetchd",
    "sirfetch'd": "sirfetchd",
    "mr. rime": "mr-rime",
}

# Words that are NOT Pokémon names (noise words in titles)
TITLE_NOISE_WORDS = {
    "pokemon", "pokémon", "tcg", "card", "cards", "nm", "lp", "mp", "hp",
    "near", "mint", "lightly", "played", "moderately", "heavily", "damaged",
    "rare", "ultra", "holo", "holofoil", "reverse", "reverseholofoil", "full", "art",
    "tag", "team", "prism", "star", "break", "trainer",
    "gallery", "galarian", "radiant", "amazing", "shiny", "baby",
    "promo", "black", "white", "sword", "shield", "scarlet", "violet",
    "standard", "envelope", "lot", "mixed", "common", "uncommon",
    "secret", "illustration", "anime", "japanese", "english", "first", "edition",
    "1st", "ed", "foil", "non", "hgss", "dp",
    "pl", "pop", "np", "poke", "ball", "energy", "basic", "stage",
    "level", "ancient", "future", "tera",
    "reverse", "holo", "rare", "unlimited", "near mint", "lightly played",
    "moderately played", "heavily played", "mint", "played",
    "cosmos", "swirl", "hd", "blister", "exclusives", "promo",
    "unseen", "forces", "evolution", "mega", "ex", "gx", "vmax", "vstar",
    "rainbow", "gold", "silver", "crystal", "neo", "discovery", "destiny",
    "guardians", "fossil", "jungle", "base", "team", "rocket", "gym",
    "legendary", "collection", "champion", "path", "dark", "steel",
    "dragon", "fairy", "fighting", "fire", "water", "grass", "electric",
    "psychic", "ghost", "normal", "flying", "bug", "rock", "ground",
    "poison", "ice", "shadow", "purified", "delta", "species",
    "prime", "lv", "lv.x", "lvl", "sp", "ex", "gx", "v", "vmax", "vstar",
    "tag team", "amazing rare", "shiny rare", "illustration rare",
    "special illustration rare", "character rare", "character super rare",
    "hyper rare", "secret rare", "ultra rare", "double rare", "triple rare",
    "holo rare", "reverse holo", "non holo", "first edition",
    "unlimited", "shadowless", "error", "misprint", "mis-cut",
    "signed", "autograph", "graded", "psa", "bgs", "cgc", "sgc",
    "gem mint", "mint", "excellent", "good", "fair", "poor",
    "pack", "box", "booster", "theme", "deck", "collection",
    "english", "japanese", "korean", "chinese", "french", "german",
    "italian", "spanish", "portuguese", "russian",
    "unown", "forms", "form", "variant", "variant", "alternate",
    "alternate art", "full art", "alt art", "secret", "rainbow",
    "gold", "silver", "bronze", "platinum", "diamond", "pearl",
    "heartgold", "soulsilver", "black", "white", "black 2", "white 2",
    "x", "y", "omega ruby", "alpha sapphire", "sun", "moon",
    "ultra sun", "ultra moon", "lets go", "pikachu", "eevee",
    "sword", "shield", "isle", "armor", "crown", "tundra",
    "brilliant", "diamond", "shining", "pearl", "legends", "arceus",
    "scarlet", "violet", "teal", "mask", "indigo", "disk",
    "sv", "swsh", "sm", "xy", "bw", "dp", "pt", "hgss", "pl",
    "ex", "gx", "v", "vmax", "vstar", "tag", "team", "amazing",
    "radiant", "shiny", "baby", "basic", "stage", "stage 1", "stage 2",
    "break", "prism", "star", "ex", "mega", "gx", "v", "vmax", "vstar",
    "tag team", "amazing rare", "shiny rare", "illustration rare",
    "special illustration rare", "character rare", "character super rare",
    "hyper rare", "secret rare", "ultra rare", "double rare", "triple rare",
    "holo rare", "reverse holo", "non holo", "first edition",
    "unlimited", "shadowless", "error", "misprint", "mis-cut",
    "signed", "autograph", "graded", "psa", "bgs", "cgc", "sgc",
    "gem mint", "mint", "excellent", "good", "fair", "poor",
    "pack", "box", "booster", "theme", "deck", "collection",
    "english", "japanese", "korean", "chinese", "french", "german",
    "italian", "spanish", "portuguese", "russian",
}

# Set abbreviations that appear in titles
SET_ABBREV = {
    "base1": "base", "base2": "jungle", "base3": "fossil", "base4": "base set 2",
    "base5": "team rocket", "base6": "gym heroes", "gym1": "gym heroes",
    "gym2": "gym challenge", "neo1": "neo genesis", "neo2": "neo discovery",
    "neo3": "neo revelation", "neo4": "neo destiny", "si1": "southern islands",
    "ecard1": "expedition", "ecard2": "aquapolis", "ecard3": "skyridge",
    "ex1": "ruby sapphire", "ex2": "sandstorm", "ex3": "dragon",
    "ex4": "team magma vs team aqua", "ex5": "hidden legends",
    "ex6": "fire red leaf green", "ex7": "team rocket returns",
    "ex8": "deoxys", "ex9": "emerald", "ex10": "unseen forces",
    "ex11": "delta species", "ex12": "legend maker", "ex13": "holon phantoms",
    "ex14": "crystal guardians", "ex15": "dragon frontiers",
    "ex16": "power keepers", "dp1": "diamond pearl", "dp2": "mysterious treasures",
    "dp3": "secret wonders", "dp4": "great encounters", "dp5": "majestic dawn",
    "dp6": "legends awakened", "dp7": "stormfront", "pl1": "platinum",
    "pl2": "rising rivals", "pl3": "supreme victors", "pl4": "arceus",
    "hgss1": "heartgold soulsilver", "hgss2": "unleashed", "hgss3": "undaunted",
    "hgss4": "triumphant", "call1": "call of legends", "bw1": "black white",
    "bw2": "emerging powers", "bw3": "noble victors", "bw4": "next destinies",
    "bw5": "dark explorers", "bw6": "dragons exalted", "bw7": "boundaries crossed",
    "bw8": "plasma storm", "bw9": "plasma freeze", "bw10": "plasma blast",
    "bw11": "legendary treasures", "xy1": "xy", "xy2": "flashfire",
    "xy3": "furious fists", "xy4": "phantom forces", "xy5": "primal clash",
    "xy6": "roaring skies", "xy7": "ancient origins", "xy8": "breakthrough",
    "xy9": "breakpoint", "xy10": "fates collide", "xy11": "steam siege",
    "xy12": "evolutions", "sm1": "sun moon", "sm2": "guardians rising",
    "sm3": "burning shadows", "sm4": "crimson invasion", "sm5": "ultra prism",
    "sm6": "forbidden light", "sm7": "celestial storm", "sm8": "lost thunder",
    "sm9": "team up", "sm10": "unbroken bonds", "sm11": "unified minds",
    "sm12": "cosmic eclipse", "swsh1": "sword shield", "swsh2": "rebel clash",
    "swsh3": "darkness ablaze", "swsh4": "champion's path", "swsh5": "vivid voltage",
    "swsh6": "shining fates", "swsh7": "battle styles", "swsh8": "chilling reign",
    "swsh9": "evolving skies", "swsh10": "fusion strike", "swsh11": "brilliant stars",
    "swsh12": "astral radiance", "swsh12pt5": "lost origin", "swsh13": "silver tempest",
    "swsh14": "crown zenith", "sv1": "scarlet violet", "sv2": "paldea evolved",
    "sv3": "obsidian flames", "sv3pt5": "151", "sv4": "paradox rift",
    "sv4pt5": "paldean fates", "sv5": "temporal forces", "sv5pt5": "twilight masquerade",
    "sv6": "stellar crown", "sv7": "surging sparks", "sv8": "prismatic evolutions",
    "sv9": "journey together", "sv10": "heat wave arena",
}


class PokemonSpriteMapper:
    def __init__(self):
        self._name_to_id: dict[str, int] = {}
        self._pokemon_names: list[str] = []  # Sorted by length descending
        self._loaded = False

    def ensure_loaded(self) -> None:
        """Load the name-to-id mapping from cache or fetch from PokeAPI."""
        if self._loaded:
            return

        if os.path.isfile(CACHE_FILE) and os.path.isfile(POKEMON_NAMES_FILE):
            age_days = (time.time() - os.path.getmtime(CACHE_FILE)) / 86400
            if age_days < CACHE_TTL_DAYS:
                print(f"  Loading Pokemon name->id mapping from cache ({int(age_days)} days old)...")
                self._load_cache()
                self._loaded = True
                return

        print("  Fetching Pokemon name->id mapping from PokeAPI...")
        self._fetch_and_cache()
        self._loaded = True

    def _load_cache(self) -> None:
        with open(CACHE_FILE, encoding="utf-8") as f:
            self._name_to_id = json.load(f)
        with open(POKEMON_NAMES_FILE, encoding="utf-8") as f:
            self._pokemon_names = json.load(f)

    def _save_cache(self) -> None:
        os.makedirs(DATA_DIR, exist_ok=True)
        tmp = CACHE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self._name_to_id, f, ensure_ascii=False)
        os.replace(tmp, CACHE_FILE)

        tmp = POKEMON_NAMES_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self._pokemon_names, f, ensure_ascii=False)
        os.replace(tmp, POKEMON_NAMES_FILE)

    def _fetch_and_cache(self) -> None:
        """Fetch all Pokémon from PokeAPI and build name→id mapping."""
        url = f"{POKEAPI_BASE}/pokemon?limit=1300"
        try:
            resp = requests.get(url, timeout=60)
            resp.raise_for_status()
            data = resp.json()

            for entry in data["results"]:
                entry_id = int(entry["url"].rstrip("/").split("/")[-1])
                name = entry["name"]

                self._name_to_id[name] = entry_id
                self._name_to_id[name.replace("-", "")] = entry_id

        except requests.RequestException as e:
            print(f"  Warning: Failed to fetch from PokeAPI: {e}")
            if os.path.isfile(CACHE_FILE):
                print("  Using stale cache...")
                self._load_cache()
            else:
                raise

        # Build sorted list of Pokémon names (longest first for better matching)
        self._pokemon_names = sorted(self._name_to_id.keys(), key=len, reverse=True)
        self._save_cache()
        print(f"  Cached {len(self._name_to_id)} Pokemon name mappings")

    def _normalize_name(self, name: str) -> str:
        """Normalize a Pokémon name for lookup."""
        name = name.lower().strip()
        name = re.sub(r"[^a-z0-9\s\-\.']", "", name)
        if name in NAME_FIXES:
            return NAME_FIXES[name]
        return name

    def _normalize_title(self, title: str) -> str:
        """Normalize a title for matching - remove noise, keep Pokémon name candidates."""
        title = title.lower()
        # Remove special characters but keep spaces, hyphens, brackets
        title = re.sub(r"[^a-z0-9\s\-\[\]\.'()]", " ", title)
        # Collapse whitespace
        title = re.sub(r"\s+", " ", title).strip()
        return title

    def find_pokemon_in_title(self, title: str) -> Optional[str]:
        """Find the best matching Pokémon name in a title."""
        self.ensure_loaded()

        if not title:
            return None

        normalized_title = self._normalize_title(title)

        # Handle Unown forms specially (Unown [A], Unown [B], etc.)
        unown_match = re.search(r"unown\s*[\[\(]([a-z?!\-\?])[\]\)]", normalized_title)
        if unown_match:
            return "unown"

        # Try exact matches for longest names first
        for poke_name in self._pokemon_names:
            # Skip very short names that might be false positives
            if len(poke_name) < 3:
                continue
            
            # Create pattern for word boundary match
            # Handle names with hyphens/spaces
            pattern = r"\b" + re.escape(poke_name) + r"\b"
            if re.search(pattern, normalized_title):
                return poke_name

        # Try matching with common variations
        # Some titles might have "mr mime" instead of "mr-mime"
        normalized_no_hyphens = normalized_title.replace("-", " ")
        for poke_name in self._pokemon_names:
            if len(poke_name) < 3:
                continue
            poke_no_hyphens = poke_name.replace("-", " ")
            pattern = r"\b" + re.escape(poke_no_hyphens) + r"\b"
            if re.search(pattern, normalized_no_hyphens):
                return poke_name

        # Try matching without the 's (possessive) e.g. "Pikachu's" -> "pikachu"
        normalized_no_apos = re.sub(r"'s\b", "", normalized_title)
        for poke_name in self._pokemon_names:
            if len(poke_name) < 3:
                continue
            pattern = r"\b" + re.escape(poke_name) + r"\b"
            if re.search(pattern, normalized_no_apos):
                return poke_name

        return None

    def get_sprite_url(self, title: str) -> Optional[str]:
        """Get the sprite URL for a Pokémon found in a title."""
        self.ensure_loaded()

        pokemon_name = self.find_pokemon_in_title(title)
        if not pokemon_name:
            return None

        # Direct lookup
        if pokemon_name in self._name_to_id:
            return f"{SPRITE_BASE}/{self._name_to_id[pokemon_name]}.png"

        # Try without hyphens
        simple = pokemon_name.replace("-", "").replace(" ", "")
        if simple in self._name_to_id:
            return f"{SPRITE_BASE}/{self._name_to_id[simple]}.png"

        # Try fuzzy match for regional forms
        for regional in ["alolan", "galarian", "hisuian", "paldean"]:
            if regional in pokemon_name:
                base_name = pokemon_name.replace(regional, "").strip()
                if base_name in self._name_to_id:
                    return f"{SPRITE_BASE}/{self._name_to_id[base_name]}.png"

        # Try removing form suffixes
        for form_suffix in ["mega", "gmax", "gigantamax", "primal", "origin", "eternamax"]:
            if pokemon_name.endswith(f"-{form_suffix}") or pokemon_name.endswith(f" {form_suffix}"):
                base_name = pokemon_name.replace(f"-{form_suffix}", "").replace(f" {form_suffix}", "")
                if base_name in self._name_to_id:
                    return f"{SPRITE_BASE}/{self._name_to_id[base_name]}.png"

        return None


# Global instance
_mapper: Optional[PokemonSpriteMapper] = None


def get_sprite_mapper() -> PokemonSpriteMapper:
    global _mapper
    if _mapper is None:
        _mapper = PokemonSpriteMapper()
    return _mapper


def get_sprite_url(title: str) -> str:
    """Convenience function to get sprite URL from a title string.
    Returns Pikachu sprite as fallback if no Pokémon is found in title."""
    url = get_sprite_mapper().get_sprite_url(title)
    return url if url else DEFAULT_SPRITE_URL