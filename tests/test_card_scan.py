import unittest

from dashboard.backend.services.card_scan import (
    Candidate,
    OcrLine,
    _clean_name,
    _confidence,
    _extract_number,
    _hash_similarity,
    _number_matches,
)


def line(text: str, y: int, h: int = 20) -> OcrLine:
    return OcrLine(text=text, score=1.0, x=0, y=y, w=100, h=h)


class CleanNameTests(unittest.TestCase):
    def test_removes_hp_and_leading_stage_word(self):
        self.assertEqual(_clean_name("Basic Pikachu HP 60"), "Pikachu")

    def test_keeps_a_name_with_no_noise(self):
        self.assertEqual(_clean_name("Charizard ex"), "Charizard ex")


class ExtractNumberTests(unittest.TestCase):
    def test_slash_number_keeps_the_collector_number(self):
        self.assertEqual(_extract_number([line("Pikachu 58/102", 980)]), "58")

    def test_promo_number_is_normalized(self):
        self.assertEqual(_extract_number([line("SVP 013", 980)]), "SVP13")

    def test_bare_number_is_only_read_from_the_bottom_strip(self):
        lines = [line("60", 100), line("Pikachu", 120), line("58", 980)]
        self.assertEqual(_extract_number(lines), "58")

    def test_attack_damage_number_is_not_a_collector_number(self):
        lines = [
            line("Charizard", 100),
            line("120", 500),
            line("Fire Spin", 550),
            line("Trainer", 1200),
        ]
        self.assertIsNone(_extract_number(lines))


class NumberMatchTests(unittest.TestCase):
    def test_slash_number_matches_catalog_number(self):
        self.assertTrue(_number_matches("58/102", {"number": "58", "set_id": "base1"}))

    def test_promo_prefix_and_zero_padding_match(self):
        card = {"number": "13", "set_id": "svp"}
        self.assertTrue(_number_matches("SVP013", card))
        self.assertTrue(_number_matches("SVP 13", card))

    def test_unrelated_number_does_not_match(self):
        self.assertFalse(_number_matches("77", {"number": "58", "set_id": "base1"}))


class ConfidenceTests(unittest.TestCase):
    def candidate(self, **overrides) -> Candidate:
        values = dict(
            card_query="Pikachu 58 Base",
            name="Pikachu",
            set_name="Base",
            number="58",
            rarity="Common",
            image_url=None,
            score=1.0,
            name_score=1.0,
            number_match=True,
            visual_score=1.0,
        )
        values.update(overrides)
        return Candidate(**values)

    def test_high_requires_a_unique_identity(self):
        first = self.candidate()
        duplicate = self.candidate()
        self.assertEqual(_confidence("Pikachu", 1.0, [first], True), ("high", 1.0))
        self.assertEqual(_confidence("Pikachu", 1.0, [first, duplicate], True)[0], "medium")

    def test_medium_accepts_a_strong_name_without_a_number(self):
        candidate = self.candidate(number_match=False, score=0.82)
        self.assertEqual(_confidence("Pikachu", 1.0, [candidate], True)[0], "medium")

    def test_no_candidates_is_none(self):
        self.assertEqual(_confidence("Pikachu", 1.0, [], True), ("none", None))


class HashTests(unittest.TestCase):
    def test_identical_hashes_are_a_perfect_match(self):
        self.assertEqual(_hash_similarity("00", "00"), 1.0)

    def test_different_hashes_lose_their_bits(self):
        self.assertEqual(_hash_similarity("00", "ff"), 0.0)


if __name__ == "__main__":
    unittest.main()
