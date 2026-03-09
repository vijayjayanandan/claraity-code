"""
Provider-agnostic attachment model for multimodal LLM input.

This module defines the core Attachment structure used throughout the pipeline:
- UI layer (ChatInput, AttachmentManager)
- Agent layer (stream_response)
- LLM adapter layer (payload generation)

The actual conversion to provider-specific formats (OpenAI, Anthropic, etc.)
happens in the LLM adapter layer, NOT here.
"""

import base64
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Optional

# Size limits (configurable)
MAX_IMAGE_SIZE_MB = 10  # 10MB max for images
MAX_TEXT_FILE_SIZE_KB = 100  # 100KB max for text files (to avoid token explosion)
MAX_ATTACHMENTS_PER_MESSAGE = 10


@dataclass
class Attachment:
    """
    Provider-agnostic attachment for multimodal LLM input.

    This is the ONLY attachment structure used in the pipeline.
    UI and Agent layers pass list[Attachment] - never provider-specific schemas.

    Attributes:
        kind: "image" or "text" - determines how it's sent to LLM
        filename: Original filename for display and context
        mime: MIME type (e.g., "image/png", "text/plain", "text/x-python")
        data: Raw bytes for binary content (images)
        text: Text content for text files (already decoded)

    Usage:
        # Image attachment (screenshot)
        att = Attachment(
            kind="image",
            filename="screenshot_1.png",
            mime="image/png",
            data=png_bytes,
        )

        # Text file attachment
        att = Attachment(
            kind="text",
            filename="config.py",
            mime="text/x-python",
            text="DEBUG = True\\n...",
        )
    """
    kind: Literal["image", "text"]
    filename: str
    mime: str
    data: bytes | None = None  # For binary (images)
    text: str | None = None    # For text files
    created_at: datetime = field(default_factory=datetime.now)

    def __post_init__(self):
        """Validate attachment has appropriate content."""
        if self.kind == "image" and self.data is None:
            raise ValueError("Image attachment requires 'data' (bytes)")
        if self.kind == "text" and self.text is None:
            raise ValueError("Text attachment requires 'text' (str)")

    @property
    def size_bytes(self) -> int:
        """Size in bytes."""
        if self.data:
            return len(self.data)
        if self.text:
            return len(self.text.encode('utf-8'))
        return 0

    @property
    def size_kb(self) -> float:
        """Size in KB."""
        return self.size_bytes / 1024

    @property
    def size_mb(self) -> float:
        """Size in MB."""
        return self.size_bytes / (1024 * 1024)

    @property
    def base64_data(self) -> str:
        """Base64 encoded data (for images)."""
        if self.data:
            return base64.b64encode(self.data).decode('utf-8')
        return ""

    @property
    def data_url(self) -> str:
        """Data URL for embedding (e.g., data:image/png;base64,...)."""
        if self.data:
            return f"data:{self.mime};base64,{self.base64_data}"
        return ""

    def is_oversized(self) -> bool:
        """Check if attachment exceeds size limits."""
        if self.kind == "image":
            return self.size_mb > MAX_IMAGE_SIZE_MB
        else:
            return self.size_kb > MAX_TEXT_FILE_SIZE_KB

    def get_size_limit_exceeded_msg(self) -> str | None:
        """Get human-readable message if size limit exceeded."""
        if self.kind == "image" and self.size_mb > MAX_IMAGE_SIZE_MB:
            return f"Image too large: {self.size_mb:.1f}MB (max {MAX_IMAGE_SIZE_MB}MB)"
        if self.kind == "text" and self.size_kb > MAX_TEXT_FILE_SIZE_KB:
            return f"Text file too large: {self.size_kb:.1f}KB (max {MAX_TEXT_FILE_SIZE_KB}KB)"
        return None

    def truncated_text(self, max_chars: int = 50000) -> str:
        """
        Get text content, truncated if necessary.

        Args:
            max_chars: Maximum characters to return

        Returns:
            Text content, possibly truncated with indicator
        """
        if not self.text:
            return ""
        if len(self.text) <= max_chars:
            return self.text
        return self.text[:max_chars] + f"\n\n[... TRUNCATED - {len(self.text) - max_chars} chars omitted ...]"

    def __repr__(self) -> str:
        return f"Attachment(kind={self.kind!r}, filename={self.filename!r}, size={self.size_kb:.1f}KB)"


def create_image_attachment(
    image_bytes: bytes,
    filename: str = "image.png",
    mime: str = "image/png"
) -> Attachment:
    """
    Factory function to create an image attachment.

    Args:
        image_bytes: Raw image bytes (PNG, JPEG, etc.)
        filename: Display filename
        mime: MIME type

    Returns:
        Attachment with kind="image"
    """
    return Attachment(
        kind="image",
        filename=filename,
        mime=mime,
        data=image_bytes,
    )


def create_text_attachment(
    text_content: str,
    filename: str,
    mime: str | None = None
) -> Attachment:
    """
    Factory function to create a text attachment.

    Args:
        text_content: Text content (already decoded)
        filename: Display filename
        mime: MIME type (auto-detected from extension if not provided)

    Returns:
        Attachment with kind="text"
    """
    if mime is None:
        # Auto-detect from filename
        import mimetypes
        mime, _ = mimetypes.guess_type(filename)
        if mime is None:
            mime = "text/plain"

    return Attachment(
        kind="text",
        filename=filename,
        mime=mime,
        text=text_content,
    )


# Additional text file extensions not in Python's mimetypes
TEXT_FILE_EXTENSIONS = {
    '.md': 'text/markdown',
    '.markdown': 'text/markdown',
    '.log': 'text/plain',
    '.yml': 'text/yaml',
    '.yaml': 'text/yaml',
    '.toml': 'text/toml',
    '.ini': 'text/plain',
    '.cfg': 'text/plain',
    '.conf': 'text/plain',
    '.sh': 'text/x-shellscript',
    '.bash': 'text/x-shellscript',
    '.zsh': 'text/x-shellscript',
    '.fish': 'text/x-shellscript',
    '.ps1': 'text/x-powershell',
    '.bat': 'text/x-batch',
    '.cmd': 'text/x-batch',
    '.env': 'text/plain',
    '.gitignore': 'text/plain',
    '.dockerignore': 'text/plain',
    '.editorconfig': 'text/plain',
    '.tsx': 'text/typescript-jsx',
    '.jsx': 'text/javascript-jsx',
    '.vue': 'text/vue',
    '.svelte': 'text/svelte',
    '.rs': 'text/x-rust',
    '.go': 'text/x-go',
    '.kt': 'text/x-kotlin',
    '.scala': 'text/x-scala',
    '.r': 'text/x-r',
    '.sql': 'text/x-sql',
    '.graphql': 'text/x-graphql',
    '.proto': 'text/x-protobuf',
}


def create_attachment_from_file(file_path: str) -> Attachment:
    """
    Factory function to create an attachment from a file path.

    Automatically determines kind based on MIME type.

    Args:
        file_path: Path to file

    Returns:
        Attachment (image or text based on content)

    Raises:
        FileNotFoundError: If file doesn't exist
        ValueError: If file type not supported
    """
    import mimetypes
    from pathlib import Path

    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    # Determine MIME type - check our custom mappings first
    ext = path.suffix.lower()
    mime = TEXT_FILE_EXTENSIONS.get(ext)

    if mime is None:
        mime, _ = mimetypes.guess_type(str(path))

    if mime is None:
        mime = "application/octet-stream"

    filename = path.name
    content = path.read_bytes()

    # Determine kind based on MIME type
    if mime.startswith("image/"):
        return Attachment(
            kind="image",
            filename=filename,
            mime=mime,
            data=content,
        )
    elif mime.startswith("text/") or mime in ("application/json", "application/xml", "application/javascript"):
        try:
            text = content.decode('utf-8')
        except UnicodeDecodeError:
            text = content.decode('latin-1')  # Fallback

        return Attachment(
            kind="text",
            filename=filename,
            mime=mime,
            text=text,
        )
    else:
        raise ValueError(f"Unsupported file type: {mime} for {filename}")


def validate_attachments(attachments: list[Attachment]) -> list[str]:
    """
    Validate a list of attachments.

    Args:
        attachments: list of attachments to validate

    Returns:
        list of error messages (empty if all valid)
    """
    errors = []

    if len(attachments) > MAX_ATTACHMENTS_PER_MESSAGE:
        errors.append(f"Too many attachments: {len(attachments)} (max {MAX_ATTACHMENTS_PER_MESSAGE})")

    for att in attachments:
        size_error = att.get_size_limit_exceeded_msg()
        if size_error:
            errors.append(size_error)

    return errors
