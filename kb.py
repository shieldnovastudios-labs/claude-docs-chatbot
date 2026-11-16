"""Knowledge base: load documents, split them into chunks, rank chunks with BM25.

Everything here is plain Python (no extra dependencies) so it is easy to read
and easy to run anywhere. For a few dozen documents this is fast and accurate
enough; for thousands of pages you would switch to a search index or embeddings.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import List, Sequence, Tuple

SUPPORTED_SUFFIXES = {".md", ".markdown", ".txt"}
MAX_CHUNK_CHARS = 900

STOPWORDS = frozenset(
    """
    a an and are as at be been but by can could do does did for from had has have
    how i if in into is it its me my of on or our please so than that the their them
    then there these they this to up us was we were what when where which who why
    will with would you your yours about any also just get got let lets
    """.split()
)

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")
_TOKEN_RE = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True)
class Chunk:
    """One searchable piece of a document."""

    source: str  # file name, e.g. "opening-hours.md"
    heading: str  # nearest heading above the text ("" if none)
    text: str

    @property
    def title(self) -> str:
        return f"{self.source} — {self.heading}" if self.heading else self.source


def stem(word: str) -> str:
    """A deliberately tiny stemmer: "grooming" -> "groom", "cancellations" -> "cancel".

    Strips a few common English endings, then keeps at most 6 letters, so word
    families ("vaccination", "vaccinations", "vaccinated") match each other.
    """
    for suffix in ("ing", "ed", "s"):
        if len(word) > len(suffix) + 3 and word.endswith(suffix) and not word.endswith("ss"):
            word = word[: -len(suffix)]
            break
    return word[:6]


def tokenize(text: str) -> List[str]:
    """Lowercase words, drop stopwords, stem the rest."""
    return [stem(w) for w in _TOKEN_RE.findall(text.lower()) if w not in STOPWORDS]


def _split_long(paragraphs: Sequence[str], max_chars: int) -> List[str]:
    """Group paragraphs into pieces of at most ~max_chars (never splits a paragraph)."""
    pieces: List[str] = []
    current: List[str] = []
    size = 0
    for para in paragraphs:
        if current and size + len(para) > max_chars:
            pieces.append("\n\n".join(current))
            current, size = [], 0
        current.append(para)
        size += len(para) + 2
    if current:
        pieces.append("\n\n".join(current))
    return pieces


def chunk_text(text: str, source: str, max_chars: int = MAX_CHUNK_CHARS) -> List[Chunk]:
    """Split a markdown/text document by headings, then by paragraphs if a section is long."""
    sections: List[Tuple[str, List[str]]] = []
    heading = ""
    lines: List[str] = []

    def flush() -> None:
        body = "\n".join(lines).strip()
        if body:
            sections.append((heading, [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]))

    for line in text.splitlines():
        match = _HEADING_RE.match(line)
        if match:
            flush()
            heading, lines = match.group(2).strip(), []
        else:
            lines.append(line)
    flush()

    chunks = []
    for sec_heading, paragraphs in sections:
        for piece in _split_long(paragraphs, max_chars):
            chunks.append(Chunk(source=source, heading=sec_heading, text=piece))
    return chunks


def load_chunks(folder: Path) -> List[Chunk]:
    folder = Path(folder)
    if not folder.is_dir():
        raise FileNotFoundError(f"Docs folder not found: {folder}")
    chunks: List[Chunk] = []
    for path in sorted(folder.rglob("*")):
        if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES:
            rel = path.relative_to(folder).as_posix()
            chunks.extend(chunk_text(path.read_text(encoding="utf-8"), rel))
    return chunks


class KnowledgeBase:
    """BM25 ranking over chunks (the classic formula search engines started with)."""

    def __init__(self, chunks: Sequence[Chunk], k1: float = 1.5, b: float = 0.75):
        self.chunks = list(chunks)
        self.k1, self.b = k1, b
        # Headings count as text too, so "Cancellation policy" matches "cancel".
        self._tfs = [Counter(tokenize(f"{c.heading} {c.text}")) for c in self.chunks]
        self._lens = [sum(tf.values()) for tf in self._tfs]
        self._avg_len = (sum(self._lens) / len(self._lens)) if self._lens else 0.0
        df: Counter = Counter()
        for tf in self._tfs:
            df.update(tf.keys())
        n = len(self.chunks)
        self._idf = {t: math.log(1 + (n - d + 0.5) / (d + 0.5)) for t, d in df.items()}

    @classmethod
    def from_folder(cls, folder: Path) -> "KnowledgeBase":
        return cls(load_chunks(folder))

    def search(self, query: str, top_k: int = 4, min_score: float = 1.5) -> List[Tuple[float, Chunk]]:
        """Return up to top_k (score, chunk) pairs, best first, dropping weak matches."""
        terms = set(tokenize(query))
        if not terms or not self.chunks:
            return []
        results = []
        for chunk, tf, length in zip(self.chunks, self._tfs, self._lens):
            score = 0.0
            for term in terms:
                freq = tf.get(term)
                if not freq:
                    continue
                norm = freq * (self.k1 + 1) / (freq + self.k1 * (1 - self.b + self.b * length / self._avg_len))
                score += self._idf[term] * norm
            if score >= min_score:
                results.append((score, chunk))
        results.sort(key=lambda pair: pair[0], reverse=True)
        return results[:top_k]
