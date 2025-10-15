#!/bin/bash

###############################################################################
# AI Coding Agent - Testing Kickstart Script
# This script sets up the testing infrastructure and guides you through
# systematic testing with Claude CLI
###############################################################################

set -e

echo "╔═══════════════════════════════════════════════════════════╗"
echo "║  AI Coding Agent - Testing Infrastructure Setup         ║"
echo "╚═══════════════════════════════════════════════════════════╝"
echo ""

# Activate venv
source /workspace/ai-coding-agent/venv/bin/activate
cd /workspace/ai-coding-agent

# Create directory structure
echo "📁 Creating testing directory structure..."
mkdir -p tests/unit
mkdir -p tests/integration
mkdir -p tests/performance
mkdir -p tests/quality
mkdir -p benchmarks/results
mkdir -p reports
mkdir -p data/test-repos

echo "✓ Directory structure created"
echo ""

# Install dev dependencies
echo "📦 Installing development dependencies..."
pip install -q pytest pytest-cov pytest-asyncio pytest-benchmark pytest-xdist
pip install -q black flake8 mypy pylint
pip install -q matplotlib pandas tabulate

echo "✓ Dev dependencies installed"
echo ""

# Create pytest configuration
echo "⚙️  Creating pytest configuration..."
cat > pytest.ini << 'EOF'
[pytest]
testpaths = tests
python_files = test_*.py
python_classes = Test*
python_functions = test_*
addopts =
    -v
    --strict-markers
    --tb=short
    --cov=src
    --cov-report=html
    --cov-report=term-missing
    --durations=10
markers =
    unit: Unit tests
    integration: Integration tests
    performance: Performance benchmarks
    quality: Quality metrics tests
    slow: Slow running tests
EOF

echo "✓ pytest.ini created"
echo ""

# Create initial test file
echo "🧪 Creating initial test template..."
cat > tests/test_demo.py << 'EOF'
"""
Demo test to verify pytest setup works.
"""
import pytest
from src.core import CodingAgent
from src.memory import TaskContext

def test_agent_initialization():
    """Test that agent can be initialized."""
    agent = CodingAgent(model_name="deepseek-coder:6.7b-instruct")
    assert agent is not None
    assert agent.llm is not None

def test_task_context_creation():
    """Test task context creation."""
    context = TaskContext(
        task_type="code_understanding",
        description="Test task",
        context="Test context"
    )
    assert context.task_type == "code_understanding"
    assert context.description == "Test task"

@pytest.mark.slow
def test_agent_simple_query():
    """Test agent can handle a simple query."""
    agent = CodingAgent(model_name="deepseek-coder:6.7b-instruct")
    response = agent.execute_task("Say hello in one word")
    assert response is not None
    assert len(response) > 0
EOF

echo "✓ Demo test created"
echo ""

# Run demo test
echo "🚀 Running demo test to verify setup..."
pytest tests/test_demo.py -v
echo ""

# Display summary
echo "╔═══════════════════════════════════════════════════════════╗"
echo "║  ✅ Testing Infrastructure Ready!                         ║"
echo "╚═══════════════════════════════════════════════════════════╝"
echo ""

echo "📊 Created:"
echo "  • tests/ directory with structure"
echo "  • benchmarks/ directory for performance tests"
echo "  • reports/ directory for analysis"
echo "  • pytest.ini configuration"
echo "  • Demo test (tests/test_demo.py)"
echo ""

echo "📚 Documentation:"
echo "  • TESTING_STRATEGY.md - Overall testing strategy"
echo "  • CLAUDE_CLI_PROMPTS.md - Ready-to-use prompts"
echo ""

echo "🎯 Next Steps:"
echo ""
echo "Option 1: Use Claude CLI for automated testing"
echo "  1. Open Claude CLI: claude"
echo "  2. Copy prompts from: CLAUDE_CLI_PROMPTS.md"
echo "  3. Start with Prompt 1 (Test Suite Creation)"
echo ""

echo "Option 2: Manual testing first"
echo "  1. Run existing tests: pytest tests/ -v"
echo "  2. Check coverage: open htmlcov/index.html"
echo "  3. Review TESTING_STRATEGY.md"
echo ""

echo "📈 Track Progress:"
echo "  • Update todo list in TESTING_STRATEGY.md"
echo "  • Save test results to reports/"
echo "  • Compare with baseline weekly"
echo ""

echo "🚀 Recommended: Start with Claude CLI Prompt 1"
echo "   See CLAUDE_CLI_PROMPTS.md for details"
echo ""
