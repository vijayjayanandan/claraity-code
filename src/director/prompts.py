"""Director phase prompts and tool allowlists.

The script for each act of the movie -- tells the LLM what phase
it's in, what to focus on, and what tools are available.
"""

from typing import Optional

# Reuse the read-only tools set from plan_mode to avoid duplication
from src.core.plan_mode import READ_ONLY_TOOLS
from src.director.models import (
    ContextDocument,
    DirectorPhase,
    DirectorPlan,
)

# =============================================================================
# Phase Prompts -- system prompt injection per phase
# =============================================================================

PHASE_PROMPTS: dict[DirectorPhase, str] = {
    DirectorPhase.UNDERSTAND: """\
<director-mode phase="UNDERSTAND">
You are in UNDERSTAND mode. Your job is to explore the codebase and build
a complete picture of what exists before any code is written.

Do NOT write code. Do NOT modify any files. Only read and explore.

TOOLS AVAILABLE:
- read_file, search_code, glob, list_directory -- explore the codebase
- web_search, web_fetch -- research best practices, libraries, patterns
- `clarify` -- ask the user up to 4 structured clarifying questions
- `director_complete_understand` -- submit findings and advance to PLAN

WORKFLOW:
1. Explore the codebase (or note it is greenfield if empty)
2. If the task is ambiguous or key decisions are needed, use the `clarify`
   tool to ask the user 2-3 focused questions (tech stack, scope, priorities)
3. Once you have sufficient understanding, call `director_complete_understand`
   with your findings (affected files, existing patterns, constraints, risks)

IMPORTANT: You MUST eventually call `director_complete_understand` to advance.
Do not end your turn with only text output -- always finish with the tool call.
Keep your text responses brief. Save detailed findings for the tool call.
</director-mode>""",
    DirectorPhase.PLAN: """\
<director-mode phase="PLAN">
You are in PLAN mode. Your job is to design the implementation as a series
of vertical slices -- thin, independently testable increments.

Do NOT write application code. You may ONLY write plan documents.

TOOLS AVAILABLE:
- read_file, search_code, glob, list_directory -- explore if needed
- web_search, web_fetch -- research best practices, libraries, patterns
- `clarify` -- ask the user if a design decision needs their input
- `delegate_to_subagent` -- delegate planning to the 'planner' subagent
- `write_file` -- write your plan document to .claraity/plans/ ONLY
- `director_complete_plan` -- submit plan and advance to approval

WORKFLOW OPTIONS:

Option A: Delegate to Planner Subagent (RECOMMENDED for complex tasks)
1. Use `delegate_to_subagent` with subagent="planner" and provide:
   - The task description and context from UNDERSTAND phase
   - Specific questions or constraints to address
   - Request for a detailed implementation plan
2. Review the planner's output
3. Write the plan to .claraity/plans/director_plan.md using write_file
4. Call `director_complete_plan` with the plan details

Option B: Create Plan Directly (for simple, well-understood tasks)
1. Design your implementation plan with full detail:
   - Tech stack decisions with rationale and alternatives compared
   - Architecture approach with trade-offs explained
   - Vertical slices (3-5) with what each builds
   - Risk assessment and constraints
2. Write the COMPLETE plan as a markdown document using write_file:
   Path: .claraity/plans/director_plan.md
   Include: executive summary, decision rationale with comparison tables,
   slice details, test criteria, risks
3. Call `director_complete_plan` with:
   - plan_document: the file path you wrote
   - slices: list of slice titles (for execution tracking)
   - summary: brief one-line overview

RULES:
- Keep the plan to 3-5 slices maximum for the initial MVP
- If the scope is broad, pick the smallest useful starting point
- Each slice should be small enough to verify in one pass
- Put ALL detail in the markdown file, NOT in the tool call JSON
- The user reviews the markdown file, so make it thorough and readable

IMPORTANT: You MUST end this phase by calling `director_complete_plan`.
Do not end your turn with only text output.
</director-mode>""",
    DirectorPhase.AWAITING_APPROVAL: """\
<director-mode phase="AWAITING_APPROVAL">
Your plan has been submitted and is awaiting user approval.
Wait for the user to approve, reject with feedback, or cancel.
Do not proceed with any code changes until the plan is approved.
</director-mode>""",
    DirectorPhase.EXECUTE: """\
<director-mode phase="EXECUTE">
You are in EXECUTE mode. You are the DIRECTOR -- you orchestrate, you do
NOT write code yourself. Begin working on the current slice immediately.

For each slice, follow RED-GREEN-REFACTOR by DELEGATING to specialists:

1. RED -- Delegate to `test-writer` subagent:
   - Use `delegate_to_subagent` with subagent="test-writer"
   - In the task, specify: what behavior to test, which files to read for
     context, what patterns/frameworks the project uses
   - Review the returned test -- does it test the right behavior?
   - Run the test with `run_command` to confirm it FAILS (red means the
     test is valid but the feature is not yet implemented)

2. GREEN -- Delegate to `code-writer` subagent:
   - Use `delegate_to_subagent` with subagent="code-writer"
   - In the task, specify: the failing test file, what to implement, which
     existing files to read for patterns and conventions
   - Review the returned code -- is it minimal? Does it follow conventions?
   - Run ALL tests with `run_command` to confirm they PASS

3. REFACTOR (only if needed):
   - If the code is messy, delegate cleanup to `code-writer`
   - Run ALL tests again to confirm they still PASS

4. REVIEW -- Delegate to `code-reviewer` subagent:
   - Use `delegate_to_subagent` with subagent="code-reviewer"
   - In the task, specify: which files were created/modified, what the
     slice was supposed to accomplish
   - If the reviewer flags issues, delegate fixes to `code-writer`

After completing a slice:
- Verify ALL tests pass
- Call `director_complete_slice` with the slice ID and test results
- Then immediately proceed to the next slice

CONTEXT CURATION -- For every delegation, tell the subagent:
- Which specific files to read (not "the whole project")
- What patterns/conventions to follow (from your UNDERSTAND findings)
- What the acceptance criteria are (from the plan)

You may use `read_file`, `search_code`, `glob`, and `run_command` directly
to explore, verify, and run tests. But for writing or modifying code,
DELEGATE to a subagent.

IMPORTANT: Begin now. Delegate the first failing test for the current
slice to the test-writer subagent as your very next action.
</director-mode>""",
    DirectorPhase.INTEGRATE: """\
<director-mode phase="INTEGRATE">
You are in INTEGRATE mode. All slices are complete. Verify everything
works together before closing out.

WORKFLOW:
1. Run the FULL test suite with `run_command` (not just slice tests)
2. Review cross-slice coherence -- do the pieces fit together correctly?
3. If there are failures, fix them (delegate to code-writer if needed)
4. Once ALL tests pass, call `director_complete_integration` with:
   - test_results_summary: final test suite output
   - issues: any known limitations or follow-up items (empty if none)

IMPORTANT: You MUST call `director_complete_integration` to finish.
Do not end your turn with only text output.
</director-mode>""",
}


# =============================================================================
# Director Tool Names -- referenced by prompts and allowlists
# =============================================================================

DIRECTOR_TOOLS = frozenset(
    {
        "director_complete_understand",
        "director_complete_plan",
        "director_complete_slice",
        "director_complete_integration",
    }
)


# =============================================================================
# Phase Allowed Tools -- what the LLM can use in each phase
# =============================================================================

# UNDERSTAND and PLAN: read-only exploration + clarify + web research + checkpoint
_UNDERSTAND_TOOLS = READ_ONLY_TOOLS | frozenset(
    {
        "director_complete_understand",
        "clarify",
        "web_search",
        "web_fetch",
        "list_directory",
    }
)

_PLAN_TOOLS = READ_ONLY_TOOLS | frozenset(
    {
        "director_complete_plan",
        "clarify",
        "web_search",
        "web_fetch",
        "list_directory",
        "delegate_to_subagent",
        # NOTE: write_file is NOT in this set. The adapter handles it
        # with path-based gating (only .claraity/plans/ allowed).
    }
)

# EXECUTE: all tools (read + write + delegation + run + director)
_EXECUTE_TOOLS = READ_ONLY_TOOLS | frozenset(
    {
        "write_file",
        "edit_file",
        "append_to_file",
        "run_command",
        "git_status",
        "git_diff",
        "delegate_to_subagent",
        "director_complete_slice",
        "list_directory",
    }
)

# INTEGRATE: read-only + test execution + git (no file writes)
_INTEGRATE_TOOLS = (
    READ_ONLY_TOOLS
    | frozenset(
        {
            "run_command",
            "list_directory",
        }
    )
    | DIRECTOR_TOOLS
)

# AWAITING_APPROVAL: read-only only (waiting for user)
_AWAITING_APPROVAL_TOOLS = READ_ONLY_TOOLS


PHASE_ALLOWED_TOOLS: dict[DirectorPhase, frozenset] = {
    DirectorPhase.UNDERSTAND: _UNDERSTAND_TOOLS,
    DirectorPhase.PLAN: _PLAN_TOOLS,
    DirectorPhase.AWAITING_APPROVAL: _AWAITING_APPROVAL_TOOLS,
    DirectorPhase.EXECUTE: _EXECUTE_TOOLS,
    DirectorPhase.INTEGRATE: _INTEGRATE_TOOLS,
}


# =============================================================================
# Dynamic Prompt Generator
# =============================================================================


def get_director_phase_prompt(
    phase: DirectorPhase,
    task_description: str,
    context: ContextDocument | None = None,
    plan: DirectorPlan | None = None,
    current_slice_id: int | None = None,
) -> str | None:
    """Build the complete system prompt injection for the current phase.

    Returns None for phases that don't need injection (IDLE, COMPLETE, FAILED).

    Args:
        phase: Current director phase
        task_description: The task being worked on
        context: ContextDocument from UNDERSTAND phase (if available)
        plan: DirectorPlan from PLAN phase (if available)
        current_slice_id: ID of the current slice being executed (EXECUTE phase)

    Returns:
        System prompt injection string, or None
    """
    base_prompt = PHASE_PROMPTS.get(phase)
    if base_prompt is None:
        return None

    parts = [base_prompt]

    # Always include task description
    parts.append(f"\n<director-task>{task_description}</director-task>")

    # Include context summary in PLAN and later phases
    if context and phase in (
        DirectorPhase.PLAN,
        DirectorPhase.EXECUTE,
        DirectorPhase.INTEGRATE,
    ):
        context_lines = []
        if context.existing_patterns:
            context_lines.append(f"Existing patterns: {', '.join(context.existing_patterns)}")
        if context.constraints:
            context_lines.append(f"Constraints: {', '.join(context.constraints)}")
        if context.affected_files:
            file_paths = [f.path for f in context.affected_files]
            context_lines.append(f"Affected files: {', '.join(file_paths)}")
        if context_lines:
            parts.append(
                "\n<director-context>\n" + "\n".join(context_lines) + "\n</director-context>"
            )

    # Include plan summary in EXECUTE and INTEGRATE phases
    if plan and phase in (DirectorPhase.EXECUTE, DirectorPhase.INTEGRATE):
        plan_lines = [f"Plan: {plan.summary}"]
        plan_lines.append(f"Total slices: {plan.total_slices}")
        for s in plan.slices:
            status = s.status.name if hasattr(s.status, "name") else str(s.status)
            plan_lines.append(f"  Slice {s.id}: {s.title} [{status}]")
        parts.append("\n<director-plan>\n" + "\n".join(plan_lines) + "\n</director-plan>")

    # Include current slice details in EXECUTE phase
    if plan and current_slice_id is not None and phase == DirectorPhase.EXECUTE:
        current_slice = None
        for s in plan.slices:
            if s.id == current_slice_id:
                current_slice = s
                break
        if current_slice:
            slice_lines = [
                f"Current slice: {current_slice.id} - {current_slice.title}",
            ]
            if current_slice.files_to_create:
                slice_lines.append(f"Files to create: {', '.join(current_slice.files_to_create)}")
            if current_slice.files_to_modify:
                slice_lines.append(f"Files to modify: {', '.join(current_slice.files_to_modify)}")
            if current_slice.test_criteria:
                slice_lines.append(f"Test criteria: {', '.join(current_slice.test_criteria)}")
            parts.append(
                "\n<director-current-slice>\n"
                + "\n".join(slice_lines)
                + "\n</director-current-slice>"
            )

    return "\n".join(parts)
