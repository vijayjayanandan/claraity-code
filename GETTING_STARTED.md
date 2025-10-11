# Getting Started with AI Coding Agent

## Prerequisites

### 1. Install Ollama

Download and install Ollama from: https://ollama.ai

### 2. Pull a Code Model

```bash
# Recommended: CodeLlama 7B Instruct
ollama pull codellama:7b-instruct

# Alternatives:
ollama pull deepseek-coder:6.7b-instruct  # Better for complex tasks
ollama pull qwen2.5-coder:7b              # Large context (32K)
```

### 3. Verify Ollama is Running

```bash
ollama list  # Should show installed models
```

## Installation

### 1. Clone and Setup

```bash
cd ai-coding-agent

# Create virtual environment
python -m venv venv

# Activate (Windows)
venv\Scripts\activate

# Activate (Mac/Linux)
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Verify Installation

```bash
python -c "import src; print('✓ Installation successful!')"
```

## Quick Start

### Option 1: Interactive Chat Mode

```bash
python -m src.cli chat
```

This starts an interactive session where you can:
- Ask coding questions
- Request code implementations
- Debug issues
- Get explanations

**Example session:**
```
You: Explain how the memory manager works
Agent: [Provides detailed explanation...]

You: Create a function to calculate fibonacci numbers
Agent: [Generates code with explanation...]

You: save my_session
✓ Session saved to: ./data/sessions/my_session
```

### Option 2: Single Task Execution

```bash
python -m src.cli task "Add error handling to the login function" --type implement
```

### Option 3: Index Codebase for RAG

```bash
python -m src.cli index ./my_project
```

This indexes your codebase for intelligent code retrieval.

### Option 4: Run the Demo

```bash
python demo.py
```

This demonstrates all features working together.

## Basic Usage Examples

### Example 1: Code Implementation

```python
from src.core import CodingAgent

# Initialize agent
agent = CodingAgent(
    model_name="codellama:7b-instruct",
    backend="ollama",
)

# Execute task
response = agent.execute_task(
    task_description="Create a function to validate email addresses",
    task_type="implement",
)

print(response.content)
```

### Example 2: With RAG (Codebase Search)

```python
# Index your codebase
agent.index_codebase(directory="./my_project")

# Now agent can search relevant code
response = agent.execute_task(
    task_description="How is user authentication implemented?",
    task_type="explain",
    use_rag=True,
)

print(response.content)
```

### Example 3: Debug Code

```python
code = '''
def calculate_average(numbers):
    return sum(numbers) / len(numbers)
'''

response = agent.execute_task(
    task_description=f"Debug this code: {code}\nError: ZeroDivisionError when list is empty",
    task_type="debug",
)

print(response.content)
```

### Example 4: Interactive Chat

```python
# Chat interface
while True:
    user_input = input("You: ")
    if user_input.lower() == "exit":
        break

    response = agent.chat(user_input, stream=True)
    # Response is streamed to console
```

## CLI Commands

### Chat Mode
```bash
python -m src.cli chat [--model MODEL] [--context SIZE]
```

**In-chat commands:**
- `help` - Show available commands
- `stats` - Show agent statistics
- `save [name]` - Save session
- `clear` - Clear memory
- `exit` - Exit chat

### Task Mode
```bash
python -m src.cli task "TASK_DESCRIPTION" [--type TYPE]
```

Types: `implement`, `debug`, `refactor`, `explain`, `test`, `review`

### Index Mode
```bash
python -m src.cli index [DIRECTORY]
```

## Configuration

### Using Different Models

```bash
# DeepSeek Coder (great for coding)
ollama pull deepseek-coder:6.7b-instruct
python -m src.cli chat --model deepseek-coder:6.7b-instruct

# Qwen 2.5 Coder (large context)
ollama pull qwen2.5-coder:7b
python -m src.cli chat --model qwen2.5-coder:7b --context 8192
```

### Adjusting Context Window

```bash
# For models with larger context
python -m src.cli chat --context 8192

# For limited memory
python -m src.cli chat --context 2048
```

## Understanding the Components

### 1. Memory System
- **Working Memory**: Current conversation (2K tokens)
- **Episodic Memory**: Session history with compression (10K tokens)
- **Semantic Memory**: Vector DB for long-term storage

### 2. RAG System
- Indexes code with Tree-sitter AST parsing
- Hybrid search (semantic + keyword)
- Retrieves top-5 relevant chunks per query

### 3. Prompt Engineering
- Task-specific templates
- Token compression (40-60% reduction)
- Context-aware optimization

### 4. Tools
- `read_file` - Read file contents
- `write_file` - Write to file
- `edit_file` - Find/replace editing
- `search_code` - Search codebase
- `analyze_code` - Extract structure info

## Troubleshooting

### Ollama Not Found
```bash
# Check if Ollama is running
curl http://localhost:11434/api/tags

# Start Ollama (if installed)
# Windows: Run Ollama from Start Menu
# Mac/Linux: ollama serve
```

### Model Not Found
```bash
# List available models
ollama list

# Pull the model
ollama pull codellama:7b-instruct
```

### Out of Memory
```bash
# Use smaller context
python -m src.cli chat --context 2048

# Use smaller model
python -m src.cli chat --model codellama:7b-instruct
```

### Slow Response
- Use quantized models (Q4, Q5)
- Reduce context window
- Disable RAG if not needed: `use_rag=False`

## Next Steps

1. **Explore Examples**: Check `examples/` directory
2. **Read Architecture**: See `ARCHITECTURE.md`
3. **Customize Prompts**: Edit `src/prompts/templates.py`
4. **Add Tools**: Extend `src/tools/`
5. **Try Different Models**: Experiment with various LLMs

## Advanced Usage

### Save and Resume Sessions

```python
# Save session
session_path = agent.save_session("project_analysis")

# Later, load it
agent.load_session(Path("./data/sessions/project_analysis"))
```

### Custom Tool

```python
from src.tools import Tool, ToolResult, ToolStatus

class MyTool(Tool):
    def __init__(self):
        super().__init__("my_tool", "My custom tool")

    def execute(self, **kwargs):
        # Your logic here
        return ToolResult(
            tool_name=self.name,
            status=ToolStatus.SUCCESS,
            output="Result"
        )

# Register
agent.tool_executor.register_tool(MyTool())
```

### Monitor Memory Usage

```python
# Get statistics
stats = agent.get_statistics()
memory_stats = stats['memory']

print(f"Working memory: {memory_stats['working_memory']['tokens']} tokens")
print(f"Episodic memory: {memory_stats['episodic_memory']['total_turns']} turns")

# Check token budget
budget = agent.memory.get_token_budget()
print(f"Remaining tokens: {budget['remaining']}")
```

## Tips for Best Results

1. **Be Specific**: Provide clear, detailed task descriptions
2. **Use RAG**: Index codebase for context-aware responses
3. **Right Model**: Choose appropriate model for task complexity
4. **Context Size**: Match model's optimal context window
5. **Save Sessions**: Resume complex tasks across sessions

## Support

- **Issues**: Report bugs at GitHub Issues
- **Documentation**: See `docs/` directory
- **Examples**: Check `examples/` directory
- **Architecture**: Read `ARCHITECTURE.md`

---

**You're all set!** Start with `python -m src.cli chat` and explore the AI coding agent.
