"""OAuth token storage for MCP servers.

Primary:  OS keyring (Windows Credential Manager / macOS Keychain / libsecret)
          Encrypted at rest, tied to OS user login.
Fallback: ~/.claraity/mcp_auth/<server_id>/ with restricted file permissions.
          Used when keyring is unavailable (WSL default, headless Linux, TUI).

Each MCP server gets isolated storage keyed by server_id so tokens from
different servers never collide.

To clear stored credentials (forces re-login):
    storage = KeyringTokenStorage("atlassian-rovo")
    storage.clear()
"""

import asyncio
import logging
import stat
import sys
from pathlib import Path

try:
    from src.observability import get_logger

    logger = get_logger("integrations.mcp.token_storage")
except ImportError:
    logger = logging.getLogger(__name__)

from mcp.client.auth import TokenStorage
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

# File fallback location -- user home dir, NOT project dir (avoids git accidents)
_AUTH_DIR = Path.home() / ".claraity" / "mcp_auth"

KEYRING_SERVICE = "claraity-mcp"


class KeyringTokenStorage(TokenStorage):
    """OAuth token storage: keyring primary, file fallback.

    Usage:
        storage = KeyringTokenStorage("atlassian-rovo")
        oauth = OAuthClientProvider(server_url=..., storage=storage, ...)
    """

    def __init__(self, server_id: str):
        self.server_id = server_id
        self._file_dir = _AUTH_DIR / server_id
        self._use_keyring = self._probe_keyring()

    def _probe_keyring(self) -> bool:
        """Check if a usable keyring backend is available via a read/write probe."""
        try:
            import keyring

            keyring.set_password(KEYRING_SERVICE, "__probe__", "ok")
            result = keyring.get_password(KEYRING_SERVICE, "__probe__")
            keyring.delete_password(KEYRING_SERVICE, "__probe__")
            if result == "ok":
                backend = type(keyring.get_keyring()).__name__
                logger.info("mcp_keyring_available", backend=backend, server=self.server_id)
                return True
        except Exception as e:
            logger.warning(
                "mcp_keyring_unavailable",
                server=self.server_id,
                error=str(e),
                fallback=str(self._file_dir),
            )
        return False

    # -- Keyring helpers --

    def _kr_get(self, key: str) -> str | None:
        try:
            import keyring

            return keyring.get_password(KEYRING_SERVICE, f"{self.server_id}:{key}")
        except Exception as e:
            logger.warning("mcp_keyring_read_failed", key=key, error=str(e))
            return None

    def _kr_set(self, key: str, value: str) -> None:
        try:
            import keyring

            keyring.set_password(KEYRING_SERVICE, f"{self.server_id}:{key}", value)
        except Exception as e:
            logger.warning("mcp_keyring_write_failed", key=key, error=str(e))

    def _kr_delete(self, key: str) -> None:
        try:
            import keyring

            keyring.delete_password(KEYRING_SERVICE, f"{self.server_id}:{key}")
        except Exception:
            pass

    # -- File fallback helpers --

    def _file_path(self, key: str) -> Path:
        return self._file_dir / f"{key}.json"

    def _file_read(self, key: str) -> str | None:
        path = self._file_path(key)
        if not path.exists():
            return None
        try:
            return path.read_text(encoding="utf-8")
        except Exception as e:
            logger.warning("mcp_auth_file_read_failed", path=str(path), error=str(e))
            return None

    def _file_write(self, key: str, value: str) -> None:
        self._file_dir.mkdir(parents=True, exist_ok=True)
        # Restrict directory to owner only (chmod 700)
        # On Windows this is best-effort -- NTFS ACLs require icacls for full control
        try:
            if sys.platform != "win32":
                self._file_dir.chmod(stat.S_IRWXU)
        except Exception:
            pass
        path = self._file_path(key)
        path.write_text(value, encoding="utf-8")
        # Restrict file to owner read/write only (chmod 600)
        try:
            if sys.platform != "win32":
                path.chmod(stat.S_IRUSR | stat.S_IWUSR)
        except Exception:
            pass

    def _file_delete(self, key: str) -> None:
        path = self._file_path(key)
        if path.exists():
            try:
                path.unlink()
            except Exception:
                pass

    # -- TokenStorage interface --

    async def get_tokens(self) -> OAuthToken | None:
        if self._use_keyring:
            raw = await asyncio.to_thread(self._kr_get, "tokens")
        else:
            raw = await asyncio.to_thread(self._file_read, "tokens")
        if not raw:
            return None
        try:
            return OAuthToken.model_validate_json(raw)
        except Exception as e:
            logger.warning("mcp_token_parse_failed", server=self.server_id, error=str(e))
            return None

    async def set_tokens(self, tokens: OAuthToken) -> None:
        value = tokens.model_dump_json()
        if self._use_keyring:
            await asyncio.to_thread(self._kr_set, "tokens", value)
        else:
            await asyncio.to_thread(self._file_write, "tokens", value)
        logger.info(
            "mcp_token_saved",
            server=self.server_id,
            backend="keyring" if self._use_keyring else "file",
        )

    async def get_client_info(self) -> OAuthClientInformationFull | None:
        if self._use_keyring:
            raw = await asyncio.to_thread(self._kr_get, "client")
        else:
            raw = await asyncio.to_thread(self._file_read, "client")
        if not raw:
            return None
        try:
            return OAuthClientInformationFull.model_validate_json(raw)
        except Exception as e:
            logger.warning("mcp_client_info_parse_failed", server=self.server_id, error=str(e))
            return None

    async def set_client_info(self, info: OAuthClientInformationFull) -> None:
        value = info.model_dump_json()
        if self._use_keyring:
            await asyncio.to_thread(self._kr_set, "client", value)
        else:
            await asyncio.to_thread(self._file_write, "client", value)
        logger.info(
            "mcp_client_info_saved",
            server=self.server_id,
            backend="keyring" if self._use_keyring else "file",
        )

    def clear(self) -> None:
        """Remove all stored credentials for this server. Forces re-login on next connect."""
        for key in ("tokens", "client"):
            self._kr_delete(key)
            self._file_delete(key)
        logger.info("mcp_credentials_cleared", server=self.server_id)
