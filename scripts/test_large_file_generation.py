"""
Test large file generation capabilities.

This script tests the agent's ability to generate large files using the new
append_to_file tool and incremental generation strategy.

Run with: python scripts/test_large_file_generation.py
"""

import os
import sys
import tempfile
import shutil
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()

# Add parent directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.core.agent import CodingAgent


def create_agent(workspace):
    """Create a CodingAgent instance with configuration from .env"""
    # Read configuration from environment variables
    model_name = os.getenv("LLM_MODEL")
    backend = os.getenv("LLM_BACKEND", "openai")
    base_url = os.getenv("LLM_HOST")
    context_window = int(os.getenv("MAX_CONTEXT_TOKENS", "32768"))

    if not model_name or not base_url:
        raise ValueError(
            "Missing required configuration in .env file. "
            "Please ensure LLM_MODEL and LLM_HOST are set."
        )

    return CodingAgent(
        model_name=model_name,
        backend=backend,
        base_url=base_url,
        context_window=context_window,
        working_directory=workspace
    )


def setup_test_workspace():
    """Create a temporary workspace for testing."""
    workspace = tempfile.mkdtemp(prefix="test_large_files_")
    print(f"[TEST] Created test workspace: {workspace}")
    return workspace


def cleanup_test_workspace(workspace):
    """Clean up the test workspace."""
    if os.path.exists(workspace):
        shutil.rmtree(workspace)
        print(f"[TEST] Cleaned up workspace: {workspace}")


def validate_file_exists(workspace, filename):
    """Check if a file exists in the workspace."""
    filepath = os.path.join(workspace, filename)
    exists = os.path.exists(filepath)
    if exists:
        size = os.path.getsize(filepath)
        with open(filepath, 'r') as f:
            lines = len(f.readlines())
        print(f"  [OK] {filename} exists ({lines} lines, {size} bytes)")
        return True, lines, size
    else:
        print(f"  [FAIL] {filename} does not exist")
        return False, 0, 0


def validate_python_syntax(workspace, filename):
    """Validate that a Python file has correct syntax."""
    filepath = os.path.join(workspace, filename)
    try:
        with open(filepath, 'r') as f:
            code = f.read()
        compile(code, filepath, 'exec')
        print(f"  [OK] {filename} has valid Python syntax")
        return True
    except SyntaxError as e:
        print(f"  [FAIL] {filename} has syntax error: {e}")
        return False


def test_small_file(workspace):
    """Test 1: Small file (<500 lines) should complete in one write_file."""
    print("\n" + "="*70)
    print("TEST 1: Small File Generation (<500 lines)")
    print("="*70)

    agent = create_agent(workspace)

    prompt = """
Create a simple calculator CLI application in Python with the following functions:
- add(a, b)
- subtract(a, b)
- multiply(a, b)
- divide(a, b)
- main() function for CLI interface

Save it as calculator.py
"""

    print(f"[PROMPT] {prompt.strip()}")
    print("\n[AGENT] Processing...")

    try:
        response = agent.execute_task(prompt)
        print(f"[RESPONSE] {response.content}")

        # Validate
        exists, lines, size = validate_file_exists(workspace, "calculator.py")
        if exists:
            validate_python_syntax(workspace, "calculator.py")
            if lines < 200:
                print(f"  [OK] File size appropriate for simple task ({lines} lines)")
            else:
                print(f"  [WARN] File larger than expected ({lines} lines)")

        return exists
    except Exception as e:
        print(f"[ERROR] Test failed: {e}")
        return False


def test_medium_file(workspace):
    """Test 2: Medium file (500-1500 lines) may use write + append."""
    print("\n" + "="*70)
    print("TEST 2: Medium File Generation (500-1500 lines)")
    print("="*70)

    agent = create_agent(workspace)

    prompt = """
Create a Flask REST API in Python with 5 CRUD endpoints for user management:
- GET /users (list all users)
- GET /users/<id> (get specific user)
- POST /users (create user)
- PUT /users/<id> (update user)
- DELETE /users/<id> (delete user)

Include:
- User model with SQLAlchemy
- Input validation
- Error handling
- Proper HTTP status codes
- JSON responses

Save it as flask_api.py
"""

    print(f"[PROMPT] {prompt.strip()}")
    print("\n[AGENT] Processing...")

    try:
        response = agent.execute_task(prompt)
        print(f"[RESPONSE] {response.content}")

        # Validate
        exists, lines, size = validate_file_exists(workspace, "flask_api.py")
        if exists:
            validate_python_syntax(workspace, "flask_api.py")
            if 200 <= lines <= 1000:
                print(f"  [OK] File size reasonable for medium task ({lines} lines)")
            else:
                print(f"  [WARN] File size unexpected ({lines} lines)")

        return exists
    except Exception as e:
        print(f"[ERROR] Test failed: {e}")
        return False


def test_large_file(workspace):
    """Test 3: Large file (1500+ lines) should use write + multiple appends."""
    print("\n" + "="*70)
    print("TEST 3: Large File Generation (1500+ lines)")
    print("="*70)

    agent = create_agent(workspace)

    prompt = """
Create a complete Flask REST API with 12 CRUD endpoints in Python:

User Management (4 endpoints):
- GET /users, GET /users/<id>, POST /users, PUT /users/<id>, DELETE /users/<id>

Product Management (4 endpoints):
- GET /products, GET /products/<id>, POST /products, PUT /products/<id>, DELETE /products/<id>

Order Management (4 endpoints):
- GET /orders, GET /orders/<id>, POST /orders, PUT /orders/<id>, DELETE /orders/<id>

Additional requirements:
- SQLAlchemy models for User, Product, Order
- JWT authentication middleware
- Input validation with marshmallow schemas
- Error handling and logging
- Database initialization
- Proper HTTP status codes
- JSON responses
- Full docstrings for all functions

This is a production-ready implementation, not a skeleton.
Save it as large_api.py
"""

    print(f"[PROMPT] {prompt.strip()}")
    print("\n[AGENT] Processing...")

    try:
        response = agent.execute_task(prompt)
        print(f"[RESPONSE] {response.content}")

        # Validate
        exists, lines, size = validate_file_exists(workspace, "large_api.py")
        if exists:
            is_valid = validate_python_syntax(workspace, "large_api.py")
            if lines >= 500:
                print(f"  [OK] File is substantial ({lines} lines)")
            else:
                print(f"  [WARN] File smaller than expected for 'production-ready' ({lines} lines)")

            # Check for key components
            with open(os.path.join(workspace, "large_api.py"), 'r') as f:
                content = f.read()
                has_auth = "jwt" in content.lower() or "token" in content.lower()
                has_models = "class User" in content or "class Product" in content
                has_routes = "@app.route" in content

                if has_auth:
                    print("  [OK] Contains authentication code")
                if has_models:
                    print("  [OK] Contains model definitions")
                if has_routes:
                    print("  [OK] Contains route definitions")

        return exists
    except Exception as e:
        print(f"[ERROR] Test failed: {e}")
        return False


def test_multi_file_project(workspace):
    """Test 4: Multi-file project."""
    print("\n" + "="*70)
    print("TEST 4: Multi-File Project Generation")
    print("="*70)

    agent = create_agent(workspace)

    prompt = """
Create a Flask application with separate files:

1. models.py: 3 SQLAlchemy models (User, Product, Category)
2. routes.py: 6 API endpoints (2 per model)
3. app.py: Flask app initialization and configuration

Each file should be complete and production-ready.
"""

    print(f"[PROMPT] {prompt.strip()}")
    print("\n[AGENT] Processing...")

    try:
        response = agent.execute_task(prompt)
        print(f"[RESPONSE] {response.content}")

        # Validate all files
        files = ["models.py", "routes.py", "app.py"]
        results = []
        for filename in files:
            exists, lines, size = validate_file_exists(workspace, filename)
            if exists:
                is_valid = validate_python_syntax(workspace, filename)
                results.append(exists and is_valid)
            else:
                results.append(False)

        return all(results)
    except Exception as e:
        print(f"[ERROR] Test failed: {e}")
        return False


def main():
    """Run all tests."""
    print("\n" + "="*70)
    print("LARGE FILE GENERATION TEST SUITE")
    print("="*70)
    print("\nThis suite tests the agent's ability to generate large files using")
    print("the append_to_file tool and incremental generation strategy.\n")

    workspace = None
    results = {
        "Test 1 (Small File)": False,
        "Test 2 (Medium File)": False,
        "Test 3 (Large File)": False,
        "Test 4 (Multi-File)": False
    }

    try:
        workspace = setup_test_workspace()

        # Run tests
        results["Test 1 (Small File)"] = test_small_file(workspace)
        results["Test 2 (Medium File)"] = test_medium_file(workspace)
        results["Test 3 (Large File)"] = test_large_file(workspace)
        results["Test 4 (Multi-File)"] = test_multi_file_project(workspace)

        # Summary
        print("\n" + "="*70)
        print("TEST SUMMARY")
        print("="*70)
        for test_name, passed in results.items():
            status = "[PASS]" if passed else "[FAIL]"
            print(f"{status} {test_name}")

        passed_count = sum(results.values())
        total_count = len(results)
        pass_rate = (passed_count / total_count) * 100 if total_count > 0 else 0

        print(f"\nResults: {passed_count}/{total_count} tests passed ({pass_rate:.1f}%)")

        if passed_count == total_count:
            print("\n[SUCCESS] All tests passed! Large file generation is working correctly.")
            return 0
        else:
            print("\n[WARNING] Some tests failed. Review the output above for details.")
            return 1

    except KeyboardInterrupt:
        print("\n\n[INTERRUPTED] Tests interrupted by user")
        return 130
    except Exception as e:
        print(f"\n[FATAL ERROR] Test suite failed: {e}")
        import traceback
        traceback.print_exc()
        return 1
    finally:
        if workspace:
            cleanup_test_workspace(workspace)


if __name__ == "__main__":
    sys.exit(main())
