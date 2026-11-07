"""Passage retrieval for large materials and the server-sent-events parser."""

from __future__ import annotations

import time

from frlocal.config import Limits
from frlocal.retrieval import Source, build_context_documents, prepare_sources, relevant_passages, search_terms
from frlocal.sse import SseParser

LIMITS = Limits()
FILLER = "General overview of the radio frame and timing. " * 600


def spec_source() -> Source:
    text = FILLER + "The PDSCH supports QPSK, 16QAM, 64QAM and 256QAM modulation. " + FILLER + "物理下行共享信道支持多种调制方式。" + FILLER
    return prepare_sources([({"document_id": "spec", "kind": "material", "filename": "36.211.pdf"}, text)], LIMITS)[0]


def test_search_terms_keep_identifiers_and_drop_stop_words():
    terms = search_terms("Tell me how the PDSCH in 36.211 uses C++ and 5G?", 16)
    assert {"pdsch", "36.211", "c++", "5g"} <= set(terms)
    assert "the" not in terms and "tell" not in terms
    assert search_terms("下行共享信道", 16)[:2] == ["下行", "行共"]


def test_relevant_passage_is_found_in_english_and_chinese():
    source = spec_source()
    english = relevant_passages(source, search_terms("Which modulation does the PDSCH support?", 16), 5000, 1500)
    assert english.excerpts and "256QAM modulation" in english.text and len(english.text) <= 5000
    chinese = relevant_passages(source, search_terms("下行共享信道用什么调制？", 16), 5000, 1500)
    assert "物理下行共享信道支持多种调制方式" in chinese.text


def test_whole_words_only_for_latin_terms():
    source = Source("d", "material", "f", "filtering lte " + "x" * 3000, ("filtering lte " + "x" * 3000).lower())
    selection = relevant_passages(source, ["lte"], 1500, 1500)
    assert selection.passages == [0]
    assert relevant_passages(Source("d", "material", "f", "filter " * 500, ("filter " * 500)), ["lte"], 100, 1500).excerpts is False


def test_context_budget_resume_first_and_provenance():
    documents = [
        ({"document_id": "m", "kind": "material", "filename": "notes.md"}, "Specific interview material"),
        ({"document_id": "r", "kind": "resume", "filename": "cv.pdf", "display_name": "My resume"}, "Led the payments migration. " + "x" * 9000),
        ({"document_id": "spec", "kind": "material", "filename": "36.211.pdf"}, spec_source().text),
        ({"document_id": "gone", "kind": "material", "filename": "old", "archived_at": "2026"}, "archived"),
    ]
    sources = prepare_sources(documents, LIMITS)
    assert [s.document_id for s in sources] == ["r", "m", "spec"]
    context, refs = build_context_documents(sources, "Which modulation does the PDSCH support?", LIMITS)
    assert context[0] == {"kind": "resume", "filename": "My resume", "text": context[0]["text"], "truncated": True}
    assert len(context[0]["text"]) == LIMITS.max_resume_chars
    assert context[1] == {"kind": "material", "filename": "notes.md", "text": "Specific interview material"}
    assert context[2]["excerpts"] is True and "PDSCH supports" in context[2]["text"]
    assert sum(len(d["text"]) for d in context) <= LIMITS.max_source_chars
    assert refs and all(ref["document_id"] == "spec" for ref in refs)
    unrelated, unrelated_refs = build_context_documents(sources, "Tell me about this project.", LIMITS)
    assert unrelated[2].get("truncated") is True and unrelated_refs == []


def test_retrieval_on_twenty_million_characters_is_fast():
    words = ["channel", "resource", "block", "subframe", "antenna", "port", "symbol", "mapping", "reference", "signal"]
    text = " ".join(f"{words[i % len(words)]} {i % 997}" for i in range(2_100_000))[:20_000_000]
    source = Source("big", "material", "big.pdf", text, text.lower())
    started = time.perf_counter()
    selection = relevant_passages(source, search_terms("How is the PDSCH resource block mapping done for antenna port 7?", 16), 5000, 1500)
    elapsed = time.perf_counter() - started
    assert selection.excerpts
    assert elapsed < 3.0, f"retrieval took {elapsed:.2f}s"


# ── SSE ──────────────────────────────────────────────────────────────────────


def test_sse_events_survive_arbitrary_chunk_boundaries():
    stream = ('event: response.output_text.delta\r\ndata: {"delta":"你好"}\r\n\r\n'
              ': comment\n\nevent: x\ndata: line1\ndata: line2\n\n').encode()
    for size in (1, 2, 3, 7, len(stream)):
        parser = SseParser()
        events = []
        for start in range(0, len(stream), size):
            events += parser.feed(stream[start:start + size])
        events += parser.close()
        assert [(e.event, e.data) for e in events] == [
            ("response.output_text.delta", '{"delta":"你好"}'), ("x", "line1\nline2")], size


def test_sse_flushes_a_final_event_without_blank_line():
    parser = SseParser()
    assert parser.feed(b"data: tail") == []
    assert [e.data for e in parser.close()] == ["tail"]
