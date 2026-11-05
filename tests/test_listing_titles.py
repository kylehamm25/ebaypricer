import unittest

from dashboard.backend.services.listing_csv import TITLE_MAX, build_title


def ident(**overrides):
    data = {
        "name": "Charizard ex",
        "number": "199",
        "set_name": "151",
        "set_series": "Scarlet & Violet",
        "rarity": "Special Illustration Rare",
        "supertype": "Pokemon",
        "subtypes": ["Stage 2", "ex"],
        "reverse": False,
        "pattern": None,
        "non_holo": False,
        "catalog": True,
    }
    data.update(overrides)
    return data


class TitleTests(unittest.TestCase):
    def test_uses_catalog_context_and_stays_under_limit(self):
        title = build_title(ident(), "Near Mint")

        self.assertLessEqual(len(title), TITLE_MAX)
        self.assertTrue(title.startswith("Charizard ex 199"))
        self.assertIn("Scarlet & Violet 151", title)
        self.assertIn("Special Illustration Rare", title)
        self.assertIn("Pokemon TCG", title)
        self.assertTrue(title.endswith("NM"))

    def test_grade_survives_a_long_title(self):
        title = build_title(ident(name="A" * 120), "Lightly Played")

        self.assertLessEqual(len(title), TITLE_MAX)
        self.assertTrue(title.endswith("LP"))

    def test_vintage_catalog_fills_with_year_type_and_vintage(self):
        title = build_title(
            ident(name="Pikachu", number="58", set_name="Base", set_series="Base",
                  rarity="Common", subtypes=["Basic"], types=["Lightning"],
                  release="1999/01/09"),
            "Near Mint",
        )

        self.assertLessEqual(len(title), TITLE_MAX)
        self.assertIn("1999", title)
        self.assertIn("Vintage", title)
        self.assertIn("Lightning", title)
        self.assertTrue(title.endswith("NM"))

    def test_poke_ball_is_not_called_reverse_holo(self):
        title = build_title(
            ident(name="Espeon", number="033", set_name="Prismatic Evolutions",
                  pattern="poke_ball", reverse=True),
            "Near Mint",
        )

        self.assertIn("Poke Ball", title)
        self.assertNotIn("Reverse Holo", title)

    def test_non_holo_does_not_keep_holo_rarity(self):
        title = build_title(
            ident(name="Charizard", number="4", set_name="Base Set",
                  set_series="Base", rarity="Rare Holo", non_holo=True),
            "Near Mint",
        )

        self.assertIn("Non-Holo", title)
        self.assertNotIn("Rare Holo", title)

    def test_series_is_not_repeated_when_the_set_name_has_it(self):
        title = build_title(
            ident(name="Pikachu", number="58", set_name="Base Set",
                  set_series="Base", rarity="Common", subtypes=["Basic"]),
            "Near Mint",
        )

        self.assertNotIn("Base Base", title)
        self.assertIn("Base Set", title)

    def test_free_text_does_not_repeat_its_own_number_or_set(self):
        title = build_title(
            ident(name="dragonite 12 mcdonalds", number="12", set_name="mcdonalds",
                  set_series="", rarity="", supertype="", subtypes=[], catalog=False),
            "Near Mint",
        )

        self.assertEqual(title.lower().count("12"), 1)
        self.assertEqual(title.lower().count("mcdonalds"), 1)

    def test_unknown_condition_adds_no_grade(self):
        title = build_title(ident(), None)

        self.assertLessEqual(len(title), TITLE_MAX)
        self.assertFalse(title.endswith(("NM", "LP", "MP", "HP", "DMG")))

    def test_blank_name_produces_no_title(self):
        self.assertEqual(build_title(ident(name=""), "Near Mint"), "")


if __name__ == "__main__":
    unittest.main()
