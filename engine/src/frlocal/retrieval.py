"""Choosing which parts of the knowledge sources go into each model request.

Short documents are sent whole. A long material (for example a 3GPP
specification) is split into fixed-size passages and only the passages that
best match the current question are sent, scored with BM25-style term
weighting. Matching is lexical and works for English words, identifiers such
as ``36.211`` or ``C++``, and Chinese/Japanese/Korean text via character
bigrams.

Searching is a handful of ``str.find`` scans over a lower-cased copy of each
document, which keeps the per-question cost to a few hundred milliseconds even
at the 20-million-character document limit, without building an index.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from .config import Limits

STOP_WORDS = frozenset(["the", "and", "for", "are", "but", "not", "you", "your", "with", "this", "that", "from", "have", "has", "had", "was", "were", "what", "when", "where", "which", "who", "why", "how", "can", "could", "would", "should", "will", "about", "into", "than", "then", "them", "they", "their", "there", "these", "those", "our", "out", "all", "any", "its", "also", "just", "more", "most", "some", "such", "tell", "describe", "explain", "please", "give", "walk", "through", "time", "did", "does", "doing", "done", "been", "being", "very", "really", "like"])

WORD = re.compile(r"[a-z0-9][a-z0-9.+#-]*[a-z0-9+#]|[a-z0-9]")
CJK_RUN = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af\uf900-\ufaff]+")


def search_terms(text: str, limit: int) -> list[str]:
    """Distinct, informative search terms from a question, longest first."""
    terms: dict[str, None] = {}
    lower = text.lower()
    for word in WORD.findall(lower):
        if (len(word) >= 3 or any(ch.isdigit() for ch in word)) and word not in STOP_WORDS:
            terms[word] = None
    for run in CJK_RUN.findall(lower):
        if len(run) == 1:
            terms[run] = None
        for index in range(len(run) - 1):
            terms[run[index:index + 2]] = None
    return sorted(terms, key=len, reverse=True)[:limit]


def _is_word_char(ch: str) -> bool:
    return "a" <= ch <= "z" or "0" <= ch <= "9"


@dataclass
class Source:
    """One prepared document available to a live session."""

    document_id: str
    kind: str          # "resume" or "material"
    filename: str
    text: str
    lower: str | None = field(default=None, repr=False)  # only for long materials


@dataclass
class Selection:
    text: str
    excerpts: bool = False                       # text is a set of matched passages
    passages: list[int] = field(default_factory=list)


def relevant_passages(source: Source, terms: list[str], limit: int, passage_chars: int) -> Selection:
    """The best-matching passages of a long document, in document order."""
    text, lower = source.text, source.lower or source.text.lower()
    count = math.ceil(len(text) / passage_chars)
    scores = [0.0] * count
    for term in terms:
        ascii_term = _is_word_char(term[0])
        frequencies: dict[int, int] = {}
        position = lower.find(term)
        while position >= 0:
            end = position + len(term)
            whole_word = not ascii_term or (
                (position == 0 or not _is_word_char(lower[position - 1])) and (end >= len(lower) or not _is_word_char(lower[end])))
            if whole_word:
                index = position // passage_chars
                frequencies[index] = frequencies.get(index, 0) + 1
            position = lower.find(term, end)
        idf = math.log(1 + (count - len(frequencies) + 0.5) / (len(frequencies) + 0.5))
        for index, frequency in frequencies.items():
            scores[index] += idf * frequency * 2.2 / (frequency + 1.2)
    ranked = sorted((i for i in range(count) if scores[i] > 0), key=lambda i: scores[i], reverse=True)
    if not ranked:
        return Selection(text[:limit])
    chosen = sorted(ranked[:max(1, limit // (passage_chars + 5))])
    joined = "\n…\n".join(text[i * passage_chars:(i + 1) * passage_chars].strip() for i in chosen)
    return Selection(joined[:limit], excerpts=True, passages=chosen)


def prepare_sources(documents: list[tuple[dict, str]], limits: Limits) -> list[Source]:
    """Order documents resume-first and pre-compute what retrieval needs."""
    sources = []
    for metadata, text in documents:
        trimmed = text.strip()
        if not trimmed or metadata.get("archived_at"):
            continue
        kind = metadata.get("kind", "material")
        sources.append(Source(
            document_id=metadata["document_id"], kind=kind,
            filename=metadata.get("display_name") or metadata.get("filename") or "document",
            text=trimmed,
            lower=trimmed.lower() if kind != "resume" and len(trimmed) > limits.max_material_chars else None,
        ))
    sources.sort(key=lambda source: 0 if source.kind == "resume" else 1)
    return sources


def build_context_documents(sources: list[Source], query: str, limits: Limits) -> tuple[list[dict], list[dict]]:
    """Documents to send with one request, plus provenance for the app.

    Returns ``(documents, refs)``: ``documents`` go into the model input and
    ``refs`` (``document_id``/``chunk_no``) let the app show "From your
    materials" under answers that used matched passages.
    """
    terms = search_terms(query, limits.max_query_terms)
    budget = limits.max_source_chars
    documents, refs = [], []
    for source in sources:
        limit = min(budget, limits.max_resume_chars if source.kind == "resume" else limits.max_material_chars)
        if limit <= 0:
            break
        selection = (relevant_passages(source, terms, limit, limits.passage_chars)
                     if source.lower is not None else Selection(source.text[:limit]))
        budget -= len(selection.text)
        entry = {"kind": source.kind, "filename": source.filename, "text": selection.text}
        if selection.excerpts:
            entry["excerpts"] = True
            refs.extend({"document_id": source.document_id, "chunk_no": index, "distance": 0.0} for index in selection.passages)
        elif len(selection.text) < len(source.text):
            entry["truncated"] = True
        documents.append(entry)
    return documents, refs
