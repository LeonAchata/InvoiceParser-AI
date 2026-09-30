from dataclasses import dataclass, field
from typing import Any


class UnsupportedFormatError(ValueError):
    """Raised when a file cannot be turned into text or images."""


@dataclass
class ImagePart:
    mime: str
    data: bytes


@dataclass
class LoadedDocument:
    """Normalized representation of any input file: text, page images, or both."""

    format: str
    text: str = ""
    images: list[ImagePart] = field(default_factory=list)
    pages: int = 1
    method: str = "text"
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def has_content(self) -> bool:
        return bool(self.text.strip()) or bool(self.images)

    def merge(self, other: "LoadedDocument", label: str) -> None:
        """Append another document (e.g. an email attachment) to this one."""
        if other.text.strip():
            self.text += f"\n\n--- {label} ---\n{other.text}"
        self.images.extend(other.images)
        self.pages += other.pages
