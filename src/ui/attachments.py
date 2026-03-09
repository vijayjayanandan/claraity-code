"""
In-memory attachment handling for TUI.

Attachments (screenshots, files) are stored in memory only - no filesystem writes.
This ensures privacy and avoids disk clutter.

Uses the core Attachment model for provider-agnostic representation.
"""

import asyncio
import mimetypes

from src.observability import get_logger

logger = get_logger(__name__)

# Import the core Attachment model (provider-agnostic)
from src.core.attachment import (
    MAX_ATTACHMENTS_PER_MESSAGE,
    MAX_IMAGE_SIZE_MB,
    MAX_TEXT_FILE_SIZE_KB,
    Attachment,
    create_attachment_from_file,
    create_image_attachment,
    create_text_attachment,
    validate_attachments,
)

# Re-export for convenience
__all__ = [
    "Attachment",
    "AttachmentManager",
    "create_image_attachment",
    "create_text_attachment",
]


class AttachmentManager:
    """
    Manages in-memory attachments for the current message.

    Attachments are cleared after the message is submitted.
    Uses the core Attachment model for provider-agnostic representation.
    """

    # Maximum total size in MB
    MAX_TOTAL_SIZE_MB = 20

    def __init__(self):
        self._attachments: list[Attachment] = []
        self._screenshot_counter = 0

    def add_screenshot(self, image_bytes: bytes, format: str = "png") -> Attachment:
        """
        Add screenshot from clipboard.

        Args:
            image_bytes: PNG image data
            format: Image format (default: "png")

        Returns:
            Created Attachment

        Raises:
            ValueError: If max attachments reached or size exceeded
        """
        self._check_limits(len(image_bytes))

        # Check image size limit
        size_mb = len(image_bytes) / (1024 * 1024)
        if size_mb > MAX_IMAGE_SIZE_MB:
            raise ValueError(f"Image too large: {size_mb:.1f}MB (max {MAX_IMAGE_SIZE_MB}MB)")

        # Generate unique filename with timestamp
        from datetime import datetime

        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        self._screenshot_counter += 1
        filename = f"screenshot_{timestamp}_{self._screenshot_counter}.{format}"

        logger.debug(
            "screenshot_filename_generated", filename=filename, counter=self._screenshot_counter
        )

        attachment = create_image_attachment(
            image_bytes=image_bytes,
            filename=filename,
            mime=f"image/{format}",
        )

        logger.debug("attachment_created", filename=attachment.filename, size_kb=attachment.size_kb)

        self._attachments.append(attachment)
        return attachment

    async def add_file(self, file_path: str) -> Attachment:
        """
        Add file from path (reads content into memory).

        Args:
            file_path: Path to file

        Returns:
            Created Attachment

        Raises:
            ValueError: If max attachments reached, size exceeded, or unsupported type
            FileNotFoundError: If file doesn't exist
        """
        from pathlib import Path

        path = Path(file_path)

        if not path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        # Read file content in thread pool to avoid blocking UI
        content = await asyncio.to_thread(path.read_bytes)
        self._check_limits(len(content))

        # Use factory function which handles type detection (also in thread pool)
        attachment = await asyncio.to_thread(create_attachment_from_file, file_path)

        # Check size limits based on kind
        size_error = attachment.get_size_limit_exceeded_msg()
        if size_error:
            raise ValueError(size_error)

        self._attachments.append(attachment)
        return attachment

    def _check_limits(self, new_size: int) -> None:
        """Check if adding new attachment would exceed limits."""
        if len(self._attachments) >= MAX_ATTACHMENTS_PER_MESSAGE:
            raise ValueError(f"Maximum {MAX_ATTACHMENTS_PER_MESSAGE} attachments allowed")

        current_size = sum(a.size_bytes for a in self._attachments)
        total_size_mb = (current_size + new_size) / (1024 * 1024)

        if total_size_mb > self.MAX_TOTAL_SIZE_MB:
            raise ValueError(f"Total attachment size would exceed {self.MAX_TOTAL_SIZE_MB}MB")

    def remove(self, index: int) -> None:
        """Remove attachment by index."""
        if 0 <= index < len(self._attachments):
            del self._attachments[index]

    def clear(self) -> None:
        """Clear all attachments (after message sent)."""
        self._attachments.clear()

    @property
    def attachments(self) -> list[Attachment]:
        """Get current attachments (copy to prevent mutation)."""
        return self._attachments.copy()

    @property
    def count(self) -> int:
        """Number of attachments."""
        return len(self._attachments)

    @property
    def total_size_kb(self) -> float:
        """Total size of all attachments in KB."""
        return sum(a.size_kb for a in self._attachments)

    def get_summary(self) -> str:
        """
        Summary string for display in input border.

        Returns:
            String like "[Image #1] [Image #2] [FILE: config.py]" or empty string
        """
        if not self._attachments:
            return ""

        parts = []
        image_count = 0
        for att in self._attachments:
            if att.kind == "image":
                image_count += 1
                parts.append(f"[Image #{image_count}]")
            else:
                parts.append(f"[FILE: {att.filename}]")

        return " ".join(parts)

    def validate(self) -> list[str]:
        """
        Validate all attachments.

        Returns:
            list of error messages (empty if all valid)
        """
        return validate_attachments(self._attachments)

    def __len__(self) -> int:
        return len(self._attachments)

    def __bool__(self) -> bool:
        return len(self._attachments) > 0
