"""Нормализация строк и проверка ответов (AnswerChecker)."""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field

POLICY_VERSION = "1"


@dataclass
class NormalizePolicy:
    """Политика нормализации. По умолчанию сохраняем смысловые различия
    (C/C++, 1/-1, resume/résumé, латинская/кириллическая 'a')."""

    casefold: bool = True
    collapse_whitespace: bool = True
    trim: bool = True
    strip_final_punctuation: bool = False
    unify_quotes: bool = False
    ignore_diacritics: bool = False

    def version(self) -> str:
        return f"{POLICY_VERSION}:{int(self.casefold)}{int(self.collapse_whitespace)}{int(self.trim)}{int(self.strip_final_punctuation)}{int(self.unify_quotes)}{int(self.ignore_diacritics)}"


DEFAULT_POLICY = NormalizePolicy()
STRICT_POLICY = NormalizePolicy(casefold=False, strip_final_punctuation=False)
LENIENT_POLICY = NormalizePolicy(
    strip_final_punctuation=True, unify_quotes=True, collapse_whitespace=True
)

FINAL_PUNCT = ".,;:!?\u2026"
QUOTES_MAP = str.maketrans(
    {
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u00ab": '"',
        "\u00bb": '"',
    }
)


def normalize(text: str, policy: NormalizePolicy = DEFAULT_POLICY) -> str:
    s = unicodedata.normalize("NFC", text or "")
    if policy.trim:
        s = s.strip()
    if policy.collapse_whitespace:
        s = " ".join(s.split())
    if policy.strip_final_punctuation:
        s = s.rstrip(FINAL_PUNCT + " " if False else FINAL_PUNCT).rstrip()
    if policy.unify_quotes:
        s = s.translate(QUOTES_MAP)
    if policy.ignore_diacritics:
        s = "".join(
            ch for ch in unicodedata.normalize("NFD", s) if unicodedata.category(ch) != "Mn"
        )
        s = unicodedata.normalize("NFC", s)
    if policy.casefold:
        s = s.casefold()
    return s


@dataclass
class CheckResult:
    correct: bool
    normalized_answer: str
    possible_typo: bool = False
    matched_answer: str | None = None
    policy_version: str = ""


def check_answer(
    user_answer: str | None,
    accepted: list[str],
    policy: NormalizePolicy = DEFAULT_POLICY,
    typo_suggest_threshold: float = 0.92,
) -> CheckResult:
    """Проверка текстового ответа. Fuzzy — только для сообщения «возможно, опечатка»,
    не для присуждения правильного ответа."""
    raw = user_answer or ""
    norm = normalize(raw, policy)
    accepted_norms = [(a, normalize(a, policy)) for a in accepted if a and a.strip()]
    if not norm:
        return CheckResult(False, norm, policy_version=policy.version())
    for original, acc in accepted_norms:
        if norm == acc:
            return CheckResult(True, norm, matched_answer=original, policy_version=policy.version())
    best_ratio = 0.0
    for original, acc in accepted_norms:
        ratio = _similarity(norm, acc)
        best_ratio = max(best_ratio, ratio)
        if ratio >= typo_suggest_threshold:
            return CheckResult(False, norm, possible_typo=True, matched_answer=original, policy_version=policy.version())
    return CheckResult(False, norm, policy_version=policy.version())


def _similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    import difflib

    return difflib.SequenceMatcher(None, a, b).ratio()


@dataclass
class AcceptedSides:
    """Допустимые ответы по сторонам: основной текст стороны + явно заданные варианты."""

    front: list[str] = field(default_factory=list)
    back: list[str] = field(default_factory=list)

    def for_direction(self, direction: str) -> list[str]:
        return self.back if direction == "front_to_back" else self.front
