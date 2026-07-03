import requests, json

# Check TCGplayer pricing availability for different cards
test_cards = [
    ("sv02-063", "Pikachu ex (Paldea Evolved)"),
    ("sv07-155", "Archaludon (Stellar Crown)"),
    ("base1-004", "Charizard (Base Set)"),
    ("swsh7-100", "Garbodor V (Evolving Skies)"),
    ("sv03_5-158", "Zapdos ex (151)"),
    ("sv04-063", "Pikachu ex (Paradox Rift)"),
]

for cid, name in test_cards:
    r = requests.get(f"https://api.tcgdex.net/v2/en/cards/{cid}", timeout=15)
    if r.status_code != 200:
        print(f"{cid:15s} {name:40s} {r.status_code}")
        continue
    d = r.json()
    pricing = d.get("pricing", {})
    if not pricing:
        print(f"{cid:15s} {name:40s} NO PRICING")
        continue
    tcg = pricing.get("tcgplayer")
    cm = pricing.get("cardmarket")
    tcg_prices = {}
    if tcg and isinstance(tcg, dict):
        for k in ["normal", "holofoil", "reverseHolofoil"]:
            if k in tcg and isinstance(tcg[k], dict) and "marketPrice" in tcg[k]:
                tcg_prices[k] = tcg[k]["marketPrice"]
    print(f"{cid:15s} {name:40s} TCG: {tcg_prices}  Cardmarket: {bool(cm)}")
