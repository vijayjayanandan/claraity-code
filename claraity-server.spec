# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the ClarAIty VS Code agent binary.

Builds a one-folder distribution:
    claraity-server.exe + _internal/

Excludes Textual/rich/trio (TUI-only) to keep size down (~58MB).

Build:
    .venv-build/Scripts/pyinstaller claraity-server.spec
    # Then copy dist/claraity-server/ -> claraity-vscode/bin/

Pre-release checklist:
    .venv-build/Scripts/python -m pip_audit  # Must show 0 vulnerabilities
"""

import sys
from pathlib import Path

block_cipher = None

# Collect all src/ Python files as data (PyInstaller sometimes misses
# dynamically imported subpackages)
src_root = Path("src")

a = Analysis(
    ["src/server/__main__.py"],
    pathex=["."],
    binaries=[],
    datas=[],
    hiddenimports=[
        # Core agent
        "src.core.agent",
        "src.core.protocol",
        "src.core.events",
        "src.core.attachment",
        "src.core.tool_gating",
        "src.core.special_tool_handlers",
        "src.core.stream_phases",
        "src.core.tool_loop_state",
        "src.core.error_recovery",
        "src.core.tool_metadata",
        # LLM backends
        "src.llm.base",
        "src.llm.openai_backend",
        "src.llm.ollama_backend",
        "src.llm.anthropic_backend",
        "src.llm.config_loader",
        "src.llm.credential_store",
        # Server
        "src.server.stdio_server",
        "src.server.config_handler",
        "src.server.serializers",
        "src.server.jsonrpc",
        "src.server.subagent_bridge",
        # Session
        "src.session.store.memory_store",
        "src.session.scanner",
        "src.session.manager.session_manager",
        # Subagents (needed for --subagent mode)
        "src.subagents",
        "src.subagents.runner",
        "src.subagents.ipc",
        "src.subagents.subagent",
        "src.subagents.config",
        # Tools
        "src.tools",
        "src.tools.base",
        "src.tools.delegation",
        "src.tools.file_operations",
        "src.tools.document_extractor",
        "src.tools.tool_schemas",
        "src.tools.knowledge_tools",
        # Memory
        "src.memory.memory_manager",
        "src.memory.working_memory",
        # Prompts
        "src.prompts.system_prompts",
        # Observability
        "src.observability",
        "src.observability.logging_config",
        "src.observability.transcript_logger",
        # Platform
        "src.platform.windows",
        # Integrations (lazy-loaded)
        "src.integrations.jira.connection",
        "src.integrations.jira.tools",
        "src.integrations.mcp.client",
        "src.integrations.mcp.config",
        "src.integrations.mcp.registry",
        "src.integrations.mcp.manager",
        "src.integrations.mcp.adapter",
        "src.integrations.mcp.bridge",
        "src.integrations.mcp.policy",
        "src.integrations.mcp.settings",
        "src.integrations.mcp.marketplace",
        # Testing
        "src.testing.test_runner",
        # Third-party hidden imports
        "anthropic",      # Anthropic LLM backend
        "fitz",           # PyMuPDF - PDF extraction
        "pymupdf",        # PyMuPDF alternate import name
        "docx",           # python-docx - Word extraction
        "bs4",
        "bs4.builder",
        "bs4.builder._htmlparser",
        "bs4.formatter",
        "bs4.element",
        "emoji",
        "pathspec",        # .claraityignore / .gitignore pattern matching
        "keyring",         # Credential store
        "cryptography",    # Fernet encryption for secrets
        "aiohttp",
        "aiohttp.web",
        "openai",
        "httpx",
        "pydantic",
        "yaml",
        # tiktoken encoding registry (PyInstaller misses the plugin-style import)
        "tiktoken",
        "tiktoken_ext",
        "tiktoken_ext.openai_public",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # TUI-only — not needed in VS Code server binary
        "textual",
        "rich",
        "trio",
        "trio_websocket",
        # Dev/test tools
        "pytest",
        "black",
        "ruff",
        "mypy",
        "isort",
        # Heavy unused stdlib
        "tkinter",
        "turtle",
        "unittest",
        "doctest",
        "pdb",
        "lib2to3",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="claraity-server",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="claraity-server",
)
