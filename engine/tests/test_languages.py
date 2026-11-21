"""Interview vs assistance language: translation targets and hint sections per (spoken, assist) pair."""

from __future__ import annotations

from frlocal.realtime import coach, understanding
from frlocal.realtime.session import useful_translation


def test_translation_rule_targets_the_assistance_language():
    assert "into Simplified Chinese" in understanding._translate_rule("zh")
    assert "into English" in understanding._translate_rule("en")
    assert "into Japanese" in understanding._translate_rule("ja")


def test_analyze_instructions_carry_the_rule():
    assert "translate into English; when the text is already in English, return an empty string" in (
        understanding.INSTRUCTIONS.format(translate_rule=understanding._translate_rule("en")))


def test_useful_translation_follows_assist():
    # Chinese assistance (the default): a Chinese rendering of English speech is worth showing.
    assert useful_translation("你好", "hello", "zh")
    assert not useful_translation("hello", "hello", "zh")          # an echo is not a translation
    assert not useful_translation("hello", "你好", "zh")            # English under Chinese speech is not shown
    # English assistance: the mirror image — only non-Chinese output counts.
    assert useful_translation("hello", "你好", "en")
    assert not useful_translation("你好", "hello", "en")


def test_hint_sections_single_language():
    # 中文面试 (zh+zh) and 英文面试 (en+en): one section in the interview's language.
    zh = coach.answer_instructions(["zh"])
    assert "**中文**" in zh and "**EN**" not in zh and "Simplified Chinese" in zh
    en = coach.answer_instructions(["en"])
    assert "**EN**" in en and "**中文**" not in en


def test_hint_sections_bilingual_for_english_interview_chinese_help():
    # 英文面试中文辅助 (en+zh): the speakable English bullets, then the same in Chinese.
    text = coach.answer_instructions(["en", "zh"])
    assert "**EN**" in text and "**中文**" in text and text.index("**EN**") < text.index("**中文**")
    zh_en = coach.answer_instructions(["zh", "en"])
    assert zh_en.index("**中文**") < zh_en.index("**EN**")


def test_continue_variant_uses_the_same_languages():
    text = coach.answer_instructions(["en"], said=True)
    assert "**EN**" in text and "**中文**" not in text and "continue naturally" in text


def test_default_instructions_match_the_previous_bilingual_prompt():
    # Old clients send no assist: the session defaults to en+zh sections, like before.
    text = coach.answer_instructions()
    assert "**EN**" in text and "**中文**" in text


def test_answer_request_passes_languages_through():
    body = coach.answer_request("model", {}, "Why?", _limits(), languages=["zh"])
    assert "**中文**" in body["instructions"] and "**EN**" not in body["instructions"]


def _limits():
    from frlocal.config import Limits
    return Limits()
