# Agent-to-Agent Orchestration - Design Document

**Goal:** Enable Claude Code to interact with AI Coding Agent like a real developer would, providing rigorous real-world testing through natural conversations.

**Created:** 2025-11-05
**Status:** Design Phase

---

## 🎯 Vision

Instead of predefined scripts, **Claude Code acts as a realistic user** who:
- Starts with unclear requirements
- Asks follow-up questions
- Reports bugs in generated code
- Requests enhancements
- Changes their mind
- Tests edge cases
- Evaluates the full developer experience

This provides **validation that automated tests cannot achieve.**

---

## 🏗️ Architecture

```
┌──────────────────────────────────────────────────────────────┐
│ Claude Code (Testing Agent)                                  │
│ ┌──────────────────────────────────────────────────────────┐ │
│ │ TestScenarioRunner                                       │ │
│ │ - Reads scenario definition                             │ │
│ │ - Formulates natural language requests                  │ │
│ │ - Evaluates responses in real-time                      │ │
│ │ - Decides on follow-ups based on agent's response       │ │
│ │ - Simulates realistic user behavior                     │ │
│ └──────────────────────────────────────────────────────────┘ │
│ ┌──────────────────────────────────────────────────────────┐ │
│ │ ConversationEvaluator                                    │ │
│ │ - Scores each turn (comprehension, execution, etc.)     │ │
│ │ - Identifies failure patterns                           │ │
│ │ - Generates detailed reports                            │ │
│ └──────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────┘
                          │ AgentOrchestrator
                          │ (Manages communication)
                          ▼
┌──────────────────────────────────────────────────────────────┐
│ AI Coding Agent (Subject Under Test)                         │
│ ┌──────────────────────────────────────────────────────────┐ │
│ │ CodingAgent                                              │ │
│ │ - Receives natural language requests                    │ │
│ │ - Plans and executes tasks                              │ │
│ │ - Generates code/documentation                          │ │
│ │ - Responds with natural language                        │ │
│ └──────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────┘
```

---

## 📋 Core Components

### 1. AgentOrchestrator
**Purpose:** Manages bidirectional communication between Claude Code and AI Coding Agent

**Key Methods:**
```python
class AgentOrchestrator:
    def send_message(self, message: str) -> AgentResponse:
        """Send message to AI Coding Agent, get response"""

    def start_conversation(self, scenario: TestScenario) -> ConversationSession:
        """Initialize new test conversation"""

    def end_conversation(self) -> ConversationLog:
        """Finalize conversation, return full log"""
```

**Communication Protocol:**
- **Input:** Natural language message from Claude Code
- **Output:** Natural language response + generated artifacts (code, files, etc.)
- **State:** Maintains conversation history for context

### 2. TestScenario
**Purpose:** Defines realistic user interaction patterns

**Structure:**
```python
@dataclass
class TestScenario:
    name: str
    description: str
    initial_request: str  # First message from "user"
    goal: str  # What success looks like

    # Evaluation criteria
    required_deliverables: List[str]  # e.g., ["app.py", "test_app.py", "README.md"]
    quality_checks: List[Callable]  # Functions to validate code quality

    # Conversation strategy
    clarification_triggers: List[str]  # When to ask follow-ups
    bug_injection: Optional[BugScenario]  # Simulate user finding bugs
    requirement_changes: List[RequirementChange]  # Mid-task changes
```

**Example Scenarios:**

#### Scenario 1: Vague to Clear Requirements
```python
VAGUE_TO_CLEAR = TestScenario(
    name="Vague Requirements Clarification",
    initial_request="I need a web scraper",
    goal="Agent asks clarifying questions, then builds correct scraper",
    expected_questions=[
        "What website do you want to scrape?",
        "What data do you need to extract?",
        "What format should the output be?"
    ]
)
```

#### Scenario 2: Bug Report and Fix
```python
BUG_REPORT_FLOW = TestScenario(
    name="Bug Report and Iteration",
    initial_request="Build a calculator CLI",
    # After agent delivers, Claude Code tests and finds bug
    follow_ups=[
        {
            "trigger": "code_delivered",
            "message": "The division by zero isn't handled. I get a crash.",
            "expected_fix": "Add try-except for ZeroDivisionError"
        }
    ]
)
```

#### Scenario 3: Changing Requirements
```python
REQUIREMENT_CHANGE = TestScenario(
    name="Mid-Task Requirement Change",
    initial_request="Create a REST API for tasks",
    follow_ups=[
        {
            "turn": 2,
            "message": "Actually, can you add user authentication with JWT?",
            "expected_behavior": "Agent modifies existing code, doesn't start from scratch"
        }
    ]
)
```

### 3. ConversationEvaluator
**Purpose:** Claude Code evaluates each turn and overall conversation quality

**Evaluation Dimensions:**

| Dimension | Description | Scale |
|-----------|-------------|-------|
| **Comprehension** | Did agent understand the request? | 1-5 |
| **Clarification** | Did agent ask good questions when needed? | 1-5 |
| **Planning** | Was the approach/plan sound? | 1-5 |
| **Execution** | Does the code work correctly? | 1-5 |
| **Communication** | Were responses clear and helpful? | 1-5 |
| **Error Handling** | How did agent handle mistakes/bugs? | 1-5 |
| **Iteration** | Could agent improve based on feedback? | 1-5 |

**Evaluation Methods:**
```python
class ConversationEvaluator:
    def evaluate_turn(
        self,
        user_message: str,
        agent_response: AgentResponse,
        context: ConversationHistory
    ) -> TurnEvaluation:
        """Evaluate single conversation turn"""

        return TurnEvaluation(
            comprehension_score=self._score_comprehension(...),
            clarification_score=self._score_clarification(...),
            execution_score=self._score_execution(...),
            reasoning="Agent understood the request but didn't ask about edge cases",
            suggestions=["Should clarify error handling requirements"]
        )

    def evaluate_conversation(
        self,
        scenario: TestScenario,
        conversation_log: ConversationLog
    ) -> ConversationEvaluation:
        """Evaluate entire conversation"""

        return ConversationEvaluation(
            overall_score=4.2,  # Average of all dimensions
            goal_achieved=True,
            turn_evaluations=[...],
            strengths=["Good clarification questions", "Fast execution"],
            weaknesses=["Didn't handle edge case", "Could improve error messages"],
            comparison_to_human_developer="Similar to junior developer"
        )
```

### 4. ConversationLogger
**Purpose:** Records full conversation for analysis and debugging

**Output Format:**
```json
{
  "scenario": "Vague Requirements Clarification",
  "started_at": "2025-11-05T14:30:00Z",
  "ended_at": "2025-11-05T14:35:22Z",
  "turns": [
    {
      "turn": 1,
      "user": "I need a web scraper",
      "agent_response": "I can help with that! To build the right scraper, I need some details:\n1. What website do you want to scrape?\n2. What data do you need?\n3. What format should the output be?",
      "evaluation": {
        "comprehension": 5,
        "clarification": 5,
        "reasoning": "Excellent - agent recognized vague request and asked all the right questions"
      }
    },
    {
      "turn": 2,
      "user": "Scrape Hacker News front page, get titles and URLs, output to JSON",
      "agent_response": "Got it! I'll build a scraper for Hacker News...",
      "files_generated": ["scraper.py", "test_scraper.py", "requirements.txt"],
      "evaluation": {
        "execution": 5,
        "code_quality": 4,
        "reasoning": "Code works and has tests, but could use better error handling"
      }
    }
  ],
  "final_evaluation": {
    "overall_score": 4.5,
    "goal_achieved": true,
    "strengths": ["Excellent clarification questions", "Fast execution", "Included tests"],
    "weaknesses": ["Could improve error handling", "No rate limiting mentioned"]
  }
}
```

---

## 🔄 Multi-Turn Conversation Flow

```
┌─────────────────────────────────────────────────────────────┐
│ Turn 1: Initial Request                                     │
├─────────────────────────────────────────────────────────────┤
│ Claude Code: "I need to build a REST API"                  │
│ AI Agent:    "What kind of API? What functionality?"        │
│ Evaluation:  Comprehension=5, Clarification=5              │
└─────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│ Turn 2: Clarification                                       │
├─────────────────────────────────────────────────────────────┤
│ Claude Code: "A task management API with CRUD operations"  │
│ AI Agent:    "Got it! I'll build... [generates code]"      │
│ Evaluation:  Planning=4, Execution=5                       │
└─────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│ Turn 3: Bug Report                                          │
├─────────────────────────────────────────────────────────────┤
│ Claude Code: "I tested it - the DELETE endpoint returns    │
│              500 error instead of 204"                      │
│ AI Agent:    "You're right, let me fix that..."            │
│ Evaluation:  Error Handling=5, Iteration=5                 │
└─────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│ Final: Deliverables Check                                   │
├─────────────────────────────────────────────────────────────┤
│ Files: app.py, test_app.py, README.md ✓                   │
│ Tests: 15/15 passing ✓                                     │
│ Code Quality: Clean, well-documented ✓                     │
│ Overall Score: 4.7/5                                        │
└─────────────────────────────────────────────────────────────┘
```

---

## 🎭 Realistic User Behaviors to Simulate

### 1. Unclear → Clear Requirements
- Start vague: "I need a web app"
- Respond to clarifications: "Actually, just a CLI tool"
- Add constraints: "It should use SQLite, not PostgreSQL"

### 2. Bug Discovery and Reporting
- Test generated code
- Find actual bugs (not hypothetical)
- Report with specifics: "When I run X, I get error Y"
- Verify fix works

### 3. Incremental Feature Requests
- Start simple: "Build a calculator"
- Add features: "Can you add memory functions?"
- Enhance: "Now add history logging"

### 4. Misunderstanding Correction
- Agent misinterprets requirement
- User corrects: "No, I meant X not Y"
- Agent adjusts approach

### 5. Edge Case Discovery
- Agent delivers working code
- User tests edge cases: "What if input is empty?"
- Agent handles robustness

---

## 📊 Evaluation Rubric

### Per-Turn Evaluation (1-5 scale):

**5 - Excellent:** Exceeds expectations, professional quality
**4 - Good:** Meets expectations, solid work
**3 - Adequate:** Works but has issues
**2 - Poor:** Significant problems
**1 - Failing:** Doesn't work or misunderstands completely

### Overall Conversation Evaluation:

**Score Bands:**
- **4.5-5.0:** Senior developer level
- **4.0-4.4:** Mid-level developer
- **3.5-3.9:** Junior developer
- **3.0-3.4:** Intern level
- **< 3.0:** Needs significant improvement

**Qualitative Assessment:**
- Would you hire this agent as a contractor?
- Would you trust it with production code?
- How does it compare to human developers?

---

## 🛠️ Implementation Plan

### Phase 1: Basic Communication (Day 1, 4 hours)
**Goal:** Single-turn conversation working

**Deliverables:**
- [ ] `AgentOrchestrator` class
- [ ] Simple CLI interface for testing
- [ ] Conversation logging to JSON
- [ ] Manual test: Send message, get response

**Success Criteria:**
```bash
$ python -m src.orchestration.test_basic
User: "Build a hello world script"
Agent: [generates hello.py]
✓ Communication working
```

### Phase 2: Multi-Turn Support (Day 1-2, 4 hours)
**Goal:** Back-and-forth conversations with context

**Deliverables:**
- [ ] `ConversationSession` class
- [ ] Conversation history management
- [ ] Context passed to AI Coding Agent
- [ ] State persistence between turns

**Success Criteria:**
```python
session = orchestrator.start_conversation()
session.send("Build a calculator")
response1 = session.get_response()
session.send("Add memory functions")  # Agent remembers calculator
response2 = session.get_response()
assert "calculator" in response2.context
```

### Phase 3: Test Scenarios (Day 2, 4 hours)
**Goal:** Define 5 realistic user scenarios

**Deliverables:**
- [ ] `TestScenario` data class
- [ ] 5 predefined scenarios:
  1. Vague → Clear Requirements
  2. Bug Report → Fix
  3. Incremental Features
  4. Misunderstanding Correction
  5. Edge Case Discovery
- [ ] Scenario execution framework

**Success Criteria:**
```bash
$ python -m src.orchestration.run_scenario vague_to_clear
Turn 1: "I need a web scraper" → Agent asks clarifying questions
Turn 2: User provides details → Agent builds scraper
Turn 3: User tests → Works correctly
✓ Scenario completed
```

### Phase 4: Evaluation Framework (Day 3, 4 hours)
**Goal:** Claude Code evaluates interactions

**Deliverables:**
- [ ] `ConversationEvaluator` class
- [ ] 7-dimension scoring system
- [ ] Per-turn evaluation
- [ ] Overall conversation scoring
- [ ] Detailed report generation

**Success Criteria:**
```python
evaluator = ConversationEvaluator()
evaluation = evaluator.evaluate_conversation(scenario, log)
assert evaluation.overall_score >= 3.0
assert len(evaluation.strengths) > 0
assert len(evaluation.weaknesses) > 0
print(evaluation.generate_report())  # Human-readable markdown
```

### Phase 5: Comprehensive Testing (Day 3-4, 8 hours)
**Goal:** Run 10+ scenarios, identify patterns

**Deliverables:**
- [ ] 10 diverse test scenarios
- [ ] Automated scenario runner
- [ ] Comparative analysis (vs human developers)
- [ ] Comprehensive report with:
  - Overall agent capabilities
  - Strengths and weaknesses
  - Failure patterns
  - Improvement recommendations

**Success Criteria:**
```bash
$ python -m src.orchestration.run_all_scenarios
Running 10 scenarios...
[1/10] Vague Requirements: 4.5/5 ✓
[2/10] Bug Report Flow: 4.2/5 ✓
[3/10] Changing Requirements: 3.8/5 ⚠
...
[10/10] Complex Refactoring: 2.5/5 ✗

Overall: 3.9/5 (Junior-Mid Developer Level)
Report: validation-results/agent_to_agent_report_20251105.md
```

---

## 🎯 Example Test Scenarios

### Scenario 1: Vague to Clear Requirements

```python
VAGUE_TO_CLEAR = TestScenario(
    name="Vague Requirements Clarification",
    description="User starts with unclear request, agent clarifies, then delivers",

    turns=[
        Turn(
            user_message="I need a web scraper",
            expected_agent_behavior="Ask clarifying questions",
            evaluation_criteria={
                "comprehension": "Agent recognizes request is vague",
                "clarification": "Agent asks about website, data, format",
            }
        ),
        Turn(
            user_message="Scrape Hacker News, get titles and URLs, output JSON",
            expected_agent_behavior="Build scraper with requirements",
            evaluation_criteria={
                "execution": "Code works and produces correct JSON",
                "quality": "Includes error handling and tests",
            }
        ),
    ],

    success_criteria={
        "deliverables": ["scraper.py", "test_scraper.py", "requirements.txt"],
        "tests_passing": True,
        "manual_test": "Run scraper, verify JSON output is valid",
    }
)
```

### Scenario 2: Bug Report and Iteration

```python
BUG_REPORT_FLOW = TestScenario(
    name="Bug Discovery and Fix",
    description="Agent delivers code, user finds bug, agent fixes it",

    turns=[
        Turn(
            user_message="Build a CLI calculator with +, -, *, / operations",
            expected_agent_behavior="Generate working calculator",
        ),
        # Claude Code tests the generated code
        Turn(
            user_message="I tested it - when I do '5 / 0', it crashes instead of showing an error",
            expected_agent_behavior="Fix division by zero handling",
            evaluation_criteria={
                "error_handling": "Agent acknowledges bug and fixes it",
                "iteration": "Agent modifies existing code, doesn't start over",
            }
        ),
        Turn(
            user_message="Thanks! Can you also add a sqrt function?",
            expected_agent_behavior="Add feature to existing code",
            evaluation_criteria={
                "iteration": "Extends existing calculator, maintains quality",
            }
        ),
    ],

    success_criteria={
        "no_crashes": True,
        "all_operations_work": True,
        "tests_updated": True,
    }
)
```

### Scenario 3: Changing Requirements Mid-Task

```python
CHANGING_REQUIREMENTS = TestScenario(
    name="Mid-Task Requirement Change",
    description="User changes requirements after agent starts working",

    turns=[
        Turn(
            user_message="Create a simple REST API for managing tasks - just title and completed status",
            expected_agent_behavior="Start building simple CRUD API",
        ),
        Turn(
            # Agent is in progress or just finished
            user_message="Actually, I need user authentication too. Each user should only see their own tasks.",
            expected_agent_behavior="Modify plan to include auth, don't start from scratch",
            evaluation_criteria={
                "flexibility": "Agent adapts to new requirement",
                "efficiency": "Reuses existing work where possible",
            }
        ),
    ],

    success_criteria={
        "auth_implemented": True,
        "task_isolation": "Users can only see own tasks",
        "backward_compatible": "Original CRUD still works",
    }
)
```

---

## 📈 Expected Outcomes

### Quantitative Metrics:
- **Overall Agent Score:** 3.5-4.5 (target: mid-level developer)
- **Scenario Pass Rate:** 70-90% (target: 80%+)
- **Average Turns per Scenario:** 3-5
- **Bug Fix Success Rate:** 80%+ (agent can fix reported bugs)

### Qualitative Insights:
- **Strengths:** What agent does well (e.g., code generation, testing)
- **Weaknesses:** What needs improvement (e.g., edge cases, communication)
- **Failure Patterns:** Common failure modes (e.g., misunderstands vague requests)
- **Comparison:** How agent compares to human developers

### Actionable Improvements:
Based on findings, we'll know:
1. What prompts to improve
2. What tools to add
3. What workflows to optimize
4. What training data to include

---

## 🔍 Why This Matters

### Current Testing (Automated):
- ✅ Tests predefined scenarios with fixed inputs
- ✅ Validates code correctness
- ❌ Doesn't test conversational ability
- ❌ Doesn't test real-world workflows
- ❌ Doesn't test iteration and improvement

### Agent-to-Agent Testing (Proposed):
- ✅ Tests realistic user interactions
- ✅ Tests clarification and communication
- ✅ Tests iteration and bug fixing
- ✅ Tests adaptability to changing requirements
- ✅ Provides developer-experience feedback

**This reveals gaps that automated tests miss.**

---

## 🚀 Next Steps

1. **Get User Approval** - Confirm this approach makes sense
2. **Phase 1 Implementation** - Build basic communication (4 hours)
3. **Phase 2 Implementation** - Add multi-turn support (4 hours)
4. **Phase 3 Implementation** - Create test scenarios (4 hours)
5. **Phase 4 Implementation** - Build evaluation framework (4 hours)
6. **Phase 5 Execution** - Run comprehensive testing (8 hours)

**Total Estimated Time:** 3-4 days (24 hours of focused work)

**Deliverables:**
- Fully autonomous agent-to-agent testing framework
- 10+ realistic test scenarios
- Detailed evaluation reports
- Actionable improvement recommendations

---

## 💡 Additional Ideas

### Future Enhancements:
1. **Adversarial Testing:** Claude Code intentionally gives confusing/contradictory requests
2. **Performance Testing:** Measure response time, token usage, cost
3. **Multi-Agent Scenarios:** Multiple users working on same codebase
4. **Long-Term Projects:** Test agent over 10+ conversation turns
5. **Comparison Testing:** Same scenario with different LLMs/prompts

### Integration with Existing Validation:
- Run both automated tests AND agent-to-agent tests
- Automated: Tests code correctness
- Agent-to-Agent: Tests developer experience
- Combined score gives full picture

---

**Ready to proceed?** Let me know if you want me to start with Phase 1 (basic communication), or if you'd like to discuss/modify the architecture first!
