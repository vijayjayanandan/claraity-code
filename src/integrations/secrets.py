"""Secure secret storage abstraction.

Provides a SecretStore protocol with two backends:
- KeyringSecretStore: OS keychain via `keyring` library (preferred)
- EncryptedFileSecretStore: AES-256 Fernet fallback for headless environments

HARD RULE: Secret values must NEVER appear in logs, MessageStore, JSONL
session files, or ToolResult output. This module is the ONLY place that
reads/writes secret material.
"""

import json
import logging
import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

# Use our structured logging if available, otherwise stdlib
try:
    from src.observability import get_logger
    logger = get_logger("integrations.secrets")
except ImportError:
    logger = logging.getLogger(__name__)

# Service name used as namespace in OS keychain
_KEYRING_SERVICE = "claraity-agent"


class SecretStore(ABC):
    """Abstract interface for secret storage.

    Implementations must guarantee:
    - Values are encrypted at rest
    - get/set/delete/has are the only accessors
    - __repr__ and __str__ never expose stored values
    """

    @abstractmethod
    def get(self, key: str) -> Optional[str]:
        """Retrieve a secret. Returns None if not found."""

    @abstractmethod
    def set(self, key: str, value: str) -> None:
        """Store a secret (overwrites if exists)."""

    @abstractmethod
    def delete(self, key: str) -> None:
        """Remove a secret. No-op if not found."""

    @abstractmethod
    def has(self, key: str) -> bool:
        """Check if a secret exists without revealing its value."""


class KeyringSecretStore(SecretStore):
    """OS keychain backend (macOS Keychain, Windows Credential Locker, etc.)."""

    def __init__(self, service: str = _KEYRING_SERVICE):
        import keyring as _kr
        self._kr = _kr
        self._service = service

    def get(self, key: str) -> Optional[str]:
        try:
            return self._kr.get_password(self._service, key)
        except Exception:
            logger.warning("keyring_get_failed", key_name=key)
            return None

    def set(self, key: str, value: str) -> None:
        try:
            self._kr.set_password(self._service, key, value)
        except Exception:
            logger.error("keyring_set_failed", key_name=key)
            raise

    def delete(self, key: str) -> None:
        try:
            self._kr.delete_password(self._service, key)
        except Exception:
            # keyring raises if key doesn't exist on some backends
            pass

    def has(self, key: str) -> bool:
        return self.get(key) is not None


class EncryptedFileSecretStore(SecretStore):
    """AES-256 Fernet file backend (fallback when keyring unavailable).

    Secrets are stored in a single JSON file, encrypted with a Fernet key.
    The Fernet key is derived from CLARAITY_SECRET_KEY env var or
    auto-generated and stored in a separate key file.

    File layout:
        <store_dir>/secrets.enc   - Fernet-encrypted JSON blob
        <store_dir>/secret.key    - Fernet key (only if auto-generated)
    """

    def __init__(self, store_dir: Optional[Path] = None):
        from cryptography.fernet import Fernet

        self._store_dir = store_dir or Path(".clarity") / "secrets"
        self._store_dir.mkdir(parents=True, exist_ok=True)
        self._enc_path = self._store_dir / "secrets.enc"
        self._key_path = self._store_dir / "secret.key"
        self._fernet = Fernet(self._get_or_create_key())

    def _get_or_create_key(self) -> bytes:
        from cryptography.fernet import Fernet

        # Prefer env var
        env_key = os.environ.get("CLARAITY_SECRET_KEY")
        if env_key:
            return env_key.encode()

        # Auto-generate key file (first run)
        if self._key_path.exists():
            return self._key_path.read_bytes().strip()

        key = Fernet.generate_key()
        self._key_path.write_bytes(key)
        # Restrict permissions (best-effort on Windows)
        try:
            self._key_path.chmod(0o600)
        except OSError:
            pass
        return key

    def _load(self) -> dict:
        if not self._enc_path.exists():
            return {}
        try:
            encrypted = self._enc_path.read_bytes()
            decrypted = self._fernet.decrypt(encrypted)
            return json.loads(decrypted)
        except Exception:
            logger.warning("encrypted_store_load_failed")
            return {}

    def _save(self, data: dict) -> None:
        plaintext = json.dumps(data).encode()
        encrypted = self._fernet.encrypt(plaintext)
        self._enc_path.write_bytes(encrypted)

    def get(self, key: str) -> Optional[str]:
        return self._load().get(key)

    def set(self, key: str, value: str) -> None:
        data = self._load()
        data[key] = value
        self._save(data)

    def delete(self, key: str) -> None:
        data = self._load()
        data.pop(key, None)
        self._save(data)

    def has(self, key: str) -> bool:
        return key in self._load()


def get_secret_store(store_dir: Optional[Path] = None) -> SecretStore:
    """Factory: returns best available SecretStore backend.

    Tries OS keyring first; falls back to encrypted file store.
    """
    try:
        store = KeyringSecretStore()
        # Smoke-test: some keyring backends silently fail
        store._kr.get_password(_KEYRING_SERVICE, "__probe__")
        logger.info("secret_store_backend", backend="keyring")
        return store
    except Exception:
        pass

    logger.info("secret_store_backend", backend="encrypted_file")
    return EncryptedFileSecretStore(store_dir=store_dir)
