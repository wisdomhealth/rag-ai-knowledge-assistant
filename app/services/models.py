from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DocumentPage:
    """Extracted text from one logical document page or whole text file."""

    file_name: str
    file_id: str
    source_link: str
    page_number: int | None
    text: str
