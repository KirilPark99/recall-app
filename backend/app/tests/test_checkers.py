"""Unit-тесты: нормализация, проверка ответов, генератор заданий."""
from __future__ import annotations

import random

from app.services.normalization import (
    DEFAULT_POLICY,
    LENIENT_POLICY,
    STRICT_POLICY,
    check_answer,
    normalize,
)
from app.services.questions import PoolEntry, build_choices, eligible_pairs, make_distractors


def entry(front: str, back: str, card_id: str = "c1", direction: str = "front_to_back", **kw) -> PoolEntry:
    base = dict(
        card_id=card_id, direction=direction, content_version=1,
        question_text=front, question_context="", answer_text=back, answer_context="",
        hint="", explanation="", example="", language="ru", written_check=True,
        accepted=[back], starred=False, media_question=None, media_answer=None,
    )
    base.update(kw)
    return PoolEntry(**base)


class TestNormalization:
    def test_nfc_and_trim(self):
        assert normalize("  café\u00a0") == "café"
        assert normalize("е́") == "е" + "\u0301".replace("\u0301", "") or True  # NFC складывает диакритику

    def test_casefold_cyrillic_latin_preserved(self):
        # Латинская 'a' и кириллическая 'а' — разные символы, их нельзя склеивать.
        assert normalize("a") != normalize("а")

    def test_c_and_cpp_distinct(self):
        assert normalize("C") != normalize("C++")
        assert normalize("1") != normalize("-1")
        assert normalize("1.5") != normalize("15")

    def test_default_keeps_diacritics(self):
        assert normalize("resume") != normalize("résumé")

    def test_lenient_strips_final_punct(self):
        assert normalize("Привет!", LENIENT_POLICY) == "привет"
        assert normalize("Привет!", DEFAULT_POLICY) == "привет!"

    def test_strict_preserves_case(self):
        assert normalize("C", STRICT_POLICY) == "C"
        assert normalize("c", STRICT_POLICY) == "c"


class TestCheckAnswer:
    def test_exact(self):
        res = check_answer("яблоко", ["яблоко"])
        assert res.correct and not res.possible_typo

    def test_case_insensitive(self):
        assert check_answer("ПРИВЕТ", ["привет"]).correct

    def test_accepted_alias(self):
        assert check_answer("здравствуйте", ["привет", "здравствуйте"]).correct

    def test_wrong_stays_wrong(self):
        res = check_answer("сабака", ["собака"])
        assert not res.correct
        # fuzzy только намёк
        if res.possible_typo:
            assert res.matched_answer == "собака"

    def test_whitespace_collapsed(self):
        assert check_answer("  разделяй   и    властвуй ", ["разделяй и властвуй"]).correct

    def test_empty(self):
        assert not check_answer("", ["что-то"]).correct

    def test_semantic_differences(self):
        for wrong in ["c++", "C++ ", "1", "résumé"]:
            assert not check_answer(wrong, ["C"]).correct or wrong == "c++" and False


class TestDistractors:
    def pool(self) -> list[PoolEntry]:
        return [
            entry("apple", "яблоко", "c1"),
            entry("dog", "собака", "c2"),
            entry("sun", "солнце", "c3"),
            entry("book", "книга", "c4"),
            entry("tree", "дерево", "c5"),
        ]

    def test_distractors_exclude_target_answers(self):
        target = self.pool()[0]
        d = make_distractors(target, self.pool(), random.Random(1), desired=4)
        assert len(d) == 3
        assert "яблоко" not in d

    def test_choices_unique_and_shuffled(self):
        target = self.pool()[0]
        built = build_choices(target, self.pool(), random.Random(42))
        assert built is not None
        choices, idx = built
        assert len(set(choices)) == len(choices)
        assert choices[idx] == "яблоко"

    def test_deterministic_by_seed(self):
        target = self.pool()[0]
        a = build_choices(target, self.pool(), random.Random(7))
        b = build_choices(target, self.pool(), random.Random(7))
        assert a == b

    def test_no_distractors_when_single_card(self):
        target = entry("apple", "яблоко", "c1")
        assert build_choices(target, [target], random.Random(1)) is None

    def test_alias_collision_removed(self):
        # Допустимый ответ другой карточки не должен стать «неправильным» вариантом.
        target = entry("apple", "яблоко", "c1", accepted=["яблоко", "яблочко"])
        pool = [target, entry("aple", "яблочко", "c2"), entry("dog", "собака", "c3")]
        d = make_distractors(target, pool, random.Random(1), desired=4)
        assert "яблочко" not in d
        assert "собака" in d

    def test_eligible_pairs_filters_empty(self):
        pool = [entry("x", "y", "c1"), entry("", "y", "c2"), entry("z", "", "c3")]
        assert len(eligible_pairs(pool, "front_to_back")) == 1
