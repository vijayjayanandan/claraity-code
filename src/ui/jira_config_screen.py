"""Jira Configuration Screen.

A modal screen that allows users to configure Jira connection profiles.
Each profile has a name, Jira URL, username, and API token (stored securely).

Triggered via:
- Command palette: Ctrl+P -> "Configure Jira"
- Slash command: /config-jira

Follows the ConfigLLMScreen pattern (ModalScreen with dismiss).
"""

from pathlib import Path

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Select, Static

from src.integrations.jira.connection import DEFAULT_CONFIG_DIR, JiraConnection
from src.observability import get_logger

logger = get_logger("ui.jira_config_screen")


class JiraConfigResult:
    """Result returned when the Jira config screen is acted upon."""

    def __init__(
        self,
        profile: str,
        jira_url: str = "",
        username: str = "",
        api_token: str = "",
        disconnect: bool = False,
    ):
        self.profile = profile
        self.jira_url = jira_url
        self.username = username
        self.api_token = api_token
        self.disconnect = disconnect


class ConfigJiraScreen(ModalScreen[JiraConfigResult | None]):
    """Modal screen for configuring a Jira connection profile.

    Fields:
    - Profile name (e.g. "personal", "corporate")
    - Jira URL (e.g. "https://mycompany.atlassian.net")
    - Username (Atlassian email)
    - API Token (masked, stored in SecretStore)

    Returns:
        JiraConfigResult on save, None on cancel.
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
    ]

    DEFAULT_CSS = """
    ConfigJiraScreen {
        align: center middle;
    }

    ConfigJiraScreen > Vertical {
        width: 90%;
        max-width: 80;
        height: auto;
        max-height: 80%;
        background: $surface;
        border: thick $primary;
        padding: 1 2;
        overflow-y: auto;
    }

    ConfigJiraScreen #title {
        text-align: center;
        text-style: bold;
        color: $text;
        padding-bottom: 1;
    }

    ConfigJiraScreen .field-label {
        margin-top: 1;
        color: $text-muted;
    }

    ConfigJiraScreen Input {
        margin-bottom: 0;
    }

    ConfigJiraScreen Select {
        margin-bottom: 0;
    }

    ConfigJiraScreen #btn-row {
        margin-top: 2;
        height: auto;
        align: center middle;
    }

    ConfigJiraScreen #btn-row Button {
        margin: 0 1;
    }

    ConfigJiraScreen #status-msg {
        margin-top: 1;
        color: $text-muted;
        text-align: center;
    }

    ConfigJiraScreen .help-text {
        color: $text-muted;
        margin-top: 0;
    }

    ConfigJiraScreen #connection-status {
        margin-top: 1;
        text-align: center;
    }

    ConfigJiraScreen #btn-disconnect {
        margin: 0 1;
    }
    """

    def __init__(
        self,
        profile: str | None = None,
        connected_profile: str | None = None,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ):
        super().__init__(name=name, id=id, classes=classes)
        self._initial_profile = profile or connected_profile
        self._connected_profile = connected_profile
        self._profiles = JiraConnection.list_profiles()

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static("Configure Jira", id="title")

            # Profile selector (existing profiles + new)
            yield Static("Profile:", classes="field-label")
            profile_choices = [(p, p) for p in self._profiles]
            profile_choices.append(("+ New profile", "__new__"))

            initial_value = self._initial_profile or (
                self._profiles[0] if self._profiles else "__new__"
            )
            yield Select(
                profile_choices,
                value=initial_value,
                id="profile-select",
                allow_blank=False,
            )

            # New profile name (shown when "+ New profile" selected)
            yield Static("New profile name:", classes="field-label", id="new-profile-label")
            yield Input(
                value="",
                placeholder="e.g. corporate, personal",
                id="new-profile-name",
            )

            # Jira URL
            yield Static("Jira URL:", classes="field-label")
            yield Input(
                value="",
                placeholder="https://mycompany.atlassian.net",
                id="jira-url",
            )

            # Username
            yield Static("Username (email):", classes="field-label")
            yield Input(
                value="",
                placeholder="user@mycompany.com",
                id="jira-username",
            )

            # API Token (masked)
            yield Static("API Token:", classes="field-label")
            yield Input(
                value="",
                placeholder="Paste API token from id.atlassian.com",
                password=True,
                id="jira-api-token",
            )
            yield Static(
                "Get token: https://id.atlassian.com/manage-profile/security/api-tokens",
                classes="help-text",
            )

            # Connection status
            yield Static("", id="connection-status")

            # Status message
            yield Static("", id="status-msg")

            # Buttons
            with Horizontal(id="btn-row"):
                yield Button("Save & Connect", id="btn-save", variant="primary")
                yield Button("Save", id="btn-save-only", variant="default")
                yield Button("Disconnect", id="btn-disconnect", variant="warning")
                yield Button("Cancel", id="btn-cancel", variant="default")

    def on_mount(self) -> None:
        """Load existing profile data if a profile is selected."""
        self._load_profile_data()
        self._toggle_new_profile_field()
        self._update_connection_status()

    def on_select_changed(self, event: Select.Changed) -> None:
        """When profile selection changes, load that profile's data."""
        if event.select.id == "profile-select":
            self._toggle_new_profile_field()
            self._load_profile_data()
            self._update_connection_status()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-save":
            self._save_config(connect_after=True)
        elif event.button.id == "btn-save-only":
            self._save_config(connect_after=False)
        elif event.button.id == "btn-disconnect":
            self._disconnect_profile()
        elif event.button.id == "btn-cancel":
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)

    def _toggle_new_profile_field(self) -> None:
        """Show/hide the new profile name input."""
        select = self.query_one("#profile-select", Select)
        is_new = select.value == "__new__"
        try:
            label = self.query_one("#new-profile-label", Static)
            name_input = self.query_one("#new-profile-name", Input)
            label.display = is_new
            name_input.display = is_new
            if is_new:
                name_input.focus()
        except Exception:
            pass

    def _update_connection_status(self) -> None:
        """Show/hide disconnect button based on connection state."""
        select = self.query_one("#profile-select", Select)
        profile_name = select.value
        is_connected = (
            self._connected_profile is not None
            and profile_name == self._connected_profile
        )
        try:
            status_label = self.query_one("#connection-status", Static)
            disconnect_btn = self.query_one("#btn-disconnect", Button)
            if is_connected:
                status_label.update(
                    f"[green]Connected[/green] to {self._connected_profile}"
                )
                disconnect_btn.display = True
            else:
                status_label.update("")
                disconnect_btn.display = False
        except Exception:
            pass

    def _disconnect_profile(self) -> None:
        """Signal the app to disconnect the current profile."""
        if self._connected_profile:
            self.dismiss(JiraConfigResult(
                profile=self._connected_profile,
                disconnect=True,
            ))

    def _load_profile_data(self) -> None:
        """Populate fields from the selected profile's config."""
        select = self.query_one("#profile-select", Select)
        profile_name = select.value

        if profile_name == "__new__" or profile_name is Select.BLANK:
            # Clear fields for new profile
            self.query_one("#jira-url", Input).value = ""
            self.query_one("#jira-username", Input).value = ""
            self.query_one("#jira-api-token", Input).value = ""
            return

        try:
            conn = JiraConnection(profile=str(profile_name))
            self.query_one("#jira-url", Input).value = conn.jira_url or ""
            self.query_one("#jira-username", Input).value = conn.username or ""
            # Show dots if token exists, empty if not
            if conn.has_api_token():
                self.query_one("#jira-api-token", Input).value = ""
                self.query_one("#jira-api-token", Input).placeholder = (
                    "Token stored securely (leave blank to keep)"
                )
            else:
                self.query_one("#jira-api-token", Input).value = ""
                self.query_one("#jira-api-token", Input).placeholder = (
                    "Paste API token from id.atlassian.com"
                )
        except Exception as e:
            logger.warning(f"Failed to load profile: {e}")

    def _save_config(self, connect_after: bool = False) -> None:
        """Validate and save the Jira profile configuration."""
        status = self.query_one("#status-msg", Static)

        # Resolve profile name
        select = self.query_one("#profile-select", Select)
        if select.value == "__new__":
            profile = self.query_one("#new-profile-name", Input).value.strip()
            if not profile:
                status.update("[red]Profile name is required[/red]")
                return
            # Sanitize: only allow alphanumeric, hyphens, underscores
            if not all(c.isalnum() or c in "-_" for c in profile):
                status.update("[red]Profile name: only letters, numbers, hyphens, underscores[/red]")
                return
        else:
            profile = str(select.value)

        jira_url = self.query_one("#jira-url", Input).value.strip()
        username = self.query_one("#jira-username", Input).value.strip()
        api_token = self.query_one("#jira-api-token", Input).value.strip()

        # Validate required fields
        if not jira_url:
            status.update("[red]Jira URL is required[/red]")
            return
        if not username:
            status.update("[red]Username is required[/red]")
            return

        # For existing profiles, token is optional (keep existing)
        existing_conn = JiraConnection(profile=profile)
        if not api_token and not existing_conn.has_api_token():
            status.update("[red]API token is required for new profiles[/red]")
            return

        try:
            if api_token:
                # Full configure with new token
                existing_conn.configure(
                    jira_url=jira_url,
                    username=username,
                    api_token=api_token,
                )
            else:
                # Update URL/username only, keep existing token
                existing_conn._jira_url = jira_url.rstrip("/")
                existing_conn._username = username
                existing_conn._enabled = True
                existing_conn._save_config()

            logger.info("jira_profile_saved", profile=profile)

            if connect_after:
                self.dismiss(JiraConfigResult(
                    profile=profile,
                    jira_url=jira_url,
                    username=username,
                    api_token=api_token,
                ))
            else:
                self.dismiss(None)
                self.app.notify(
                    f"Jira profile '{profile}' saved",
                    severity="information",
                )

        except Exception as e:
            status.update(f"[red]Save failed: {e}[/red]")
            logger.error(f"jira_config_save_failed: {e}")
