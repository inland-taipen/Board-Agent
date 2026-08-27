"""Segment -> chunk conversion.

Chunks are the unit the model cites. Two rules follow from that:

1. A chunk never spans two documents or two pages. If it did, a citation could
   not be resolved to a single source page, which is the BRD's hard audit
   requirement.
2. Chunk IDs are short and stable (`c0041`). The model repeats them dozens of
   times in a briefing, so verbose IDs cost real tokens and invite typos.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..ingest.base import Segment

# Board text averages close to 4 characters per token; exact counts come from
# the API when it matters, this is only for splitting.
CHARS_PER_TOKEN = 4


@dataclass(slots=True)
class Chunk:
    chunk_id: str
    doc_id: str
    doc_name: str
    doc_kind: str
    page: int
    locator: str
    text: str
    heading: str | None = None
    kind: str = "body"
    meta: dict = field(default_factory=dict)

    @property
    def citation(self) -> str:
        return f"{self.doc_name}, {self.locator}"

    def render(self) -> str:
        """The form the model sees. The ID leads so it is impossible to miss."""
        head = f"[{self.chunk_id}] {self.doc_name} ({self.doc_kind}) - {self.locator}"
        if self.heading:
            head += f" - {self.heading}"
        return f"{head}\n{self.text}"


def chunk_segments(
    segments: list[Segment],
    *,
    doc_id: str,
    doc_name: str,
    doc_kind: str,
    start_index: int = 0,
    target_tokens: int = 700,
    overlap_tokens: int = 100,
) -> list[Chunk]:
    """Split one document's segments into citable chunks.

    Returns chunks numbered from `start_index` so IDs stay unique across the
    whole board pack, not just within one file.
    """
    target_chars = target_tokens * CHARS_PER_TOKEN
    overlap_chars = overlap_tokens * CHARS_PER_TOKEN

    chunks: list[Chunk] = []
    counter = start_index

    for segment in segments:
        text = segment.text.strip()
        if not text:
            continue

        for piece in _split(text, target_chars, overlap_chars):
            chunks.append(
                Chunk(
                    chunk_id=f"c{counter:04d}",
                    doc_id=doc_id,
                    doc_name=doc_name,
                    doc_kind=doc_kind,
                    page=segment.page,
                    locator=segment.locator,
                    text=piece,
                    heading=segment.heading,
                    kind=segment.kind,
                    meta=dict(segment.meta),
                )
            )
            counter += 1

    return chunks


def _split(text: str, target_chars: int, overlap_chars: int) -> list[str]:
    """Split on paragraph, then line, then hard character boundaries.

    Tables are line-oriented; prose is paragraph-oriented. Trying paragraphs
    first and falling through keeps risk-register rows intact instead of
    slicing a row in half.
    """
    if len(text) <= target_chars:
        return [text]

    units = text.split("\n\n")
    if max((len(u) for u in units), default=0) > target_chars:
        units = text.split("\n")

    pieces: list[str] = []
    buf: list[str] = []
    size = 0

    for unit in units:
        if len(unit) > target_chars:
            if buf:
                pieces.append("\n".join(buf))
                buf, size = [], 0
            pieces.extend(
                unit[i : i + target_chars] for i in range(0, len(unit), target_chars)
            )
            continue

        if size + len(unit) > target_chars and buf:
            pieces.append("\n".join(buf))
            tail = _tail(buf, overlap_chars)
            buf = list(tail)
            size = sum(len(x) for x in buf)

        buf.append(unit)
        size += len(unit) + 1

    if buf:
        pieces.append("\n".join(buf))

    return [p.strip() for p in pieces if p.strip()]


def _tail(units: list[str], overlap_chars: int) -> list[str]:
    """Carry the trailing units forward so a split never orphans context."""
    out: list[str] = []
    size = 0
    for unit in reversed(units):
        if size + len(unit) > overlap_chars:
            break
        out.insert(0, unit)
        size += len(unit)
    return out
