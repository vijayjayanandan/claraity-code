"""
Autonomous Scenario Runner

Executes test scenarios where a Testing LLM autonomously interacts
with the Coding Agent, with real-time terminal visualization.
"""

import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.panel import Panel
from rich.columns import Columns
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table
from rich.layout import Layout
from rich.live import Live
from rich import box

from .scenario import AutonomousScenario, ScenarioResult, TurnResult
from .testing_agent import TestingAgent
from .agent_orchestrator import AgentOrchestrator
from src.platform.windows import safe_print


class AutonomousScenarioRunner:
    """
    Runs autonomous test scenarios with real-time visualization.

    This orchestrates the conversation between Testing Agent (simulated user)
    and Coding Agent (system under test), displaying everything in a beautiful
    terminal UI.
    """

    def __init__(
        self,
        orchestrator: AgentOrchestrator,
        verbose: bool = True,
        save_results: bool = True
    ):
        """
        Initialize Scenario Runner.

        Args:
            orchestrator: AgentOrchestrator for managing coding agent sessions
            verbose: Show detailed real-time output
            save_results: Save results to JSON files
        """
        self.orchestrator = orchestrator
        self.verbose = verbose
        self.save_results = save_results
        self.console = Console()

    def _safe_print(self, *args, **kwargs):
        """Safely print to console, ignoring Windows encoding errors"""
        try:
            self.console.print(*args, **kwargs)
        except (ValueError, OSError):
            # Windows encoding issue - silently continue
            pass

    def run_scenario(self, scenario: AutonomousScenario) -> ScenarioResult:
        """
        Execute an autonomous test scenario.

        Args:
            scenario: Scenario to execute

        Returns:
            ScenarioResult with complete test results
        """
        start_time = datetime.now()

        # Display scenario header
        self._display_scenario_header(scenario)

        # Initialize Testing Agent (AI Test Engineer)
        testing_agent = TestingAgent(scenario)
        self._safe_print(f"[green][OK][/green] Testing Agent initialized (model: {testing_agent.model_name})")

        # Start conversation session with Coding Agent
        session = self.orchestrator.start_conversation(
            task_description=scenario.name
        )
        self._safe_print(f"[green][OK][/green] Coding Agent session started (workspace: {session.working_directory})")
        self._safe_print()

        # Multi-turn conversation loop
        turn_results = []
        turn = 0
        coding_agent_response = None
        files_generated_all = []
        tools_called_all = []

        # Generate first message from Testing Agent
        self._safe_print("[cyan][TESTING AGENT][/cyan] Generating first message...")
        first_decision = testing_agent.generate_first_message()

        while turn < scenario.max_turns:
            turn += 1

            # Determine user message
            if turn == 1:
                user_message = first_decision["user_message"]
                assessment = first_decision["assessment"]
                should_continue = first_decision["continue"]
                reasoning = first_decision["reasoning"]
            else:
                # Testing Agent generates next message based on Coding Agent's response
                self._safe_print(f"\n[cyan][TESTING AGENT][/cyan] Analyzing response...")
                decision = testing_agent.generate_next_message(
                    coding_agent_response=coding_agent_response,
                    files_generated=files_generated,
                    tools_called=tools_called,
                    turn_number=turn
                )

                user_message = decision["user_message"]
                assessment = decision["assessment"]
                should_continue = decision["continue"]
                reasoning = decision["reasoning"]

            # Display turn header
            self._display_turn_header(turn, scenario.max_turns)

            # Display Testing Agent's message and assessment
            self._display_testing_agent_message(user_message, assessment, should_continue, reasoning)

            # Check if Testing Agent wants to stop
            if not should_continue:
                self._safe_print("\n[yellow][INFO][/yellow] Testing Agent decided to end conversation")
                break

            # Send message to Coding Agent
            self._safe_print("\n[green][CODING AGENT][/green] Processing...")
            start_time_turn = time.time()

            response = session.send_message(user_message)

            elapsed = time.time() - start_time_turn

            coding_agent_response = response.content
            files_generated = response.files_generated
            tools_called = [tool.get('tool', 'unknown') for tool in response.tool_calls]

            # Track all files and tools
            files_generated_all.extend(files_generated)
            tools_called_all.extend(tools_called)

            # Display Coding Agent's response
            self._display_coding_agent_response(
                response.content,
                files_generated,
                tools_called,
                elapsed
            )

            # Record turn result
            turn_result = TurnResult(
                turn_number=turn,
                user_message=user_message,
                agent_response=coding_agent_response,
                files_generated=files_generated,
                tools_called=tools_called,
                assessment=assessment,
                should_continue=should_continue
            )
            turn_results.append(turn_result)

        # End conversation and get log
        self._safe_print(f"\n[cyan][INFO][/cyan] Conversation ended after {turn} turns")
        conversation_log = self.orchestrator.end_conversation(session.conversation_id)

        # Get workspace files
        workspace_files = [
            str(f.relative_to(session.working_directory))
            for f in session.working_directory.rglob("*")
            if f.is_file()
        ]

        # Testing Agent generates final verdict
        self._safe_print("\n[cyan][TESTING AGENT][/cyan] Generating final verdict...")
        verdict_result = testing_agent.generate_final_verdict(
            conversation_log=conversation_log,
            workspace_files=workspace_files,
            workspace_path=session.working_directory
        )

        # Display final verdict
        self._display_final_verdict(verdict_result)

        # Create scenario result
        end_time = datetime.now()
        result = ScenarioResult(
            scenario_id=scenario.scenario_id,
            scenario_name=scenario.name,
            passed=verdict_result["passed"],
            turn_results=turn_results,
            final_verdict=verdict_result["reasoning"],
            final_checks=verdict_result["validation_checks"],
            conversation_log_path=str(session.log_file) if session.log_file else None,
            workspace_path=str(session.working_directory),
            started_at=start_time,
            ended_at=end_time,
            total_turns=turn
        )

        # Save results if configured
        if self.save_results:
            result_path = self.orchestrator.output_dir / f"scenario_result_{scenario.scenario_id}_{start_time.strftime('%Y%m%d_%H%M%S')}.json"
            saved_path = result.save(str(result_path))
            self._safe_print(f"\n[green][OK][/green] Results saved to: {saved_path}")

        return result

    def _display_scenario_header(self, scenario: AutonomousScenario):
        """Display scenario information"""
        self._safe_print()
        self._safe_print("[bold cyan]AI TEST ENGINEER - Autonomous Scenario Execution[/bold cyan]")
        self._safe_print()

        info_table = Table(show_header=False, box=box.SIMPLE)
        info_table.add_column("Field", style="cyan")
        info_table.add_column("Value", style="white")

        info_table.add_row("Scenario ID", scenario.scenario_id)
        info_table.add_row("Name", scenario.name)
        info_table.add_row("Description", scenario.description)
        info_table.add_row("Max Turns", str(scenario.max_turns))
        info_table.add_row("Success Criteria", str(len(scenario.success_criteria)))

        self._safe_print(Panel(info_table, title="[bold]Scenario Configuration[/bold]", border_style="cyan"))
        self._safe_print()

    def _display_turn_header(self, turn: int, max_turns: int):
        """Display turn separator"""
        self._safe_print()
        self._safe_print(f"[bold yellow]Turn {turn}/{max_turns}[/bold yellow]")
        self._safe_print()

    def _display_testing_agent_message(
        self,
        message: str,
        assessment: str,
        should_continue: bool,
        reasoning: str
    ):
        """Display Testing Agent's message and assessment"""
        # User message
        user_panel = Panel(
            message,
            title="[bold cyan]USER MESSAGE[/bold cyan]",
            border_style="cyan",
            padding=(1, 2)
        )
        self._safe_print(user_panel)

        # Assessment
        if assessment and assessment != "[Could not parse assessment]":
            assessment_panel = Panel(
                f"[bold]Assessment:[/bold] {assessment}\n"
                f"[bold]Continue:[/bold] {'Yes' if should_continue else 'No'}\n"
                f"[bold]Reasoning:[/bold] {reasoning}",
                title="[bold yellow]TESTING AGENT ASSESSMENT[/bold yellow]",
                border_style="yellow",
                padding=(1, 2)
            )
            self._safe_print(assessment_panel)

    def _display_coding_agent_response(
        self,
        response: str,
        files_generated: list,
        tools_called: list,
        elapsed: float
    ):
        """Display Coding Agent's response"""
        try:
            # Response text (truncate if too long)
            display_response = response
            if len(response) > 500:
                display_response = response[:500] + "\n\n[... truncated ...]"

            response_panel = Panel(
                display_response,
                title=f"[bold green]CODING AGENT RESPONSE[/bold green] (took {elapsed:.1f}s)",
                border_style="green",
                padding=(1, 2)
            )
            self._safe_print(response_panel)

            # Files and tools
            if files_generated or tools_called:
                metadata = ""
                if files_generated:
                    metadata += f"[bold]Files Created:[/bold] {', '.join(files_generated)}\n"
                if tools_called:
                    metadata += f"[bold]Tools Called:[/bold] {', '.join(tools_called)}"

                meta_panel = Panel(
                    metadata,
                    title="[bold magenta]ACTIONS TAKEN[/bold magenta]",
                    border_style="magenta",
                    padding=(0, 2)
                )
                self._safe_print(meta_panel)
        except (ValueError, OSError) as e:
            # Windows encoding issue - console is closed
            # Silently continue (test logic still works, just display fails)
            pass

    def _display_final_verdict(self, verdict_result: dict):
        """Display final verdict from Testing Agent"""
        self._safe_print()
        self._safe_print("[bold magenta]FINAL VERDICT[/bold magenta]")
        self._safe_print()

        # Verdict summary
        verdict = verdict_result["verdict"]
        verdict_color = "green" if verdict == "PASS" else "red"
        verdict_symbol = "[OK]" if verdict == "PASS" else "[FAIL]"

        self._safe_print(f"[{verdict_color}]{verdict_symbol} {verdict}[/{verdict_color}]")
        self._safe_print()

        # Validation checks table
        checks_table = Table(title="Validation Checks", box=box.ROUNDED)
        checks_table.add_column("#", justify="right", style="cyan")
        checks_table.add_column("Criterion", style="white")
        checks_table.add_column("Result", justify="center")
        checks_table.add_column("Evidence", style="dim")

        for i, check in enumerate(verdict_result["validation_checks"], 1):
            result_symbol = "[green]:heavy_check_mark:[/green]" if check.passed else "[red]:x:[/red]"
            checks_table.add_row(
                str(i),
                check.expectation,
                result_symbol,
                check.evidence[:100] + "..." if len(check.evidence) > 100 else check.evidence
            )

        self._safe_print(checks_table)
        self._safe_print()

        # Reasoning
        reasoning_panel = Panel(
            verdict_result["reasoning"],
            title="[bold]Reasoning[/bold]",
            border_style="yellow",
            padding=(1, 2)
        )
        self._safe_print(reasoning_panel)
        self._safe_print()
