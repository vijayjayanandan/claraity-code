"""
Clipboard handling using PIL ImageGrab (cross-platform, robust).

This is the industry-standard approach used by professional tools like Claude Code.
PIL handles DIB->PNG conversion automatically and works on Windows + macOS.

Reference: https://pillow.readthedocs.io/en/stable/reference/ImageGrab.html
"""

from io import BytesIO
from pathlib import Path
from typing import Optional

from src.observability import get_logger

logger = get_logger(__name__)


class ClipboardHandler:
    """
    Handle clipboard operations using PIL ImageGrab.

    Supports three clipboard formats in priority order:
    1. Image data (screenshots, copied images)
    2. File list (files copied from Explorer)
    3. Text (regular text paste)
    """

    @classmethod
    def get_clipboard_content(cls) -> tuple[bytes | None, list[str] | None, str | None]:
        """
        Get clipboard content in priority order: image, files, text.

        Returns:
            tuple of (image_bytes, file_list, text) - only one will be non-None
        """
        # Try to get text first (safest, works everywhere)
        text = cls._get_text_fallback()

        # Try PIL for images/files (can sometimes cause issues)
        try:
            from PIL import ImageGrab

            result = ImageGrab.grabclipboard()

            if result is None:
                # No image or files - return text if we have it
                return None, None, text

            # Check if it's a list of files (CF_HDROP)
            if isinstance(result, list):
                # Filter to only existing files (not directories)
                try:
                    valid_files = [
                        f for f in result
                        if isinstance(f, str) and Path(f).exists() and Path(f).is_file()
                    ]
                    if valid_files:
                        return None, valid_files, None
                except Exception:
                    pass
                return None, None, text

            # It's an image - convert to PNG bytes
            try:
                output = BytesIO()
                # Convert to RGB if necessary (handles RGBA, P mode images)
                if hasattr(result, 'mode') and result.mode in ('RGBA', 'P'):
                    result = result.convert('RGB')
                result.save(output, format='PNG')
                image_bytes = output.getvalue()
                # SUCCESS - return image bytes
                return image_bytes, None, None
            except Exception as e:
                # Image conversion failed - log the error
                logger.error(f"ClipboardHandler: Image conversion failed: {e}", exc_info=True)
                # Fall back to text
                return None, None, text

        except ImportError as e:
            # PIL not available - use text only
            logger.error(f"ClipboardHandler: PIL not available: {e}")
            return None, None, text

        except Exception as e:
            # Any other error - return text if available
            logger.error(f"ClipboardHandler: Unexpected error: {e}", exc_info=True)
            return None, None, text

    @classmethod
    def _get_text_fallback(cls) -> str | None:
        """
        Get text from clipboard using pyperclip or ctypes fallback.

        Returns:
            Clipboard text or None
        """
        # Try pyperclip first (cross-platform)
        try:
            import pyperclip
            text = pyperclip.paste()
            if text:
                return text
        except ImportError:
            pass
        except Exception:
            pass

        # ctypes fallback for Windows (correct implementation)
        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.WinDLL("user32", use_last_error=True)
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

            CF_UNICODETEXT = 13

            # Set up function signatures
            user32.OpenClipboard.argtypes = [wintypes.HWND]
            user32.OpenClipboard.restype = wintypes.BOOL
            user32.CloseClipboard.argtypes = []
            user32.CloseClipboard.restype = wintypes.BOOL
            user32.IsClipboardFormatAvailable.argtypes = [wintypes.UINT]
            user32.IsClipboardFormatAvailable.restype = wintypes.BOOL
            user32.GetClipboardData.argtypes = [wintypes.UINT]
            user32.GetClipboardData.restype = wintypes.HANDLE

            kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
            kernel32.GlobalLock.restype = wintypes.LPVOID
            kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
            kernel32.GlobalUnlock.restype = wintypes.BOOL

            if not user32.OpenClipboard(None):
                return None

            try:
                if not user32.IsClipboardFormatAvailable(CF_UNICODETEXT):
                    return None

                hglobal = user32.GetClipboardData(CF_UNICODETEXT)
                if not hglobal:
                    return None

                ptr = kernel32.GlobalLock(hglobal)
                if not ptr:
                    return None

                try:
                    # Read null-terminated UTF-16 string
                    return ctypes.wstring_at(ptr)
                finally:
                    kernel32.GlobalUnlock(hglobal)

            finally:
                user32.CloseClipboard()

        except Exception:
            pass

        return None

    @classmethod
    def has_image(cls) -> bool:
        """
        Check if clipboard contains an image.

        Returns:
            True if clipboard has image data
        """
        try:
            from PIL import ImageGrab
            result = ImageGrab.grabclipboard()
            # It's an image if it's not None and not a list
            return result is not None and not isinstance(result, list)
        except Exception:
            return False

    @classmethod
    def has_files(cls) -> bool:
        """
        Check if clipboard contains files.

        Returns:
            True if clipboard has file list
        """
        try:
            from PIL import ImageGrab
            result = ImageGrab.grabclipboard()
            if isinstance(result, list):
                return any(Path(f).exists() and Path(f).is_file() for f in result)
            return False
        except Exception:
            return False
