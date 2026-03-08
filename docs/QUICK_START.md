# Quick Start Guide

## Overview
This guide will help you understand and test the AI Coding Agent components we've built so far.

## What's Working Right Now

✅ **Memory Management System**
- Hierarchical memory (Working → Episodic → Semantic)
- Automatic token budgeting
- Session persistence

✅ **RAG System**
- Code indexing with Tree-sitter
- Embedding generation
- Hybrid retrieval (semantic + keyword)

✅ **Prompt Engineering**
- Task-specific templates
- Context optimization
- Token compression

## Installation

```bash
# Navigate to project
cd ai-coding-agent

# Create virtual environment
python -m venv venv

# Activate (Windows)
venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

## Testing Components

### 1. Test Memory System

Create `test_memory.py`:

```python
from src.memory import MemoryManager, Message, MessageRole, ConversationTurn, TaskContext
from datetime import datetime
import uuid

# Initialize memory manager
memory = MemoryManager(
    total_context_tokens=4096,
    working_memory_tokens=2000,
    episodic_memory_tokens=1000,
)

# Set task context
task = TaskContext(
    task_id=str(uuid.uuid4()),
    description="Refactor the login function to use async/await",
    task_type="refactor",
    related_files=["auth/login.py"],
    key_concepts=["async", "authentication", "error handling"],
)
memory.set_task_context(task)

# Add conversation
memory.add_user_message("Can you refactor the login function?")
memory.add_assistant_message(
    "I'll refactor the login function to use async/await pattern...",
    tool_calls=[{"tool": "read_file", "args": {"path": "auth/login.py"}}]
)

# Get context for LLM
system_prompt = "You are an expert Python developer."
context = memory.get_context_for_llm(system_prompt=system_prompt)

print("Context built for LLM:")
for msg in context:
    print(f"\n[{msg['role']}]")
    print(msg['content'][:200] + "..." if len(msg['content']) > 200 else msg['content'])

# Check token budget
budget = memory.get_token_budget()
print(f"\n\nToken Budget:")
for key, value in budget.items():
    print(f"  {key}: {value}")

# Save session
session_path = memory.save_session("test_session")
print(f"\n\nSession saved to: {session_path}")

# Get statistics
stats = memory.get_statistics()
print(f"\n\nMemory Statistics:")
print(f"Session duration: {stats['session_duration_minutes']:.2f} minutes")
print(f"Working memory tokens: {stats['working_memory']['tokens']}")
print(f"Episodic memory turns: {stats['episodic_memory']['total_turns']}")
```

Run:
```bash
python test_memory.py
```

### 2. Test RAG System

Create `test_rag.py`:

```python
from src.rag import CodeIndexer, Embedder, HybridRetriever
from pathlib import Path

# Initialize components
indexer = CodeIndexer(chunk_size=512, chunk_overlap=50)
embedder = Embedder(model_name="sentence-transformers/all-MiniLM-L6-v2")

# Index a sample file (or create one)
sample_code = '''
def calculate_total(items, tax_rate=0.1):
    """Calculate total price with tax."""
    subtotal = sum(item['price'] * item['quantity'] for item in items)
    tax = subtotal * tax_rate
    return subtotal + tax

class ShoppingCart:
    """Shopping cart implementation."""

    def __init__(self):
        self.items = []

    def add_item(self, item):
        """Add item to cart."""
        self.items.append(item)

    def get_total(self):
        """Get cart total."""
        return calculate_total(self.items)
'''

# Save sample file
Path("sample.py").write_text(sample_code)

# Index the file
chunks = indexer.index_file("sample.py")
print(f"Created {len(chunks)} chunks from sample.py\n")

# Generate embeddings
chunks = embedder.embed_chunks(chunks)
print("Embeddings generated\n")

# Setup retriever
retriever = HybridRetriever(embedder, alpha=0.7)
retriever.index_chunks(chunks)

# Search
query = "How do I calculate the total price?"
results = retriever.search(query, chunks, top_k=3)

print(f"Search results for: '{query}'\n")
for result in results:
    print(f"Score: {result.score:.3f} | Semantic: {result.semantic_score:.3f} | Keyword: {result.keyword_score:.3f}")
    print(f"Type: {result.chunk.chunk_type} | Name: {result.chunk.name}")
    print(f"Content: {result.chunk.content[:100]}...")
    print("-" * 80)
```

Run:
```bash
python test_rag.py
```

### 3. Test Prompt Engineering

Create `test_prompts.py`:

```python
from src.prompts import PromptLibrary, SystemPrompts, PromptOptimizer, TaskType

# Get a template
template = PromptLibrary.get_template(TaskType.DEBUG)

# Render with variables
prompt = template.render(
    problem_description="The function crashes when given an empty list",
    code="""
def calculate_average(numbers):
    total = sum(numbers)
    return total / len(numbers)
""",
    error_message="ZeroDivisionError: division by zero"
)

print("DEBUG PROMPT:")
print("=" * 80)
print(prompt)
print("=" * 80)

# Test system prompt
system_prompt = SystemPrompts.get_context_aware_prompt(
    task_type="debug",
    language="python",
    context_size=4096
)

print("\n\nSYSTEM PROMPT:")
print("=" * 80)
print(system_prompt)
print("=" * 80)

# Test prompt compression
optimizer = PromptOptimizer()

long_prompt = """
This is a very long prompt with lots of repetitive information.
It includes multiple examples and detailed explanations.
We need to compress this to fit in a smaller context window.
""" * 20  # Make it long

print(f"\n\nORIGINAL LENGTH: {optimizer.count_tokens(long_prompt)} tokens")

compressed = optimizer.compress_prompt(long_prompt, target_tokens=200)
print(f"COMPRESSED LENGTH: {optimizer.count_tokens(compressed)} tokens")
print("\nCOMPRESSED CONTENT:")
print(compressed[:300] + "...")
```

Run:
```bash
python test_prompts.py
```

## Understanding the Architecture

### Memory Flow
```
User Input → Working Memory → Episodic Memory → Semantic Memory
                ↓                    ↓                  ↓
         Current Context    Compressed History    Vector Search
                ↓                    ↓                  ↓
                     Context Assembly for LLM
```

### RAG Pipeline
```
Source Code → Tree-sitter → AST Analysis → Code Chunks
                                                ↓
                                          Embeddings
                                                ↓
                                          Vector Store
                                                ↓
Query → Hybrid Search (Semantic + Keyword) → Top Results
```

### Prompt Construction
```
System Prompt + Task Template + Retrieved Code + Conversation
              ↓
        Token Optimizer
              ↓
        Compressed Context
              ↓
        LLM Inference
```

## Key Configuration Options

Edit `.env` file:

```env
# Context Window
MAX_CONTEXT_TOKENS=4096
WORKING_MEMORY_TOKENS=2000
EPISODIC_MEMORY_TOKENS=1000

# Embedding Model (smaller = faster)
EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2

# RAG Settings
RAG_TOP_K=5
RAG_CHUNK_SIZE=512
RAG_HYBRID_ALPHA=0.7  # 0.7 = 70% semantic, 30% keyword

# Memory
MEMORY_COMPRESSION_THRESHOLD=0.8
```

## Next Steps

Once we add the LLM backend and core agent:

```python
from src.core import CodingAgent

# Initialize agent
agent = CodingAgent(
    model="codellama:7b-instruct",
    backend="ollama"
)

# Execute task
response = agent.execute_task(
    "Add error handling to the calculate_average function"
)

print(response.result)
```

## Troubleshooting

### Import Errors
- Make sure you're in the project root directory
- Verify virtual environment is activated
- Check all dependencies installed: `pip install -r requirements.txt`

### Memory Issues
- Reduce `MAX_CONTEXT_TOKENS` if running out of RAM
- Decrease embedding batch size in Embedder

### Slow Performance
- Use smaller embedding model: `all-MiniLM-L6-v2` (384 dim)
- Reduce `RAG_TOP_K` for faster retrieval
- Enable caching in Embedder

## Learning Path

1. **Start with Memory**: Understand token budgeting and compression
2. **Explore RAG**: See how code is indexed and retrieved
3. **Study Prompts**: Learn prompt engineering techniques
4. **Experiment**: Try different models, settings, and tasks

## Additional Resources

- **ARCHITECTURE.md**: Deep dive into system design
- **IMPLEMENTATION_ROADMAP.md**: Detailed feature roadmap
- **PROGRESS_SUMMARY.md**: What we've built so far
- **README.md**: Full project documentation

---

**Happy Coding! 🚀**

This foundation is ready for you to build upon and learn from. Each component is modular and well-documented for educational purposes.
