"""
Testing Agent - Autonomous LLM that acts as a realistic user.

This is the "AI Test Engineer" that interacts with the Coding Agent
to validate its behavior through natural, adaptive conversations.
"""

import os
import re
from pathlib import Path
from typing import Any, Optional

from src.llm.base import LLMBackendType, LLMConfig
from src.llm.openai_backend import OpenAIBackend

from .models import ConversationLog
from .scenario import AutonomousScenario, ScenarioResult, ValidationCheck


class TestingAgent:
    """
    Autonomous LLM that acts as a realistic user testing the Coding Agent.

    The Testing Agent:
    - Generates realistic user messages (starting vague, clarifying gradually)
    - Adapts conversation based on Coding Agent's responses
    - Assesses Coding Agent's behavior at each turn
    - Decides when to continue or end the conversation
    - Provides final verdict with evidence

    Think of this as hiring a QA engineer who knows how to test conversational AI.
    """

    def __init__(
        self,
        scenario: AutonomousScenario,
        model_name: str | None = None,
        backend: str | None = None,
        base_url: str | None = None,
        api_key: str | None = None
    ):
        """
        Initialize Testing Agent.

        Args:
            scenario: Test scenario defining the testing objectives
            model_name: LLM model to use (defaults to env LLM_MODEL)
            backend: Backend type (defaults to env LLM_BACKEND)
            base_url: API base URL (defaults to env LLM_HOST)
            api_key: API key (defaults to env OPENAI_API_KEY)
        """
        self.scenario = scenario
        self.conversation_history: list[dict[str, str]] = []

        # Initialize LLM backend (using OpenAI-compatible backend)
        self.model_name = model_name or os.getenv("LLM_MODEL")
        self.base_url = base_url or os.getenv("LLM_HOST")
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")

        if not all([self.model_name, self.base_url, self.api_key]):
            raise ValueError(
                "Missing LLM configuration. Set LLM_MODEL, LLM_HOST, OPENAI_API_KEY in .env"
            )

        # Create LLM config
        llm_config = LLMConfig(
            backend_type=LLMBackendType.OPENAI,
            model_name=self.model_name,
            base_url=self.base_url,
            context_window=int(os.getenv("LLM_CONTEXT_WINDOW", "32768")),
            temperature=float(os.getenv("LLM_TEMPERATURE", "0.2")),
            max_tokens=int(os.getenv("LLM_MAX_TOKENS", "16384")),
            top_p=float(os.getenv("LLM_TOP_P", "0.95"))
        )

        # Initialize OpenAI backend
        self.llm = OpenAIBackend(
            llm_config,
            api_key=self.api_key
        )

        # Build system prompt for Testing Agent
        self.system_prompt = self._build_system_prompt()

    def _build_system_prompt(self) -> str:
        """Build comprehensive system prompt for Testing Agent"""
        return f"""You are an AI TEST ENGINEER evaluating a coding agent's behavior.

SCENARIO: {self.scenario.name}
{self.scenario.description}

YOUR ROLE AS TESTING AGENT:
{self.scenario.testing_agent_prompt}

SUCCESS CRITERIA (you will validate these at the end):
{chr(10).join(f"{i+1}. {criterion}" for i, criterion in enumerate(self.scenario.success_criteria))}

INSTRUCTIONS:
1. Generate realistic user messages that test the coding agent
2. Start VAGUE/UNCLEAR (like real users do), then clarify gradually
3. Adapt your messages based on the coding agent's responses
4. After each response, assess whether the coding agent is behaving correctly
5. Decide whether to continue the conversation or stop

RESPONSE FORMAT (CRITICAL - use this exact structure):
---
USER_MESSAGE: <your next message to the coding agent>
ASSESSMENT: <your evaluation of the coding agent's last response>
CONTINUE: <yes or no - whether to continue conversation>
REASONING: <why you made this decision>
---

IMPORTANT RULES:
- Be realistic - don't be overly technical at first
- Adapt based on what the coding agent says
- If the coding agent asks a question, answer it
- If the coding agent creates files, you can ask to see them or make changes
- Stop when the task is complete OR after {self.scenario.max_turns} turns
- Your goal is to VALIDATE the coding agent, not to make its job harder
"""

    def generate_first_message(self) -> dict[str, Any]:
        """
        Generate the first user message to start the conversation.

        Returns:
            Dictionary with:
                - user_message: Initial message to send
                - assessment: Initial assessment (none yet)
                - continue: Whether to continue (always True for first message)
                - reasoning: Why this message was chosen
        """
        prompt = """Generate your FIRST message to the coding agent.

Remember:
- Start VAGUE (don't be too specific immediately)
- Act like a real user who doesn't know all the technical details
- This is your opening message - make it realistic

Provide your response in the required format."""

        response = self.llm.generate(
            messages=[
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": prompt}
            ]
        ).content

        # Add to conversation history
        self.conversation_history.append({
            "role": "user",
            "content": prompt
        })
        self.conversation_history.append({
            "role": "assistant",
            "content": response
        })

        return self._parse_response(response)

    def generate_next_message(
        self,
        coding_agent_response: str,
        files_generated: list[str],
        tools_called: list[str],
        turn_number: int
    ) -> dict[str, Any]:
        """
        Generate next user message based on coding agent's response.

        Args:
            coding_agent_response: What the coding agent said
            files_generated: Files the coding agent created
            tools_called: Tools the coding agent used
            turn_number: Current turn number

        Returns:
            Dictionary with:
                - user_message: Next message to send
                - assessment: Assessment of coding agent's response
                - continue: Whether to continue conversation
                - reasoning: Why this decision was made
        """
        # Build context about coding agent's response
        context = f"""CODING AGENT'S RESPONSE:
{coding_agent_response}

FILES GENERATED: {files_generated if files_generated else "None"}
TOOLS CALLED: {tools_called if tools_called else "None"}
TURN NUMBER: {turn_number}/{self.scenario.max_turns}

Based on the coding agent's response, generate your next message.

Remember:
- Adapt to what the coding agent said
- If they asked questions, answer them
- If they created files, you can ask to see them or request changes
- Be realistic - act like a real user
- Decide if you should continue or stop (stop if task is complete OR max turns reached)

Provide your response in the required format."""

        response = self.llm.generate(
            messages=[
                {"role": "system", "content": self.system_prompt},
                *self.conversation_history,
                {"role": "user", "content": context}
            ]
        ).content

        # Add to conversation history
        self.conversation_history.append({
            "role": "user",
            "content": context
        })
        self.conversation_history.append({
            "role": "assistant",
            "content": response
        })

        return self._parse_response(response)

    def generate_final_verdict(
        self,
        conversation_log: ConversationLog,
        workspace_files: list[str],
        workspace_path: Path
    ) -> dict[str, Any]:
        """
        Generate final verdict after conversation ends.

        Args:
            conversation_log: Complete conversation history
            workspace_files: Files created in workspace
            workspace_path: Path to workspace directory

        Returns:
            Dictionary with:
                - verdict: PASS or FAIL
                - reasoning: Explanation of verdict
                - evidence: list of evidence points
                - validation_checks: list of ValidationCheck objects
        """
        # Build conversation summary
        conversation_summary = "\n\n".join([
            f"[{msg.role.upper()}] {msg.content[:500]}{'...' if len(msg.content) > 500 else ''}"
            for msg in conversation_log.messages
        ])

        # Read file contents for validation
        file_contents = {}
        for file_path in workspace_files:
            try:
                full_path = workspace_path / file_path
                if full_path.exists() and full_path.is_file():
                    # Read first 1000 chars of each file
                    content = full_path.read_text(encoding='utf-8')[:1000]
                    file_contents[file_path] = content
            except Exception:
                file_contents[file_path] = "[Could not read file]"

        verdict_prompt = f"""CONVERSATION SUMMARY:
{conversation_summary}

FILES CREATED:
{chr(10).join(f"- {f}" for f in workspace_files) if workspace_files else "No files created"}

FILE CONTENTS (first 1000 chars):
{chr(10).join(f"=== {f} ==={chr(10)}{content[:500]}{chr(10)}" for f, content in file_contents.items())}

Based on the success criteria, provide your FINAL VERDICT:

SUCCESS CRITERIA TO VALIDATE:
{chr(10).join(f"{i+1}. {criterion}" for i, criterion in enumerate(self.scenario.success_criteria))}

For EACH criterion:
1. State whether it PASSED or FAILED
2. Provide specific EVIDENCE from the conversation or files

Then provide OVERALL VERDICT: PASS or FAIL

FORMAT YOUR RESPONSE AS:
---
CRITERION 1: <PASS/FAIL>
EVIDENCE: <specific evidence>

CRITERION 2: <PASS/FAIL>
EVIDENCE: <specific evidence>

[... for each criterion ...]

OVERALL VERDICT: <PASS/FAIL>
REASONING: <why you made this decision>
---
"""

        response = self.llm.generate(
            messages=[
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": verdict_prompt}
            ]
        ).content

        return self._parse_verdict(response)

    def _parse_response(self, response: str) -> dict[str, Any]:
        """
        Parse Testing Agent's response into structured format.

        Expected format:
            USER_MESSAGE: <message>
            ASSESSMENT: <assessment>
            CONTINUE: <yes/no>
            REASONING: <reasoning>
        """
        result = {
            "user_message": "",
            "assessment": "",
            "continue": True,
            "reasoning": ""
        }

        # Extract USER_MESSAGE
        user_msg_match = re.search(r'USER_MESSAGE:\s*(.+?)(?=\nASSESSMENT:|$)', response, re.DOTALL)
        if user_msg_match:
            result["user_message"] = user_msg_match.group(1).strip()

        # Extract ASSESSMENT
        assessment_match = re.search(r'ASSESSMENT:\s*(.+?)(?=\nCONTINUE:|$)', response, re.DOTALL)
        if assessment_match:
            result["assessment"] = assessment_match.group(1).strip()

        # Extract CONTINUE
        continue_match = re.search(r'CONTINUE:\s*(yes|no)', response, re.IGNORECASE)
        if continue_match:
            result["continue"] = continue_match.group(1).lower() == "yes"

        # Extract REASONING
        reasoning_match = re.search(r'REASONING:\s*(.+?)(?=\n---|$)', response, re.DOTALL)
        if reasoning_match:
            result["reasoning"] = reasoning_match.group(1).strip()

        # Fallback: if parsing failed, use entire response as user message
        if not result["user_message"]:
            result["user_message"] = response.strip()
            result["assessment"] = "[Could not parse assessment]"
            result["reasoning"] = "[Could not parse reasoning]"

        return result

    def _parse_verdict(self, response: str) -> dict[str, Any]:
        """
        Parse final verdict response.

        Returns:
            Dictionary with:
                - verdict: "PASS" or "FAIL"
                - reasoning: Explanation
                - evidence: list of evidence points
                - validation_checks: list of ValidationCheck objects
        """
        validation_checks: list[ValidationCheck] = []

        # Extract validation checks for each criterion
        for i, criterion in enumerate(self.scenario.success_criteria):
            criterion_num = i + 1

            # Look for CRITERION N: PASS/FAIL
            pattern = rf'CRITERION {criterion_num}:\s*(PASS|FAIL)'
            match = re.search(pattern, response, re.IGNORECASE)

            if match:
                passed = match.group(1).upper() == "PASS"

                # Extract evidence for this criterion
                evidence_pattern = rf'CRITERION {criterion_num}:.*?EVIDENCE:\s*(.+?)(?=\nCRITERION|OVERALL|$)'
                evidence_match = re.search(evidence_pattern, response, re.DOTALL | re.IGNORECASE)
                evidence = evidence_match.group(1).strip() if evidence_match else "No evidence provided"

                validation_checks.append(ValidationCheck(
                    expectation=criterion,
                    passed=passed,
                    evidence=evidence
                ))
            else:
                # Criterion not found in response - mark as failed
                validation_checks.append(ValidationCheck(
                    expectation=criterion,
                    passed=False,
                    evidence="Testing Agent did not evaluate this criterion"
                ))

        # Extract overall verdict
        verdict_match = re.search(r'OVERALL VERDICT:\s*(PASS|FAIL)', response, re.IGNORECASE)
        verdict = verdict_match.group(1).upper() if verdict_match else "FAIL"

        # Extract reasoning
        reasoning_match = re.search(r'REASONING:\s*(.+?)(?=\n---|$)', response, re.DOTALL)
        reasoning = reasoning_match.group(1).strip() if reasoning_match else response

        # Overall pass = all criteria passed
        overall_passed = all(check.passed for check in validation_checks)

        # Override if LLM said PASS but not all checks passed
        if verdict == "PASS" and not overall_passed:
            reasoning += "\n[NOTE: Overridden to FAIL because not all criteria passed]"
            verdict = "FAIL"

        return {
            "verdict": verdict,
            "reasoning": reasoning,
            "validation_checks": validation_checks,
            "passed": overall_passed
        }
