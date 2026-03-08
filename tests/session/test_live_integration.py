"""Live integration tests for session persistence with actual LLM calls.

These tests make REAL API calls through the configured LLM endpoint.
They are skipped if required environment variables are not set.

Run with: pytest tests/session/test_live_integration.py -v -s
"""

import pytest
import asyncio
import os
import tempfile
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

from src.session.models import Message, ToolCall, ToolCallFunction
from src.session.store import MessageStore
from src.session.persistence import SessionWriter, load_session
from src.session.providers import from_openai, to_openai
from src.session.manager import SessionManager


def get_llm_config():
    """Get LLM configuration from environment."""
    from src.llm.base import LLMConfig, LLMBackendType

    backend_type = os.getenv("LLM_BACKEND", "openai")
    model_name = os.getenv("LLM_MODEL", "gpt-4")
    base_url = os.getenv("LLM_HOST", "https://api.openai.com/v1")

    return LLMConfig(
        backend_type=LLMBackendType.OPENAI if backend_type == "openai" else LLMBackendType.OLLAMA,
        model_name=model_name,
        base_url=base_url,
        temperature=float(os.getenv("LLM_TEMPERATURE", "0.2")),
        max_tokens=int(os.getenv("LLM_MAX_TOKENS", "1024")),
        top_p=float(os.getenv("LLM_TOP_P", "0.95")),
        top_k=int(os.getenv("LLM_TOP_K", "40")),
        context_window=int(os.getenv("MAX_CONTEXT_TOKENS", "4096")),
        timeout=float(os.getenv("REQUEST_TIMEOUT", "60")),
    )


def has_llm_credentials():
    """Check if LLM credentials are available."""
    api_key = os.getenv("OPENAI_API_KEY")
    return api_key is not None and len(api_key) > 0


# Skip all tests in this module if no credentials
pytestmark = pytest.mark.skipif(
    not has_llm_credentials(),
    reason="LLM credentials not configured (OPENAI_API_KEY not set)"
)


class TestLiveLLMIntegration:
    """Live tests that make actual LLM API calls."""

    @pytest.mark.asyncio
    async def test_simple_generation_and_persist(self):
        """Test: Make LLM call -> Parse response -> Persist -> Reload -> Verify."""
        from src.llm.openai_backend import OpenAIBackend

        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "live_test.jsonl"

            # Initialize backend
            config = get_llm_config()
            backend = OpenAIBackend(config)

            # Create store and writer
            store = MessageStore()
            writer = SessionWriter(file_path)
            await writer.open()
            writer.bind_to_store(store)

            session_id = "live-test-session"

            # Create user message
            user_msg = Message.create_user(
                content="What is 2 + 2? Reply with just the number.",
                session_id=session_id,
                parent_uuid=None,
                seq=store.next_seq()
            )
            store.add_message(user_msg)

            # Make actual LLM call
            messages_for_llm = store.get_llm_context()
            response = backend.generate(messages_for_llm)

            print(f"\n[LIVE TEST] Model: {response.model}")
            print(f"[LIVE TEST] Response: {response.content}")
            print(f"[LIVE TEST] Tokens: {response.total_tokens}")

            # Create assistant message from response
            assistant_msg = Message.create_assistant(
                content=response.content,
                session_id=session_id,
                parent_uuid=user_msg.uuid,
                seq=store.next_seq(),
                model=response.model
            )
            store.add_message(assistant_msg)

            # Wait for persistence
            await asyncio.sleep(0.2)
            await writer.close()

            # Reload and verify
            resumed_store = load_session(file_path)

            assert resumed_store.message_count == 2, f"Expected 2, got {resumed_store.message_count}"

            messages = resumed_store.get_ordered_messages()
            assert messages[0].role == "user"
            assert messages[1].role == "assistant"
            assert messages[1].content is not None
            assert "4" in messages[1].content  # Should contain the answer

            print(f"[LIVE TEST] Roundtrip successful! Persisted and reloaded {resumed_store.message_count} messages")

    @pytest.mark.asyncio
    async def test_tool_calling_and_persist(self):
        """Test: LLM tool call -> Parse response -> Persist -> Reload -> Verify."""
        from src.llm.openai_backend import OpenAIBackend
        from src.llm.base import ToolDefinition

        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "tool_test.jsonl"

            # Initialize backend
            config = get_llm_config()
            backend = OpenAIBackend(config)

            # Create store and writer
            store = MessageStore()
            writer = SessionWriter(file_path)
            await writer.open()
            writer.bind_to_store(store)

            session_id = "tool-test-session"

            # Define a simple tool
            tools = [
                ToolDefinition(
                    name="get_weather",
                    description="Get the current weather for a location",
                    parameters={
                        "type": "object",
                        "properties": {
                            "location": {
                                "type": "string",
                                "description": "City name"
                            }
                        },
                        "required": ["location"]
                    }
                )
            ]

            # Create user message requesting weather
            user_msg = Message.create_user(
                content="What's the weather in Paris?",
                session_id=session_id,
                parent_uuid=None,
                seq=store.next_seq()
            )
            store.add_message(user_msg)

            # Make actual LLM call with tools
            messages_for_llm = store.get_llm_context()

            try:
                response = backend.generate_with_tools(messages_for_llm, tools, tool_choice="auto")
            except NotImplementedError:
                pytest.skip("Backend does not support tool calling")

            print(f"\n[LIVE TEST] Model: {response.model}")
            print(f"[LIVE TEST] Content: {response.content}")
            print(f"[LIVE TEST] Tool calls: {response.tool_calls}")

            # Create assistant message
            # response.tool_calls now contains Session Model ToolCall objects
            tool_calls = response.tool_calls if response.tool_calls else []

            assistant_msg = Message.create_assistant(
                content=response.content,
                session_id=session_id,
                parent_uuid=user_msg.uuid,
                seq=store.next_seq(),
                tool_calls=tool_calls if tool_calls else None,
                model=response.model
            )
            store.add_message(assistant_msg)

            # If tool was called, add mock tool result
            if response.tool_calls:
                for tc in response.tool_calls:
                    tool_result = Message.create_tool(
                        tool_call_id=tc.id,
                        content='{"temperature": "22C", "condition": "sunny"}',
                        session_id=session_id,
                        parent_uuid=assistant_msg.uuid,
                        seq=store.next_seq(),
                        status="success"
                    )
                    store.add_message(tool_result)

            # Wait for persistence
            await asyncio.sleep(0.2)
            await writer.close()

            # Reload and verify
            resumed_store = load_session(file_path)

            print(f"[LIVE TEST] Persisted {resumed_store.message_count} messages")

            # Verify structure
            messages = resumed_store.get_ordered_messages()
            assert messages[0].role == "user"
            assert messages[1].role == "assistant"

            # If tool was called, verify tool messages
            if response.tool_calls:
                assert resumed_store.message_count >= 3
                assert any(m.role == "tool" for m in messages)
                assert messages[1].has_tool_calls()
                print(f"[LIVE TEST] Tool call roundtrip successful!")
            else:
                print(f"[LIVE TEST] LLM responded without tool call (normal text response)")

    @pytest.mark.asyncio
    async def test_streaming_and_persist(self):
        """Test: Streaming LLM call -> Accumulate -> Persist -> Reload."""
        from src.llm.openai_backend import OpenAIBackend

        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "stream_test.jsonl"

            # Initialize backend
            config = get_llm_config()
            backend = OpenAIBackend(config)

            # Create store and writer
            store = MessageStore()
            writer = SessionWriter(file_path)
            await writer.open()
            writer.bind_to_store(store)

            session_id = "stream-test-session"

            # Create user message
            user_msg = Message.create_user(
                content="Count from 1 to 5.",
                session_id=session_id,
                parent_uuid=None,
                seq=store.next_seq()
            )
            store.add_message(user_msg)

            # Make streaming LLM call
            messages_for_llm = store.get_llm_context()
            accumulated_content = ""
            model_name = None

            print("\n[LIVE TEST] Streaming response: ", end="", flush=True)

            for chunk in backend.generate_stream(messages_for_llm):
                accumulated_content += chunk.content
                model_name = chunk.model
                print(chunk.content, end="", flush=True)

                if chunk.done:
                    break

            print()  # Newline after streaming

            # Create assistant message from accumulated content
            assistant_msg = Message.create_assistant(
                content=accumulated_content,
                session_id=session_id,
                parent_uuid=user_msg.uuid,
                seq=store.next_seq(),
                model=model_name
            )
            store.add_message(assistant_msg)

            # Wait for persistence
            await asyncio.sleep(0.2)
            await writer.close()

            # Reload and verify
            resumed_store = load_session(file_path)

            assert resumed_store.message_count == 2

            messages = resumed_store.get_ordered_messages()
            assert messages[1].content == accumulated_content

            print(f"[LIVE TEST] Streaming roundtrip successful! Content length: {len(accumulated_content)}")

    @pytest.mark.asyncio
    async def test_multi_turn_conversation(self):
        """Test: Multi-turn conversation -> Persist entire history -> Reload."""
        from src.llm.openai_backend import OpenAIBackend

        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "multiturn_test.jsonl"

            # Initialize backend
            config = get_llm_config()
            backend = OpenAIBackend(config)

            # Create store and writer
            store = MessageStore()
            writer = SessionWriter(file_path)
            await writer.open()
            writer.bind_to_store(store)

            session_id = "multiturn-test-session"

            # Turn 1: User asks a question
            user1 = Message.create_user(
                content="My name is Alice. What's my name?",
                session_id=session_id,
                parent_uuid=None,
                seq=store.next_seq()
            )
            store.add_message(user1)

            response1 = backend.generate(store.get_llm_context())
            print(f"\n[LIVE TEST] Turn 1 Response: {response1.content}")

            assistant1 = Message.create_assistant(
                content=response1.content,
                session_id=session_id,
                parent_uuid=user1.uuid,
                seq=store.next_seq()
            )
            store.add_message(assistant1)

            # Turn 2: Follow-up question testing context retention
            user2 = Message.create_user(
                content="What did I just tell you my name was?",
                session_id=session_id,
                parent_uuid=assistant1.uuid,
                seq=store.next_seq()
            )
            store.add_message(user2)

            response2 = backend.generate(store.get_llm_context())
            print(f"[LIVE TEST] Turn 2 Response: {response2.content}")

            assistant2 = Message.create_assistant(
                content=response2.content,
                session_id=session_id,
                parent_uuid=user2.uuid,
                seq=store.next_seq()
            )
            store.add_message(assistant2)

            # Wait for persistence
            await asyncio.sleep(0.2)
            await writer.close()

            # Reload and verify
            resumed_store = load_session(file_path)

            assert resumed_store.message_count == 4

            # Verify context was maintained (response should mention Alice)
            messages = resumed_store.get_ordered_messages()
            assert "alice" in messages[3].content.lower() or "Alice" in messages[3].content

            print(f"[LIVE TEST] Multi-turn roundtrip successful! Context retained across {resumed_store.message_count} messages")


class TestLiveSessionManager:
    """Live tests using SessionManager for full workflow."""

    @pytest.mark.asyncio
    async def test_full_session_workflow_live(self):
        """Test complete session workflow with real LLM."""
        from src.llm.openai_backend import OpenAIBackend

        with tempfile.TemporaryDirectory() as tmpdir:
            # Initialize
            manager = SessionManager(sessions_dir=tmpdir)
            config = get_llm_config()
            backend = OpenAIBackend(config)

            # Create session
            info = manager.create_session(slug="live-workflow-test")
            await manager.start_writer()

            print(f"\n[LIVE TEST] Created session: {info.session_id}")

            # Add user message
            user_msg = Message.create_user(
                content="Hello! Please respond with 'Hi there!'",
                session_id=info.session_id,
                parent_uuid=None,
                seq=manager.store.next_seq()
            )
            manager.store.add_message(user_msg)

            # Make LLM call
            response = backend.generate(manager.store.get_llm_context())
            print(f"[LIVE TEST] LLM Response: {response.content}")

            # Add assistant response
            assistant_msg = Message.create_assistant(
                content=response.content,
                session_id=info.session_id,
                parent_uuid=user_msg.uuid,
                seq=manager.store.next_seq()
            )
            manager.store.add_message(assistant_msg)

            # Wait and close
            await asyncio.sleep(0.2)
            await manager.close()

            # Resume session and verify
            manager2 = SessionManager(sessions_dir=tmpdir)
            resumed = manager2.resume_session(info.session_id)

            assert resumed.message_count == 2
            assert "hi" in manager2.store.get_ordered_messages()[1].content.lower()

            print(f"[LIVE TEST] Session workflow complete! Resumed with {resumed.message_count} messages")


class TestProviderTranslatorLive:
    """Live tests for provider translators with real API responses."""

    @pytest.mark.asyncio
    async def test_openai_raw_response_translation(self):
        """Test translating raw OpenAI API response."""
        from src.llm.openai_backend import OpenAIBackend

        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "provider_test.jsonl"

            # Initialize backend
            config = get_llm_config()
            backend = OpenAIBackend(config)

            # Make raw API call to get actual response structure
            response = backend.client.chat.completions.create(
                model=config.model_name,
                messages=[{"role": "user", "content": "Say 'test' and nothing else."}],
                max_tokens=10,
                temperature=0.0
            )

            # Convert to dict format (simulating what we'd get from API)
            raw_response = {
                "id": response.id,
                "model": response.model,
                "choices": [{
                    "message": {
                        "role": response.choices[0].message.role,
                        "content": response.choices[0].message.content,
                        "tool_calls": None
                    },
                    "finish_reason": response.choices[0].finish_reason
                }],
                "usage": {
                    "prompt_tokens": response.usage.prompt_tokens,
                    "completion_tokens": response.usage.completion_tokens
                } if response.usage else None
            }

            print(f"\n[LIVE TEST] Raw response: {raw_response}")

            # Use our translator
            msg = from_openai(raw_response, "test-session", None, 1)

            print(f"[LIVE TEST] Translated message: role={msg.role}, content={msg.content}")
            print(f"[LIVE TEST] Meta: model={msg.meta.model}, provider={msg.meta.provider}")

            # Verify translation
            assert msg.role == "assistant"
            assert msg.content is not None
            assert msg.meta.provider == "openai"
            assert msg.meta.model == response.model

            # Persist and reload
            store = MessageStore()
            store.add_message(msg)

            writer = SessionWriter(file_path)
            await writer.open()
            await writer.write_message(msg)
            await writer.close()

            # Reload
            resumed = load_session(file_path)
            loaded_msg = resumed.get_ordered_messages()[0]

            assert loaded_msg.content == msg.content
            assert loaded_msg.meta.provider == "openai"

            # Convert back to OpenAI format
            openai_format = to_openai([loaded_msg])
            assert openai_format[0]["role"] == "assistant"
            assert "meta" not in openai_format[0]  # Meta should be stripped

            print(f"[LIVE TEST] Provider translation roundtrip successful!")
