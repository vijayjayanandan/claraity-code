"""LLM Configuration Wizard Screen.

A modal screen that allows users to configure the LLM backend, model,
and per-subagent model overrides. Saves to `.clarity/config.yaml`.

Triggered via:
- Command palette: Ctrl+P -> "Configure LLM"
- Slash command: /config-llm

Follows the SessionPickerScreen pattern (ModalScreen with dismiss).
"""

from pathlib import Path

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.suggester import SuggestFromList
from textual.widgets import (
    Button,
    Checkbox,
    Input,
    OptionList,
    Select,
    Static,
)
from textual.widgets.option_list import Option

from src.llm.config_loader import (
    DEFAULT_CONFIG_PATH,
    LLMConfigData,
    SubAgentLLMOverride,
    load_llm_config,
    save_llm_config,
)
from src.observability import get_logger

logger = get_logger("ui.llm_config_screen")

# Backend choices for the Select widget
BACKEND_CHOICES = [
    ("openai", "openai"),
    ("anthropic", "anthropic"),
    ("ollama", "ollama"),
]


class ConfigLLMScreen(ModalScreen[LLMConfigData | None]):
    """
    Modal screen for configuring the LLM backend, model selection,
    and per-subagent model overrides.

    Returns:
        LLMConfigData on save, None on cancel.
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
    ]

    DEFAULT_CSS = """
    ConfigLLMScreen {
        align: center middle;
    }

    ConfigLLMScreen > Vertical {
        width: 90%;
        max-width: 100;
        height: auto;
        max-height: 90%;
        background: $surface;
        border: thick $primary;
        padding: 1 2;
        overflow-y: auto;
    }

    ConfigLLMScreen #title {
        text-align: center;
        text-style: bold;
        color: $text;
        padding-bottom: 1;
    }

    ConfigLLMScreen .field-label {
        margin-top: 1;
        color: $text-muted;
    }

    ConfigLLMScreen Input {
        margin-bottom: 0;
    }

    ConfigLLMScreen #btn-row {
        margin-top: 1;
        height: auto;
        align: center middle;
    }

    ConfigLLMScreen #btn-row Button {
        margin: 0 1;
    }

    ConfigLLMScreen #fetch-row {
        height: auto;
        margin-top: 1;
        align: left middle;
    }

    ConfigLLMScreen #model-list {
        height: 8;
        margin-top: 0;
        margin-bottom: 0;
    }

    ConfigLLMScreen #fetch-status {
        color: $text-muted;
        margin-left: 1;
    }

    ConfigLLMScreen .subagent-row {
        height: auto;
        align: left middle;
    }

    ConfigLLMScreen .subagent-label {
        width: 20;
        color: $text;
    }

    ConfigLLMScreen .subagent-select {
        width: 1fr;
    }

    ConfigLLMScreen .subagent-input {
        width: 1fr;
    }
    """

    def __init__(
        self,
        config_path: str = DEFAULT_CONFIG_PATH,
        subagent_names: list[str] | None = None,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ):
        super().__init__(name=name, id=id, classes=classes)
        self._config_path = config_path
        self._config: LLMConfigData = load_llm_config(config_path)
        self._fetched_models: list[str] = []
        # Hardcoded fallback ensures subagents always show
        self._subagent_names: list[str] = subagent_names or [
            "code-reviewer",
            "test-writer",
            "doc-writer",
            "code-writer",
            "explore",
            "planner",
            "general-purpose",
        ]

    def compose(self) -> ComposeResult:
        """Compose the LLM configuration wizard UI."""
        with Vertical():
            yield Static("Configure LLM", id="title")

            # Backend selector
            yield Static("Backend:", classes="field-label")
            yield Select(
                BACKEND_CHOICES,
                value=self._config.backend_type or "openai",
                id="backend-select",
                allow_blank=False,
            )

            # API URL
            yield Static("API URL:", classes="field-label")
            yield Input(
                value=self._config.base_url or "",
                placeholder="http://localhost:8000/v1",
                id="base-url",
            )

            # API Key (masked -- saved to OS credential store, not config.yaml)
            yield Static("API Key:", classes="field-label")
            yield Input(
                value=self._config.api_key or "",
                placeholder="Enter your API key",
                password=True,
                id="api-key",
            )

            # Fetch models button
            with Horizontal(id="fetch-row"):
                yield Button("Fetch Models", id="btn-fetch", variant="default")
                yield Static("", id="fetch-status")

            # Model list
            yield Static("Main Agent Model:", classes="field-label")
            yield OptionList(id="model-list")

            # Model manual input (fallback)
            yield Static("Or type model name:", classes="field-label")
            yield Input(
                value=self._config.model or "",
                placeholder="gpt-4o",
                id="model-input",
            )

            # Per-subagent model overrides
            yield Static("Subagent Models:", classes="field-label")
            yield Checkbox(
                "Use same model for all subagents",
                value=False,
                id="same-model-check",
            )
            for sa_name in self._subagent_names:
                existing_model = ""
                if sa_name in self._config.subagents:
                    existing_model = self._config.subagents[sa_name].model or ""
                with Horizontal(classes="subagent-row"):
                    yield Static(f"  {sa_name}:", classes="subagent-label")
                    yield Input(
                        value=existing_model,
                        placeholder="(inherit from main)",
                        id=f"sa-{sa_name}",
                        classes="subagent-input",
                    )

            # Generation params
            yield Static("Temperature:", classes="field-label")
            yield Input(
                value=str(self._config.temperature),
                placeholder="0.2",
                id="temperature",
            )

            yield Static("Max Tokens:", classes="field-label")
            yield Input(
                value=str(self._config.max_tokens),
                placeholder="16384",
                id="max-tokens",
            )

            yield Static("Context Window:", classes="field-label")
            yield Input(
                value=str(self._config.context_window),
                placeholder="131072",
                id="context-window",
            )

            yield Static("Thinking Budget:", classes="field-label")
            yield Input(
                value=str(self._config.thinking_budget or ""),
                placeholder="e.g. 10000 (blank to disable)",
                id="thinking-budget",
            )

            # Buttons
            with Horizontal(id="btn-row"):
                yield Button("Save", id="btn-save", variant="primary")
                yield Button("Cancel", id="btn-cancel", variant="default")

    def on_mount(self) -> None:
        """Initialize the wizard with current config values."""
        # Pre-populate model list if model is already set
        if self._config.model:
            option_list = self.query_one("#model-list", OptionList)
            option_list.add_option(Option(self._config.model, id=self._config.model))

    # -----------------------------------------------------------------
    # Event handlers
    # -----------------------------------------------------------------

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button clicks."""
        if event.button.id == "btn-fetch":
            self._fetch_models()
        elif event.button.id == "btn-save":
            self._save_config()
        elif event.button.id == "btn-cancel":
            self.dismiss(None)

    def on_select_changed(self, event: Select.Changed) -> None:
        """Update default URL when backend changes."""
        if event.select.id == "backend-select":
            backend = str(event.value)
            url_input = self.query_one("#base-url", Input)
            # Suggest a default URL if the current URL is empty or a known default
            current = url_input.value.strip()
            known_defaults = {
                "",
                "http://localhost:8000/v1",
                "http://localhost:11434",
            }
            if current in known_defaults:
                if backend == "ollama":
                    url_input.value = "http://localhost:11434"
                elif backend == "anthropic":
                    url_input.value = ""  # SDK defaults to api.anthropic.com
                else:
                    url_input.value = "http://localhost:8000/v1"

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """When a model is selected from the fetched list, put it in the input."""
        if event.option_list.id == "model-list" and event.option_id:
            model_input = self.query_one("#model-input", Input)
            model_input.value = str(event.option_id)

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        """When checked, populate all subagent inputs with the main model."""
        if event.checkbox.id == "same-model-check" and event.value:
            main_model = self.query_one("#model-input", Input).value.strip()
            for sa_name in self._subagent_names:
                try:
                    sa_input = self.query_one(f"#sa-{sa_name}", Input)
                    sa_input.value = main_model
                except Exception:
                    pass

    def action_cancel(self) -> None:
        """Cancel and close the wizard."""
        self.dismiss(None)

    # -----------------------------------------------------------------
    # Fetch models
    # -----------------------------------------------------------------

    def _fetch_models(self) -> None:
        """Fetch available models from the configured backend."""
        status = self.query_one("#fetch-status", Static)
        status.update("Fetching...")

        backend_val = self.query_one("#backend-select", Select).value
        backend = str(backend_val) if backend_val is not Select.BLANK else "openai"
        base_url = self.query_one("#base-url", Input).value.strip()
        api_key = self.query_one("#api-key", Input).value.strip()

        if not base_url and backend not in ("anthropic",):
            status.update("[red]Set API URL first[/red]")
            return

        try:
            models = self._list_models(backend, base_url, api_key)
            self._fetched_models = sorted(models)

            option_list = self.query_one("#model-list", OptionList)
            option_list.clear_options()

            if not models:
                status.update("[yellow]No models found[/yellow]")
                return

            for m in self._fetched_models:
                option_list.add_option(Option(m, id=m))

            # Update main model input with suggester
            model_input = self.query_one("#model-input", Input)
            model_input.suggester = SuggestFromList(self._fetched_models, case_sensitive=False)

            # Update subagent inputs with suggester
            for sa_name in self._subagent_names:
                try:
                    sa_input = self.query_one(f"#sa-{sa_name}", Input)
                    sa_input.suggester = SuggestFromList(self._fetched_models, case_sensitive=False)
                except Exception:
                    pass

            status.update(f"[green]{len(models)} model(s) found[/green]")

        except Exception as e:
            logger.warning(f"Failed to fetch models: {e}")
            status.update(f"[red]Error: {e}[/red]")

    @staticmethod
    def _list_models(backend: str, base_url: str, api_key: str) -> list[str]:
        """
        list models from the backend.

        Reuses existing backend classes for the actual API call.

        Args:
            backend: Backend type ("openai", "anthropic", or "ollama")
            base_url: API endpoint URL
            api_key: Actual API key (not an env var name)
        """
        from src.llm.base import LLMBackendType, LLMConfig

        if backend == "ollama":
            from src.llm.ollama_backend import OllamaBackend

            config = LLMConfig(
                backend_type=LLMBackendType.OLLAMA,
                model_name="temp",
                base_url=base_url,
                temperature=0.2,
                max_tokens=1024,
                top_p=0.95,
                context_window=4096,
            )
            ollama = OllamaBackend(config)
            return ollama.list_models()
        elif backend == "anthropic":
            from src.llm.anthropic_backend import KNOWN_CLAUDE_MODELS

            return list(KNOWN_CLAUDE_MODELS)
        else:
            from src.llm.openai_backend import OpenAIBackend

            config = LLMConfig(
                backend_type=LLMBackendType.OPENAI,
                model_name="temp",
                base_url=base_url,
                temperature=0.2,
                max_tokens=1024,
                top_p=0.95,
                context_window=4096,
            )
            openai_backend = OpenAIBackend(config, api_key=api_key)
            return openai_backend.list_models()

    # -----------------------------------------------------------------
    # Save
    # -----------------------------------------------------------------

    def _save_config(self) -> None:
        """Collect values from widgets and save to config.yaml."""
        backend_val = self.query_one("#backend-select", Select).value
        backend = str(backend_val) if backend_val is not Select.BLANK else "openai"

        base_url = self.query_one("#base-url", Input).value.strip()
        api_key = self.query_one("#api-key", Input).value.strip()
        model = self.query_one("#model-input", Input).value.strip()

        # Generation params
        try:
            temperature = float(self.query_one("#temperature", Input).value.strip())
        except (ValueError, TypeError):
            temperature = 0.2

        try:
            max_tokens = int(self.query_one("#max-tokens", Input).value.strip())
        except (ValueError, TypeError):
            max_tokens = 16384

        try:
            context_window = int(self.query_one("#context-window", Input).value.strip())
        except (ValueError, TypeError):
            context_window = 131072

        thinking_budget = None
        try:
            tb_val = self.query_one("#thinking-budget", Input).value.strip()
            if tb_val:
                thinking_budget = int(tb_val)
        except (ValueError, TypeError):
            thinking_budget = None

        # Subagent overrides (always read from inputs)
        subagents: dict[str, SubAgentLLMOverride] = {}
        for sa_name in self._subagent_names:
            try:
                sa_input = self.query_one(f"#sa-{sa_name}", Input)
                sa_model = sa_input.value.strip()
                if sa_model:
                    subagents[sa_name] = SubAgentLLMOverride(model=sa_model)
            except Exception:
                pass

        config = LLMConfigData(
            backend_type=backend,
            base_url=base_url,
            api_key=api_key,  # Runtime only -- not persisted to YAML
            api_key_env=self._config.api_key_env,  # Preserve existing env var fallback
            model=model,
            context_window=context_window,
            temperature=temperature,
            max_tokens=max_tokens,
            top_p=self._config.top_p,  # Keep existing top_p
            thinking_budget=thinking_budget,
            subagents=subagents,
        )

        # Save API key to OS credential store (not config.yaml)
        if api_key:
            from src.llm.credential_store import save_api_key

            if not save_api_key(api_key):
                logger.warning("Failed to save API key to credential store")

        success = save_llm_config(config, self._config_path)
        if success:
            logger.info(f"LLM config saved to {self._config_path}")
            self.dismiss(config)
        else:
            self.app.notify(
                "Failed to save LLM configuration",
                severity="error",
            )
