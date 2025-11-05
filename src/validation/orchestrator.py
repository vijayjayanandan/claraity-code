"""
Validation Orchestrator

Executes validation scenarios, spawns agent instances, monitors execution,
runs checks, and generates results.
"""

import asyncio
import subprocess
import json
import os
import sys
import uuid
import shutil
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Any

from .scenario import (
    ValidationScenario,
    ValidationResult,
    ValidationStep,
    StepType,
    DifficultyLevel
)


def safe_print(text: str) -> None:
    """Print text, replacing emojis on Windows to avoid encoding issues."""
    if sys.platform == 'win32':
        # Replace common emojis with text equivalents
        replacements = {
            '[TEST]': '[TEST]',
            '[OK]': '[OK]',
            '[FAIL]': '[FAIL]',
            '[DIR]': '[DIR]',
            '[START]': '[RUN]',
            '[REPORT]': '[REPORT]',
            '[TARGET]': '[TARGET]',
            '[AGENT]': '[AGENT]',
            '📋': '[INFO]',
            '[TIME]': '[TIME]',
            '🔧': '[SETUP]',
            '[WARN]': '[WARN]',
        }
        for emoji, replacement in replacements.items():
            text = text.replace(emoji, replacement)
    try:
        print(text)
    except UnicodeEncodeError:
        # Fallback: remove any remaining problematic characters
        print(text.encode('ascii', 'replace').decode('ascii'))


class ValidationOrchestrator:
    """
    Orchestrates autonomous validation runs.

    Responsibilities:
    1. Create isolated workspaces
    2. Spawn agent instances in subprocesses
    3. Monitor execution and capture metrics
    4. Run automated validation checks
    5. Coordinate with judge for evaluation
    6. Generate comprehensive results
    """

    def __init__(
        self,
        output_dir: str = "./validation-results",
        agent_timeout_seconds: int = 14400  # 4 hours default
    ):
        """
        Initialize orchestrator.

        Args:
            output_dir: Directory for validation artifacts
            agent_timeout_seconds: Max time for agent execution
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True, parents=True)
        self.agent_timeout = agent_timeout_seconds

    async def run_scenario(
        self,
        scenario: ValidationScenario,
        verbose: bool = True
    ) -> ValidationResult:
        """
        Run a complete validation scenario end-to-end.

        Steps:
        1. Create isolated workspace
        2. Run initial setup (if any)
        3. Spawn agent with scenario prompt
        4. Monitor execution
        5. Run validation checks
        6. Calculate scores
        7. Generate artifacts

        Args:
            scenario: Scenario to execute
            verbose: Print progress messages

        Returns:
            ValidationResult with comprehensive metrics
        """

        run_id = str(uuid.uuid4())[:8]
        start_time = datetime.now()

        if verbose:
            safe_print(f"\n{'='*70}")
            safe_print(f"[TEST] Validation: {scenario.name}")
            safe_print(f"📋 ID: {scenario.id}")
            safe_print(f"[TIME]  Estimated: {scenario.estimated_hours} hours")
            safe_print(f"[TARGET] Difficulty: {scenario.difficulty.value.upper()}")
            safe_print(f"{'='*70}\n")

        # Initialize result
        result = ValidationResult(
            scenario_id=scenario.id,
            scenario_name=scenario.name,
            run_id=run_id,
            success=False,
            overall_score=0.0,
            start_time=start_time
        )

        try:
            # Step 1: Create workspace
            if verbose:
                safe_print("[DIR] Creating isolated workspace...")
            workspace = self._create_workspace(scenario, run_id)
            result.workspace_path = str(workspace)

            # Step 2: Run initial setup
            if scenario.initial_setup:
                if verbose:
                    safe_print(f"🔧 Running initial setup...")
                await self._run_setup(scenario, workspace)

            # Step 3: Spawn agent
            if verbose:
                safe_print(f"[AGENT] Spawning agent (timeout: {self.agent_timeout}s)...")
            agent_result = await self._run_agent(scenario, workspace, verbose)

            # Extract metrics from agent execution
            result.duration_seconds = (datetime.now() - start_time).total_seconds()
            result.tokens_used = agent_result.get("tokens_used", 0)
            result.estimated_cost_usd = agent_result.get("cost_usd", 0.0)
            result.tool_calls = agent_result.get("tool_calls", {})
            result.errors_encountered = agent_result.get("errors", [])
            result.warnings = agent_result.get("warnings", [])

            # Step 4: Run validation checks
            if verbose:
                safe_print(f"\n[OK] Running validation checks...")
            check_results = await self._run_validation_checks(
                scenario, workspace, agent_result, verbose
            )
            result.check_results = check_results

            # Extract file metrics
            result.files_created = self._get_created_files(workspace)
            result.lines_of_code = self._count_lines_of_code(workspace)

            # Extract test metrics
            if "test_results" in check_results:
                test_data = check_results["test_results"]
                result.tests_passed = test_data.get("passed", 0)
                result.tests_failed = test_data.get("failed", 0)
                result.test_output = test_data.get("output", "")

            # Step 5: Calculate autonomy
            result.autonomous_percentage = self._calculate_autonomy(agent_result)
            result.human_interventions = agent_result.get("human_interventions", 0)

            # Step 6: Save artifacts
            result.agent_log_path = str(workspace / "agent.log")
            result.transcript_path = str(workspace / "transcript.json")

            if verbose:
                safe_print(f"\n[REPORT] Validation checks complete!")
                safe_print(f"   Files created: {len(result.files_created)}")
                safe_print(f"   Lines of code: {result.lines_of_code}")
                safe_print(f"   Tests passed: {result.tests_passed}/{result.tests_passed + result.tests_failed}")

            result.end_time = datetime.now()

        except Exception as e:
            result.failure_reason = str(e)
            result.failure_stage = "execution"
            result.end_time = datetime.now()
            result.duration_seconds = (result.end_time - start_time).total_seconds()

            if verbose:
                safe_print(f"\n[FAIL] Validation failed: {e}")

        return result

    def _create_workspace(self, scenario: ValidationScenario, run_id: str) -> Path:
        """
        Create isolated workspace for validation run.

        Directory structure:
        validation-results/
          {scenario_id}_{run_id}_{timestamp}/
            context/          # Context files (if any)
            code/             # Generated code goes here
            agent.log         # Agent execution log
            transcript.json   # Full conversation
            result.json       # Final result
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        workspace = self.output_dir / f"{scenario.id}_{run_id}_{timestamp}"
        workspace.mkdir(exist_ok=True, parents=True)

        # Create subdirectories
        (workspace / "context").mkdir(exist_ok=True)
        (workspace / "code").mkdir(exist_ok=True)

        # Copy context files if provided
        if scenario.context_files:
            for file_path in scenario.context_files:
                src = Path(file_path)
                if src.exists():
                    dst = workspace / "context" / src.name
                    shutil.copy2(src, dst)

        return workspace

    async def _run_setup(self, scenario: ValidationScenario, workspace: Path):
        """Run initial setup commands"""
        if not scenario.initial_setup:
            return

        process = await asyncio.create_subprocess_shell(
            scenario.initial_setup,
            cwd=workspace / "code",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            raise RuntimeError(
                f"Setup failed with exit code {process.returncode}\n"
                f"STDERR: {stderr.decode('utf-8', errors='replace')}"
            )

    async def _run_agent(
        self,
        scenario: ValidationScenario,
        workspace: Path,
        verbose: bool
    ) -> Dict[str, Any]:
        """
        Spawn agent in subprocess and monitor execution.

        Creates a Python script that invokes the agent non-interactively,
        runs it, and captures all output and metrics.
        """

        # Create agent invocation script
        agent_script = workspace / "run_agent.py"
        agent_script_content = f'''
import sys
import os
import json
import traceback
from datetime import datetime

# Set UTF-8 encoding for stdout on Windows
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

def safe_print(text: str) -> None:
    """Print text, replacing emojis on Windows to avoid encoding issues."""
    if sys.platform == 'win32':
        import re
        # Remove all emoji characters (simplified approach)
        emoji_pattern = re.compile("["
            u"\\U0001F600-\\U0001F64F"  # emoticons
            u"\\U0001F300-\\U0001F5FF"  # symbols & pictographs
            u"\\U0001F680-\\U0001F6FF"  # transport & map symbols
            u"\\U0001F1E0-\\U0001F1FF"  # flags
            u"\\U00002702-\\U000027B0"
            u"\\U000024C2-\\U0001F251"
            "]+", flags=re.UNICODE)
        text = emoji_pattern.sub('', text)
    try:
        print(text)
    except UnicodeEncodeError:
        print(text.encode('ascii', 'replace').decode('ascii'))

# Add project root to path
sys.path.insert(0, r"{os.getcwd()}")

try:
    from src.core.agent import CodingAgent

    # Initialize agent in AUTO mode for validation (no approval prompts)
    # Use OpenAI-compatible backend with DashScope API (from .env config)
    safe_print("[AGENT] Initializing CodingAgent...")
    api_key = os.environ.get("DASHSCOPE_API_KEY") or os.environ.get("OPENAI_API_KEY")
    agent = CodingAgent(
        model_name="qwen3-coder-plus",  # From .env: LLM_MODEL
        backend="openai",
        base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1",  # From .env: LLM_HOST
        api_key=api_key,
        permission_mode="auto",
        enable_clarity=False  # Disable ClarAIty in validation mode
    )

    # Task prompt
    prompt = """
{scenario.prompt}

IMPORTANT:
- Work in the current directory
- Create all files here
- Include comprehensive tests
- Add a README with setup and usage instructions
"""

    safe_print(f"[INFO] Task prompt:\\n{{prompt}}\\n")
    safe_print("[START] Starting execution...\\n")

    # Execute task
    start_time = datetime.now()

    # Note: We're calling the agent synchronously
    # The agent will use its workflow system for complex tasks
    response = agent.execute_task(prompt)

    duration = (datetime.now() - start_time).total_seconds()

    safe_print(f"\\n[OK] Agent completed in {{duration:.1f}}s")

    # Prepare result
    result = {{
        "success": True,
        "response": str(response) if response else "",
        "duration_seconds": duration,
        "tokens_used": 0,  # TODO: Extract from agent
        "cost_usd": 0.0,   # TODO: Calculate
        "tool_calls": {{}},  # TODO: Extract from agent
        "errors": [],
        "warnings": [],
        "human_interventions": 0
    }}

    # Save result
    with open("result.json", "w") as f:
        json.dump(result, f, indent=2)

except Exception as e:
    safe_print(f"\\n[FAIL] Agent failed with error: {{e}}")
    traceback.print_exc()

    result = {{
        "success": False,
        "error": str(e),
        "traceback": traceback.format_exc(),
        "errors": [str(e)],
        "warnings": [],
        "human_interventions": 0
    }}

    with open("result.json", "w") as f:
        json.dump(result, f, indent=2)

    sys.exit(1)
'''

        agent_script.write_text(agent_script_content, encoding='utf-8')

        # Run agent script
        log_file = workspace / "agent.log"

        process = await asyncio.create_subprocess_exec(
            sys.executable, str(agent_script.absolute()),
            cwd=workspace / "code",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={**os.environ, "VALIDATION_MODE": "1", "DASHSCOPE_API_KEY": os.environ.get("DASHSCOPE_API_KEY", "")}
        )

        try:
            # Wait with timeout
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=self.agent_timeout
            )

            # Save logs
            with open(log_file, "w", encoding='utf-8') as f:
                f.write("=== STDOUT ===\n")
                f.write(stdout.decode('utf-8', errors='replace'))
                f.write("\n\n=== STDERR ===\n")
                f.write(stderr.decode('utf-8', errors='replace'))

            if verbose:
                safe_print(stdout.decode('utf-8', errors='replace'))

        except asyncio.TimeoutError:
            process.kill()
            raise RuntimeError(
                f"Agent execution timed out after {self.agent_timeout}s"
            )

        # Load result
        result_file = workspace / "code" / "result.json"
        if result_file.exists():
            with open(result_file, encoding='utf-8') as f:
                result = json.load(f)
        else:
            result = {
                "success": False,
                "error": "Agent did not produce result.json",
                "stdout": stdout.decode('utf-8', errors='replace'),
                "stderr": stderr.decode('utf-8', errors='replace'),
                "errors": ["No result file produced"],
                "warnings": [],
                "human_interventions": 0
            }

        return result

    async def _run_validation_checks(
        self,
        scenario: ValidationScenario,
        workspace: Path,
        agent_result: Dict[str, Any],
        verbose: bool
    ) -> Dict[str, Any]:
        """
        Run automated validation checks.

        Checks:
        1. Required files exist
        2. Tests pass (if required)
        3. Code runs without errors
        4. Dependencies correct
        5. Custom validation steps
        """

        results = {}
        code_dir = workspace / "code"

        # Check 1: Required files exist
        if scenario.success_criteria.required_files:
            missing_files = []
            for file_path in scenario.success_criteria.required_files:
                full_path = code_dir / file_path
                if not full_path.exists():
                    missing_files.append(file_path)

            results["required_files"] = {
                "success": len(missing_files) == 0,
                "missing": missing_files,
                "found": [f for f in scenario.success_criteria.required_files if f not in missing_files]
            }

            if verbose:
                if missing_files:
                    safe_print(f"   [WARN]  Missing files: {', '.join(missing_files)}")
                else:
                    safe_print(f"   [OK] All required files present")

        # Check 2: Run tests
        if scenario.success_criteria.tests_must_pass:
            test_result = await self._run_tests(code_dir, verbose)
            results["test_results"] = test_result

            if verbose:
                if test_result["success"]:
                    safe_print(f"   [OK] Tests passed: {test_result['passed']}/{test_result['total']}")
                else:
                    safe_print(f"   [FAIL] Tests failed: {test_result['failed']} failures")

        # Check 3: README exists
        if scenario.success_criteria.must_have_readme:
            readme_exists = (code_dir / "README.md").exists()
            results["readme_exists"] = readme_exists

            if verbose:
                status = "[OK]" if readme_exists else "[FAIL]"
                safe_print(f"   {status} README.md: {'Present' if readme_exists else 'Missing'}")

        # Check 4: Run custom validation steps
        for i, step in enumerate(scenario.validation_steps):
            step_key = f"step_{i}_{step.type.value}"
            step_result = await self._run_validation_step(step, code_dir, verbose)
            results[step_key] = step_result

        return results

    async def _install_dependencies(
        self,
        code_dir: Path,
        verbose: bool
    ) -> Dict[str, Any]:
        """
        Install dependencies from requirements.txt if it exists.

        Returns dict with success status and details.
        """
        requirements_file = code_dir / "requirements.txt"

        if not requirements_file.exists():
            if verbose:
                print("   [INFO] No requirements.txt found, skipping dependency installation")
            return {"success": True, "skipped": True}

        if verbose:
            print("   [INSTALL] Installing dependencies from requirements.txt...")

        try:
            process = await asyncio.create_subprocess_exec(
                sys.executable, "-m", "pip", "install", "-r", "requirements.txt", "--quiet",
                cwd=code_dir,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=300  # 5 minutes for installation
            )

            if process.returncode == 0:
                if verbose:
                    print("   [OK] Dependencies installed successfully")
                return {"success": True, "skipped": False}
            else:
                error_msg = stderr.decode('utf-8', errors='replace')
                if verbose:
                    print(f"   [WARN] Dependency installation failed: {error_msg[:200]}")
                return {
                    "success": False,
                    "skipped": False,
                    "error": error_msg
                }

        except asyncio.TimeoutError:
            if verbose:
                print("   [WARN] Dependency installation timed out after 5 minutes")
            return {"success": False, "error": "Installation timeout"}
        except Exception as e:
            if verbose:
                print(f"   [WARN] Dependency installation error: {str(e)}")
            return {"success": False, "error": str(e)}

    async def _run_tests(
        self,
        code_dir: Path,
        verbose: bool
    ) -> Dict[str, Any]:
        """
        Run tests using pytest or unittest.

        Strategy:
        1. Install dependencies from requirements.txt
        2. Try pytest first (handles both pytest and unittest)
        3. If no tests collected, try unittest discovery
        4. Return detailed results
        """

        # Step 1: Install dependencies
        install_result = await self._install_dependencies(code_dir, verbose)
        if not install_result["success"] and not install_result.get("skipped"):
            if verbose:
                print(f"   [WARN] Tests may fail due to missing dependencies")

        # Step 2: Try pytest
        try:
            if verbose:
                print("   [TEST] Running tests with pytest...")

            process = await asyncio.create_subprocess_exec(
                sys.executable, "-m", "pytest", "-v", "--tb=short",
                cwd=code_dir,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=120  # 2 minutes for tests
            )

            output = stdout.decode('utf-8', errors='replace')
            stderr_text = stderr.decode('utf-8', errors='replace')

            # Parse pytest output
            passed = output.count(" PASSED")
            failed = output.count(" FAILED")
            total = passed + failed

            # Check if pytest found any tests
            if total == 0 and "no tests ran" in output.lower():
                if verbose:
                    print("   [INFO] Pytest found no tests, trying unittest...")
                return await self._run_unittest(code_dir, verbose)

            return {
                "success": process.returncode == 0,
                "passed": passed,
                "failed": failed,
                "total": total,
                "output": output,
                "framework": "pytest",
                "exit_code": process.returncode
            }

        except asyncio.TimeoutError:
            return {
                "success": False,
                "error": "Tests timed out after 120s",
                "passed": 0,
                "failed": 0,
                "total": 0,
                "framework": "pytest"
            }
        except Exception as e:
            # If pytest fails, try unittest
            if verbose:
                print(f"   [INFO] Pytest failed ({str(e)}), trying unittest...")
            return await self._run_unittest(code_dir, verbose)

    async def _run_unittest(
        self,
        code_dir: Path,
        verbose: bool
    ) -> Dict[str, Any]:
        """Run tests using unittest discovery."""

        try:
            if verbose:
                print("   [TEST] Running tests with unittest...")

            process = await asyncio.create_subprocess_exec(
                sys.executable, "-m", "unittest", "discover", "-v",
                cwd=code_dir,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=120
            )

            output = stdout.decode('utf-8', errors='replace')
            stderr_text = stderr.decode('utf-8', errors='replace')
            combined = output + "\n" + stderr_text

            # Parse unittest output (tests appear in stderr for unittest)
            # Look for patterns like "test_xxx ... ok" or "test_xxx ... FAIL"
            import re
            ok_pattern = re.compile(r'\.{3,}\s+ok', re.IGNORECASE)
            fail_pattern = re.compile(r'\.{3,}\s+(FAIL|ERROR)', re.IGNORECASE)

            passed = len(ok_pattern.findall(combined))
            failed = len(fail_pattern.findall(combined))
            total = passed + failed

            # Also check summary line like "Ran 14 tests"
            ran_match = re.search(r'Ran (\d+) test', combined)
            if ran_match and total == 0:
                total = int(ran_match.group(1))
                # If we got total but no pass/fail breakdown, assume all passed if returncode == 0
                if process.returncode == 0:
                    passed = total
                    failed = 0
                else:
                    # Parse for failures
                    fail_match = re.search(r'FAILED \(.*?failures=(\d+)', combined)
                    error_match = re.search(r'errors=(\d+)', combined)
                    if fail_match:
                        failed = int(fail_match.group(1))
                    if error_match:
                        failed += int(error_match.group(1))
                    passed = total - failed

            return {
                "success": process.returncode == 0,
                "passed": passed,
                "failed": failed,
                "total": total,
                "output": combined,
                "framework": "unittest",
                "exit_code": process.returncode
            }

        except asyncio.TimeoutError:
            return {
                "success": False,
                "error": "Unittest timed out after 120s",
                "passed": 0,
                "failed": 0,
                "total": 0,
                "framework": "unittest"
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "passed": 0,
                "failed": 0,
                "total": 0,
                "framework": "unittest"
            }

    async def _run_validation_step(
        self,
        step: ValidationStep,
        code_dir: Path,
        verbose: bool
    ) -> Dict[str, Any]:
        """Run a single validation step"""

        if step.type == StepType.BASH:
            return await self._run_bash_step(step, code_dir)
        elif step.type == StepType.PYTEST:
            return await self._run_tests(code_dir, verbose)
        elif step.type == StepType.INSPECT:
            return self._run_inspect_step(step, code_dir)
        else:
            return {"success": False, "error": f"Unknown step type: {step.type}"}

    async def _run_bash_step(
        self,
        step: ValidationStep,
        code_dir: Path
    ) -> Dict[str, Any]:
        """Run a bash command validation step"""

        try:
            process = await asyncio.create_subprocess_shell(
                step.command,
                cwd=code_dir,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=step.timeout_seconds
            )

            success = process.returncode == step.expected_exit_code

            return {
                "success": success,
                "exit_code": process.returncode,
                "expected_exit_code": step.expected_exit_code,
                "stdout": stdout.decode('utf-8', errors='replace'),
                "stderr": stderr.decode('utf-8', errors='replace')
            }

        except asyncio.TimeoutError:
            return {
                "success": False,
                "error": f"Command timed out after {step.timeout_seconds}s"
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }

    def _run_inspect_step(
        self,
        step: ValidationStep,
        code_dir: Path
    ) -> Dict[str, Any]:
        """Inspect file contents"""

        file_path = code_dir / step.file_path
        if not file_path.exists():
            return {
                "success": False,
                "error": f"File not found: {step.file_path}"
            }

        try:
            content = file_path.read_text()

            # Simple criteria checks
            checks = {}
            if step.check_criteria == "has_error_handling":
                checks["has_try_except"] = "try:" in content and "except" in content
            elif step.check_criteria == "has_docstrings":
                checks["has_docstrings"] = '"""' in content or "'''" in content

            success = all(checks.values()) if checks else True

            return {
                "success": success,
                "checks": checks,
                "file_size": len(content)
            }

        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }

    def _get_created_files(self, workspace: Path) -> List[str]:
        """Get list of all files created in workspace"""
        code_dir = workspace / "code"
        if not code_dir.exists():
            return []

        files = []
        for path in code_dir.rglob("*"):
            if path.is_file() and not path.name.startswith("."):
                rel_path = path.relative_to(code_dir)
                files.append(str(rel_path))

        return sorted(files)

    def _count_lines_of_code(self, workspace: Path) -> int:
        """Count total lines of code in .py files"""
        code_dir = workspace / "code"
        if not code_dir.exists():
            return 0

        total_lines = 0
        for py_file in code_dir.rglob("*.py"):
            try:
                lines = len(py_file.read_text().splitlines())
                total_lines += lines
            except:
                pass

        return total_lines

    def _calculate_autonomy(self, agent_result: Dict[str, Any]) -> float:
        """
        Calculate autonomy percentage.

        For now, simple heuristic:
        - If agent completed without error: 100%
        - If agent failed: 0%

        TODO: Extract actual human intervention metrics from agent
        """
        if agent_result.get("success"):
            interventions = agent_result.get("human_interventions", 0)
            if interventions == 0:
                return 1.0
            else:
                # Each intervention reduces autonomy by 10%
                return max(0.0, 1.0 - (interventions * 0.1))
        else:
            return 0.0
