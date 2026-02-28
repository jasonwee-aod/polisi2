"""HTML parser preserving section heading context."""

from __future__ import annotations

from bs4 import BeautifulSoup

from polisi_scraper.indexer.parsers.base import DocumentParser, ParsedBlock, ParsedDocument


class HtmlParser(DocumentParser):
    file_type = "html"

    def parse_bytes(
        self,
        payload: bytes,
        *,
        metadata: dict[str, object] | None = None,
    ) -> ParsedDocument:
        soup = BeautifulSoup(payload.decode("utf-8", errors="ignore"), "html.parser")
        root = soup.body or soup
        current_heading: str | None = None
        blocks: list[ParsedBlock] = []

        for node in root.find_all(
            ["h1", "h2", "h3", "h4", "p", "li", "table"],
            recursive=True,
        ):
            text = node.get_text(" ", strip=True)
            if not text:
                continue
            if node.name in {"h1", "h2", "h3", "h4"}:
                current_heading = text
                continue
            block_type = "table" if node.name == "table" else "list_item" if node.name == "li" else "paragraph"
            blocks.append(
                ParsedBlock(
                    text=text,
                    block_type=block_type,
                    section_heading=current_heading,
                )
            )

        return ParsedDocument(
            file_type=self.file_type,
            title=_extract_title(soup),
            blocks=blocks,
            metadata=dict(metadata or {}),
        )


def _extract_title(soup: BeautifulSoup) -> str | None:
    if soup.title and soup.title.string:
        text = soup.title.string.strip()
        if text:
            return text
    return None
