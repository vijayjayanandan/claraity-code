# Notes

- ClarAIty Code is an AI-powered coding agent with both a Textual-based TUI and a simpler CLI mode (`README.md:3`, `README.md:35`).
- The project emphasizes built-in tool use, including file operations, code search, shell execution, planning, and subagent delegation (`README.md:37`, `README.md:46`, `README.md:48`).
- It supports multiple LLM providers through OpenAI-compatible APIs, including Claude, GPT, Qwen, DeepSeek, and Ollama (`README.md:51`, `README.md:55`, `README.md:60`).
- The codebase is organized into many focused `src/` packages such as `core`, `llm`, `tools`, `ui`, `server`, `subagents`, and `observability`, which suggests a modular architecture (`src/`).
- The package is published as `claraity-code`, requires Python 3.10+, and exposes CLI entry points like `claraity` and `claraity-server` (`pyproject.toml:6`, `pyproject.toml:13`, `pyproject.toml:82`).
