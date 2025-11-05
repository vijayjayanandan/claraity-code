# 🧪 Autonomous Validation Framework

**Autonomous testing system for validating AI Coding Agent capabilities**

---

## Overview

The Autonomous Validation Framework enables **meta-validation**: using Claude (AI) to autonomously test the AI Coding Agent across real-world coding tasks.

### Key Features

- **Autonomous Execution**: Agent runs without human intervention
- **Comprehensive Metrics**: Code quality, correctness, completion, autonomy
- **Claude Judge**: Uses Claude API for code quality evaluation
- **Multiple Scenarios**: Easy/Medium/Hard real-world projects
- **Detailed Reports**: Markdown, HTML, JSON output formats
- **Cost Tracking**: Monitor tokens and costs per validation run

---

## Quick Start

### 1. Ensure API Key is Set

The validation framework uses the **same LLM backend as your agent**, so no additional setup is needed!

```bash
# If you're using Alibaba DashScope (recommended)
export DASHSCOPE_API_KEY="sk-your-key-here"

# Or if using OpenAI
export OPENAI_API_KEY="sk-your-key-here"

# Windows (Command Prompt)
set DASHSCOPE_API_KEY=sk-your-key-here

# Windows (PowerShell)
$env:DASHSCOPE_API_KEY="sk-your-key-here"
```

**Note**: The judge will automatically detect and use the same API key as your agent.

### 3. Run Validation

```bash
# Run all 3 scenarios (easy, medium, hard)
python -m src.validation.run --all

# Run single scenario
python -m src.validation.run --scenario easy_cli_weather

# Run by difficulty
python -m src.validation.run --difficulty easy

# Generate HTML report
python -m src.validation.run --all --format html
```

---

## Architecture

```
┌─────────────────────────────────────────┐
│   Validation Runner (CLI)               │
│   - Scenario selection                  │
│   - Report generation                   │
└───────────────┬─────────────────────────┘
                │
    ┌───────────┴──────────┐
    │                      │
┌───▼──────────────┐  ┌───▼──────────────┐
│  Orchestrator     │  │   Judge          │
│  - Spawn agent    │  │   - Claude API   │
│  - Monitor exec   │  │   - Code review  │
│  - Run checks     │  │   - Scoring      │
└───┬──────────────┘  └──────────────────┘
    │
┌───▼──────────────┐
│  Agent Under Test│
│  (Your AI Agent) │
│  - Executes task │
│  - Generates code│
└──────────────────┘
```

---

## Test Scenarios

### 1. EASY: CLI Weather Tool (2 hours)

**Task**: Build a command-line weather tool with caching

**Requirements**:
- Fetch from wttr.in API
- SQLite caching (1 hour expiry)
- argparse CLI
- Error handling
- 5+ unit tests
- README

**Success Criteria**:
- All files present (`weather.py`, `test_weather.py`, `README.md`)
- Tests pass
- Code runs without errors

**Scoring**:
- Completeness: 30%
- Correctness: 35%
- Quality: 20%
- Autonomy: 15%

---

### 2. MEDIUM: REST API with Auth (4 hours)

**Task**: Create a task management REST API

**Requirements**:
- Flask/FastAPI framework
- SQLAlchemy ORM
- JWT authentication
- Bcrypt password hashing
- 6 endpoints (register, login, CRUD tasks)
- 15+ tests
- README

**Success Criteria**:
- All files present
- Tests pass (15+ tests)
- Authentication working
- Authorization (users see only their tasks)

**Scoring**:
- Completeness: 35%
- Correctness: 35%
- Quality: 20%
- Autonomy: 10%

---

### 3. HARD: Web Scraper with Analytics (6 hours)

**Task**: Build Hacker News scraper with analytics engine

**Requirements**:
- BeautifulSoup4 scraping
- SQLite database
- Rate limiting (1 req/2s)
- Analytics engine (top articles, authors, trends)
- Report generator (markdown/HTML)
- CLI interface
- 20+ tests
- Comprehensive README

**Success Criteria**:
- All 9+ files present
- Tests pass (20+ tests)
- Scraper respects rate limits
- Analytics generate correct insights

**Scoring**:
- Completeness: 40%
- Correctness: 30%
- Quality: 20%
- Autonomy: 10%

---

## Validation Process

### Phase 1: Orchestration (Automated)

1. **Create Workspace**: Isolated directory for each run
2. **Spawn Agent**: Run agent in subprocess with task prompt
3. **Monitor Execution**: Capture all output, logs, metrics
4. **Collect Artifacts**: Generated code, logs, transcripts

### Phase 2: Automated Checks (Automated)

1. **File Existence**: Check required files present
2. **Tests**: Run pytest, count pass/fail
3. **Execution**: Run validation steps (e.g., `python main.py --help`)
4. **Metrics**: Count lines of code, files created

### Phase 3: Judge Evaluation (Claude API)

1. **Collect Code**: Read all generated Python files
2. **Build Prompt**: Send code + task to Claude
3. **Get Scores**: Completeness, Correctness, Quality, Best Practices (0.0-1.0)
4. **Get Feedback**: Strengths, weaknesses, overall assessment

### Phase 4: Final Scoring

1. **Combine Scores**:
   - Completeness = 70% judge + 30% automated
   - Correctness = 70% judge + 30% automated
   - Quality = 90% judge + 10% automated
   - Autonomy = 100% automated

2. **Apply Weights**: Multiply by scenario-specific weights

3. **Determine Pass/Fail**: Overall score ≥ 70% = PASS

---

## Output & Reports

### Directory Structure

```
validation-results/
  easy_cli_weather_abc123_20251104_120000/
    context/          # Context files (if any)
    code/             # Generated code
      weather.py
      test_weather.py
      README.md
      requirements.txt
    agent.log         # Agent execution log
    result.json       # Agent result data
    judge_report.json # Claude evaluation
  validation_report_20251104_120530.md  # Final report
```

### Report Contents

**Executive Summary**:
- Total scenarios: 3
- Passed: 2 / Failed: 1
- Pass rate: 66.7%
- Average score: 73.5%
- Total cost: $2.35
- Total duration: 8.5 hours

**Per-Scenario Results**:
- Overall score
- Detailed scores (completeness, correctness, quality, autonomy)
- Metrics (files created, LOC, tests passed)
- Strengths and weaknesses
- Judge assessment
- Failure reason (if failed)
- Artifact paths

**Key Findings**:
- What works well ✅
- Critical gaps ⚠️
- Recommended priorities 🎯

---

## CLI Reference

### Basic Commands

```bash
# Run all scenarios
python -m src.validation.run --all

# Run specific scenario
python -m src.validation.run --scenario easy_cli_weather
python -m src.validation.run --scenario medium_rest_api
python -m src.validation.run --scenario hard_web_scraper

# Run by difficulty
python -m src.validation.run --difficulty easy
python -m src.validation.run --difficulty medium
python -m src.validation.run --difficulty hard
```

### Options

```bash
# Enable/disable judge evaluation
python -m src.validation.run --all --judge        # Default: enabled
python -m src.validation.run --all --no-judge     # Automated checks only

# Report format
python -m src.validation.run --all --format markdown  # Default
python -m src.validation.run --all --format html
python -m src.validation.run --all --format json

# Output directory
python -m src.validation.run --all --output-dir ./my-results

# Verbose output (default: enabled)
python -m src.validation.run --all --verbose
```

### Available Scenarios

| ID | Name | Difficulty | Est. Time |
|----|------|------------|-----------|
| `easy_cli_weather` | CLI Weather Tool | Easy | 2 hours |
| `medium_rest_api` | Task Management API | Medium | 4 hours |
| `hard_web_scraper` | Hacker News Scraper | Hard | 6 hours |

---

## Cost Estimation

### Judge Evaluation Cost

- **Easy scenario**: ~1,000 tokens → $0.003
- **Medium scenario**: ~2,000 tokens → $0.006
- **Hard scenario**: ~4,000 tokens → $0.012

### Agent Execution Cost

Depends on your agent's LLM backend:
- **Alibaba Cloud (Qwen)**: $0.001-0.005 per 1K tokens
- **OpenAI (GPT-4)**: $0.03-0.06 per 1K tokens

### Total Cost Estimate

| Scenario | Agent Cost | Judge Cost | Total |
|----------|-----------|------------|-------|
| Easy | $0.10-0.50 | $0.003 | $0.11-0.51 |
| Medium | $0.30-1.00 | $0.006 | $0.31-1.01 |
| Hard | $0.50-2.00 | $0.012 | $0.51-2.01 |
| **All 3** | **$0.90-3.50** | **$0.021** | **$0.92-3.52** |

---

## Interpreting Results

### Pass Rate Thresholds

- **≥ 80%**: ✅ Agent performing well
- **50-79%**: ⚠️ Shows promise, needs improvement
- **< 50%**: ❌ Significant gaps, review needed

### Score Breakdown

**Completeness** (did it finish all requirements?):
- 1.0 = All features implemented
- 0.7 = Most features, some missing
- 0.5 = Half complete
- 0.3 = Partial implementation
- 0.0 = Barely started

**Correctness** (does the code work?):
- 1.0 = Works perfectly, all tests pass
- 0.7 = Works mostly, minor bugs
- 0.5 = Partially works
- 0.3 = Major bugs
- 0.0 = Broken/doesn't run

**Quality** (code quality):
- 1.0 = Excellent structure, docs, error handling
- 0.7 = Good quality, minor issues
- 0.5 = Mediocre quality
- 0.3 = Poor structure, no docs
- 0.0 = Very low quality

**Autonomy** (human intervention needed?):
- 1.0 = Fully autonomous
- 0.7 = 1-2 interventions
- 0.5 = Multiple interventions
- 0.3 = Frequent help needed
- 0.0 = Could not proceed alone

---

## Troubleshooting

### Agent Timeout

**Problem**: Agent execution times out

**Solution**:
- Default timeout: 4 hours (14,400s)
- Adjust in `ValidationOrchestrator.__init__()`:
  ```python
  orchestrator = ValidationOrchestrator(
      agent_timeout_seconds=7200  # 2 hours
  )
  ```

### Judge Evaluation Fails

**Problem**: API key not set

**Solution**:
```bash
# Set your API key (same as your agent uses)
export DASHSCOPE_API_KEY="your-key-here"
# OR
export OPENAI_API_KEY="your-key-here"

python -m src.validation.run --all
```

**Problem**: Want to skip judge

**Solution**:
```bash
python -m src.validation.run --all --no-judge
```

### Tests Fail

**Problem**: Agent generated code but tests don't pass

**Analysis**:
- Check `agent.log` for errors
- Review `judge_report.json` for weaknesses
- Common issues:
  - Missing dependencies
  - Import errors
  - Logic bugs

### No Files Generated

**Problem**: Agent didn't create any files

**Possible Causes**:
- Agent crashed early
- Prompt misunderstood
- Workflow routing issue

**Debugging**:
1. Check `agent.log` for errors
2. Review `result.json` for failure reason
3. Check if agent tried to use unavailable tools

---

## Extending the Framework

### Adding New Scenarios

```python
# src/validation/scenarios.py

NEW_SCENARIO = ValidationScenario(
    id="my_new_scenario",
    name="My New Test",
    difficulty=DifficultyLevel.MEDIUM,
    estimated_hours=3.0,
    tags=["api", "database"],

    prompt="""
    Build a ... that does ...

    Requirements:
    1. ...
    2. ...
    """,

    success_criteria=SuccessCriteria(
        required_files=["main.py", "test_main.py"],
        tests_must_pass=True,
        min_test_count=10
    ),

    validation_steps=[
        ValidationStep(
            type=StepType.BASH,
            description="Run main script",
            command="python main.py --help"
        )
    ],

    scoring_weights={
        "completeness": 0.35,
        "correctness": 0.35,
        "quality": 0.20,
        "autonomy": 0.10
    }
)

# Add to registry
VALIDATION_SCENARIOS.append(NEW_SCENARIO)
```

### Custom Validation Steps

```python
# src/validation/scenarios.py

ValidationStep(
    type=StepType.BASH,
    description="Test API endpoint",
    command="curl http://localhost:8000/health",
    expected_exit_code=0
)

ValidationStep(
    type=StepType.INSPECT,
    description="Check error handling",
    file_path="main.py",
    check_criteria="has_error_handling"
)

ValidationStep(
    type=StepType.PYTEST,
    description="Run all tests"
)
```

---

## Best Practices

### 1. Start with Easy Scenario

Run `easy_cli_weather` first to validate framework setup:
```bash
python -m src.validation.run --scenario easy_cli_weather
```

### 2. Review Results Incrementally

After each scenario:
1. Read the markdown report
2. Check `agent.log` for errors
3. Review `judge_report.json` for insights
4. Identify patterns in failures

### 3. Iterate on Agent

Based on validation findings:
1. Fix critical gaps (e.g., error recovery)
2. Re-run validation
3. Measure improvement
4. Repeat

### 4. Cost Management

- Use `--no-judge` for quick iterations
- Enable judge for final validation
- Monitor `estimated_cost_usd` in results

### 5. Continuous Validation

Run after major changes:
```bash
# After implementing new feature
python -m src.validation.run --all

# Compare with baseline
diff validation_report_old.md validation_report_new.md
```

---

## FAQ

**Q: How long does validation take?**

A: Approximately the estimated hours:
- Easy: ~2 hours
- Medium: ~4 hours
- Hard: ~6 hours
- All 3: ~12 hours total

**Q: Can I run scenarios in parallel?**

A: Not currently supported. Run sequentially to avoid resource conflicts.

**Q: What if the agent gets stuck?**

A: Timeout kicks in (default: 4 hours). Check logs for issue.

**Q: How accurate is the judge?**

A: Very accurate for code quality assessment. Uses Claude Sonnet 4.5 with detailed rubric.

**Q: Can I use a different LLM for judge?**

A: Currently requires Anthropic API. Could be extended to support other LLMs.

**Q: What's the difference between automated checks and judge?**

A:
- **Automated**: File existence, tests pass/fail, syntax errors
- **Judge**: Code quality, best practices, architecture, logic correctness

**Q: Can I add my own scenarios?**

A: Yes! See "Extending the Framework" above.

---

## Next Steps

1. ✅ Run your first validation:
   ```bash
   python -m src.validation.run --scenario easy_cli_weather
   ```

2. ✅ Review the generated report

3. ✅ Identify critical gaps

4. ✅ Implement improvements to agent

5. ✅ Re-validate to measure progress

---

**Generated by Autonomous Validation Framework**
**Version 1.0 | 2025-11-04**
