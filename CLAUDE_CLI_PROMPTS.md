# Claude CLI Prompts - Ready to Execute

These are production-ready prompts to give to Claude CLI for systematic testing and improvement.

---

## 🚀 DAY 1: Automated Test Suite

### Prompt 1: Create Comprehensive Test Suite

```
I'm working on an AI coding agent that needs comprehensive testing. Please create a complete pytest test suite.

Context:
- Project location: /workspace/ai-coding-agent
- Main code in: src/
- Key components: memory system, RAG, prompts, LLM integration, tools
- Currently has demo.py but no tests

Your task:
1. Create tests/ directory structure:
   - tests/unit/ (unit tests for each component)
   - tests/integration/ (end-to-end workflows)
   - tests/performance/ (benchmarks)
   - tests/conftest.py (fixtures and setup)

2. Write comprehensive tests:
   - tests/unit/test_memory_manager.py (test memory operations)
   - tests/unit/test_code_indexer.py (test AST parsing and chunking)
   - tests/unit/test_retriever.py (test RAG retrieval)
   - tests/unit/test_prompt_optimizer.py (test token compression)
   - tests/integration/test_agent_workflows.py (end-to-end agent tasks)

3. For each test file:
   - Include at least 10 test cases
   - Test both happy paths and error cases
   - Use proper fixtures and mocks
   - Add clear docstrings

4. Create pytest.ini configuration
5. Add requirements-dev.txt with test dependencies
6. Include README in tests/ explaining how to run tests

Success criteria:
- All tests can be run with: pytest tests/
- Test coverage report available
- Clear pass/fail indicators
- Execution time < 30 seconds

Please start with the memory system tests first, then move to RAG tests.
```

---

## 🎯 DAY 2: Benchmark Suite

### Prompt 2: Build Comprehensive Benchmark Suite

```
Create a benchmark suite to measure the AI coding agent's capabilities across 50+ scenarios.

Project context:
- Location: /workspace/ai-coding-agent
- Agent uses: DeepSeek Coder 6.7B, RAG, hierarchical memory
- Need to establish baseline metrics for improvement tracking

Your task:
1. Create benchmarks/benchmark_suite.py with:

   Categories (10 scenarios each):
   a) Code Understanding
      - Explain architecture
      - Map dependencies
      - Identify patterns
      - Find security issues
      - Analyze performance

   b) Code Generation
      - Add new features
      - Write tests
      - Create utilities
      - Implement APIs

   c) Code Search
      - Find by functionality
      - Search by pattern
      - Locate error handlers

   d) Debugging
      - Identify bugs
      - Suggest fixes
      - Trace execution

   e) Refactoring
      - Extract functions
      - Optimize code
      - Improve structure

2. For each scenario:
   - Clear input query
   - Expected output criteria
   - Success metrics (accuracy, relevance, completeness)
   - Scoring system (0-10)

3. Create benchmarks/run_benchmarks.py:
   - Execute all 50 scenarios
   - Measure: response time, token usage, quality score
   - Generate HTML report with:
     * Overall score by category
     * Response time graphs
     * Failure analysis
     * Comparison with baseline (if exists)

4. Save results to: benchmarks/results/YYYY-MM-DD_results.json

5. Create benchmarks/README.md explaining:
   - How to run benchmarks
   - How to interpret results
   - How to add new scenarios

Success criteria:
- Can run: python benchmarks/run_benchmarks.py
- Generates detailed report in <5 minutes
- Results saved for historical comparison
- Clear metrics for tracking improvements

Start with code understanding scenarios first.
```

---

## 📊 DAY 3: Real-World Codebase Testing

### Prompt 3: Test on Real Open-Source Projects

```
Test the AI coding agent on 5 real-world open-source codebases to validate practical performance.

Setup:
- Agent location: /workspace/ai-coding-agent
- Test repos will be cloned to: /workspace/test-repos/

Your task:
1. Clone these 5 representative projects:
   a) spring-petclinic (Spring Boot - Java)
   b) realworld-react (React - JavaScript)
   c) fastapi-realworld-example (FastAPI - Python)
   d) nestjs-realworld-example (NestJS - TypeScript)
   e) django-rest-framework-tutorial (Django - Python)

2. For each project:
   a) Index the codebase:
      python -m src.cli index /workspace/test-repos/[project]

   b) Test these 10 scenarios:
      - "Explain the project architecture"
      - "How does authentication work?"
      - "Find all API endpoints"
      - "Identify database models and relationships"
      - "What are the main business logic components?"
      - "Find error handling patterns"
      - "Where is input validation done?"
      - "Explain the testing strategy"
      - "How is configuration managed?"
      - "Find potential security issues"

   c) Score each response:
      - Accuracy (0-10): Is the information correct?
      - Completeness (0-10): Did it cover all aspects?
      - Relevance (0-10): Did it answer the question?
      - Code references (0-10): Did it cite specific files/lines?

3. Create real_world_test_report.md with:
   - Results table (project × scenario × scores)
   - Average scores per project
   - Average scores per scenario type
   - Failure analysis (what went wrong?)
   - Strengths identified
   - Improvements needed

4. Identify patterns:
   - Which types of questions work best?
   - Which project structures are easier to understand?
   - Where does the agent struggle?

Success criteria:
- All 5 projects indexed successfully
- All 50 questions (5 projects × 10 scenarios) answered
- Detailed report with actionable insights
- Average score > 7/10 overall

Start with spring-petclinic as it's well-documented.
```

---

## 🏆 DAY 4: Competitive Feature Analysis

### Prompt 4: Compare with Cursor/Codex

```
Create a comprehensive competitive analysis comparing our AI coding agent with Cursor and GitHub Copilot.

Your task:
1. Research Cursor's features:
   - Visit cursor.com
   - Read documentation
   - Check user reviews and discussions
   - Identify key capabilities

2. Research GitHub Copilot features:
   - Official docs
   - User feedback
   - Known strengths/weaknesses

3. Create competitive_analysis.md with:

   A. Feature Comparison Matrix:
   | Feature | Cursor | Copilot | Our Agent | Priority | Effort |
   |---------|--------|---------|-----------|----------|--------|
   | [feature] | [status] | [status] | [status] | [H/M/L] | [H/M/L] |

   Include 30+ features across categories:
   - Code understanding
   - Code generation
   - Code search
   - Multi-file context
   - Chat interface
   - Tool integration
   - Performance
   - Privacy
   - Cost
   - Customization

   B. SWOT Analysis:
   Our Strengths:
   - [list specific advantages]

   Our Weaknesses:
   - [list gaps vs competitors]

   Opportunities:
   - [market opportunities we can exploit]

   Threats:
   - [competitive risks]

   C. Unique Value Propositions:
   - Why would users choose us over Cursor/Copilot?
   - What can we do that they can't?
   - What's our defensible moat?

   D. Must-Have Features for MVP:
   Priority 1 (Critical):
   - [features needed to be competitive]

   Priority 2 (Important):
   - [features that improve UX]

   Priority 3 (Nice-to-have):
   - [features for differentiation]

4. For each missing P1 feature:
   - Estimate implementation effort (days)
   - Define technical approach
   - Identify blockers
   - Suggest alternatives if complex

5. Create user persona analysis:
   - Who would benefit most from our agent?
   - What use cases favor our approach?
   - Where do we have competitive advantage?

Success criteria:
- Complete feature comparison (30+ features)
- Clear prioritization with rationale
- Actionable implementation recommendations
- Strategic positioning identified

Focus on factual analysis, not marketing claims.
```

---

## 📅 DAY 5: 90-Day Roadmap

### Prompt 5: Create Actionable Roadmap

```
Based on test results and competitive analysis, create a detailed 90-day improvement roadmap.

Context:
- Review: TESTING_STRATEGY.md
- Review: benchmark results
- Review: real-world test results
- Review: competitive_analysis.md

Your task:
1. Analyze all testing data to identify:
   - Critical bugs (must fix)
   - Performance bottlenecks (must optimize)
   - Feature gaps (must build)
   - UX friction points (must improve)

2. Create 90_day_roadmap.md structured as:

   Month 1: Foundation (Weeks 1-4)
   ====================================
   Week 1: Testing & Baseline
   - [ ] Task 1 (effort: 2d, impact: H)
   - [ ] Task 2 (effort: 1d, impact: M)
   ...

   Week 2: Performance Optimization
   - [ ] Task 1 (effort: 3d, impact: H)
   ...

   [Repeat for Weeks 3-4]

   Month 2: UX & Features (Weeks 5-8)
   ====================================
   [Detailed weekly breakdown]

   Month 3: Advanced Capabilities (Weeks 9-12)
   ====================================
   [Detailed weekly breakdown]

3. For each task:
   - Clear objective
   - Effort estimate (hours/days)
   - Impact score (H/M/L)
   - Dependencies (what must be done first)
   - Success criteria (how to verify)
   - Owner (can be Claude CLI task or manual)

4. Prioritization criteria:
   - User impact (how much does this help users?)
   - Competitive pressure (do we need this to compete?)
   - Technical risk (can we actually build this?)
   - Resource availability (realistic for one person + AI?)

5. Key milestones:
   - Week 4: All tests passing, baseline established
   - Week 8: MVP feature parity with basic Cursor features
   - Week 12: v1.0 ready for beta users

6. Risk mitigation:
   - What could go wrong?
   - Contingency plans
   - Scope adjustment triggers

Success criteria:
- Detailed task breakdown for 90 days
- Realistic effort estimates
- Clear priorities
- Measurable success criteria
- Actionable from Day 1

Be realistic about what one person + Claude CLI can achieve.
```

---

## 🔧 ONGOING: Weekly Improvement Cycle

### Prompt 6: Weekly Testing & Analysis (Run every Monday)

```
It's the start of a new week. Please run comprehensive tests and analyze results.

Your task:
1. Run all automated tests:
   pytest tests/ -v --cov=src --cov-report=html

2. Run benchmark suite:
   python benchmarks/run_benchmarks.py

3. Compare with baseline:
   - What improved?
   - What regressed?
   - New failures?

4. Analyze trends:
   - Response time (faster/slower?)
   - Quality scores (better/worse?)
   - Test pass rate (stable?)

5. Create weekly_report_YYYY-MM-DD.md:
   ## Test Results
   - Pass rate: X%
   - New failures: [list]
   - Fixed issues: [list]

   ## Performance Metrics
   - Avg response time: Xs (Δ from last week)
   - Token efficiency: X% (Δ from last week)
   - Memory usage: XMB (Δ from last week)

   ## Quality Metrics
   - Code understanding: X/10 (Δ from last week)
   - RAG relevance: X/10 (Δ from last week)

   ## Recommendations
   - Priority 1: [critical fixes]
   - Priority 2: [improvements]
   - Priority 3: [optimizations]

6. Update roadmap:
   - Mark completed tasks ✅
   - Adjust estimates based on learnings
   - Reprioritize if needed

Success criteria:
- Complete report in <10 minutes
- Clear action items for the week
- Progress clearly visible
- Data-driven decisions

This ensures continuous improvement every week.
```

---

## 🎯 Quick Start: Execute Today

### Option 1: Run All Day 1-5 Tasks in Parallel

Open Claude CLI and paste this:

```
I need you to act as a full QA + product team for my AI coding agent.

Please complete these 5 tasks in order:

1. Create comprehensive pytest test suite (see Prompt 1 above)
2. Build 50-scenario benchmark suite (see Prompt 2 above)
3. Test on 5 real codebases (see Prompt 3 above)
4. Create competitive analysis vs Cursor/Codex (see Prompt 4 above)
5. Generate 90-day improvement roadmap (see Prompt 5 above)

For each task:
- Create all files needed
- Run tests/benchmarks
- Generate detailed reports
- Provide actionable recommendations

Save all outputs to:
- tests/ (test suite)
- benchmarks/ (benchmark suite)
- reports/ (analysis and roadmap)

Work systematically through each task.
Report progress after each task completion.
Ask clarifying questions if needed.

Start with Task 1: Test Suite Creation.
```

### Option 2: Start with Highest Impact (Recommended)

```
Let's start with the highest-impact task:

Task: Create comprehensive test suite to establish quality baseline.

Please:
1. Read the project structure in /workspace/ai-coding-agent
2. Create tests/ directory with pytest tests
3. Focus on unit tests first (memory, RAG, prompts)
4. Then integration tests (end-to-end workflows)
5. Run tests and report results

This will establish our quality baseline and identify immediate issues.

See detailed requirements in Prompt 1 above.
```

---

## 📊 Success Tracking

After each prompt execution, track:

| Task | Status | Completion Date | Key Findings | Impact |
|------|--------|----------------|--------------|--------|
| Test Suite | ⏳ | - | - | - |
| Benchmarks | ⏳ | - | - | - |
| Real-world Tests | ⏳ | - | - | - |
| Competitive Analysis | ⏳ | - | - | - |
| 90-Day Roadmap | ⏳ | - | - | - |

Update after each task with specific learnings and improvements implemented.

---

**Ready to execute! Pick a prompt and start testing.** 🚀
