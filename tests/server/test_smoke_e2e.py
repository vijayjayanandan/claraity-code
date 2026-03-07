"""End-to-end smoke test for the WebSocket server.

This test:
1. Starts the AgentServer on a random port
2. Connects an aiohttp WebSocket client
3. Verifies session_info is received
4. Sends a simple chat message
5. Verifies streaming events arrive (stream_start, text_delta, stream_end)
6. Shuts down cleanly

Requires: A valid .clarity/config.yaml with LLM credentials.
Skip with: pytest -m "not e2e" to skip this test.
"""

import asyncio
import json
import pytest
import aiohttp

from src.server.app import AgentServer
from src.llm.config_loader import load_llm_config


async def _send_auth(ws, token: str) -> dict:
    """Send auth handshake and return the session_info response."""
    await ws.send_json({"type": "auth", "token": token})
    msg = await asyncio.wait_for(ws.receive_json(), timeout=5.0)
    return msg


@pytest.mark.integration
@pytest.mark.asyncio
async def test_server_health_check():
    """Test that the server starts and health endpoint works."""
    config = load_llm_config()
    agent_kwargs = {
        "model_name": config.model,
        "backend": config.backend_type,
        "base_url": config.base_url,
        "context_window": config.context_window,
        "api_key": config.api_key,
        "api_key_env": config.api_key_env,
        "permission_mode": "auto",
    }

    server = AgentServer(
        host="127.0.0.1",
        port=9121,  # Use non-default port to avoid conflicts
        agent_kwargs=agent_kwargs,
    )

    await server.start()
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get("http://127.0.0.1:9121/health") as resp:
                assert resp.status == 200
                data = await resp.json()
                assert data["status"] == "ok"
                # session_id intentionally removed from health for security (S22)
                assert "session_id" not in data
                assert data["has_active_connection"] is False
    finally:
        await server.stop()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_websocket_session_info():
    """Test that connecting via WebSocket receives session_info."""
    config = load_llm_config()
    agent_kwargs = {
        "model_name": config.model,
        "backend": config.backend_type,
        "base_url": config.base_url,
        "context_window": config.context_window,
        "api_key": config.api_key,
        "api_key_env": config.api_key_env,
        "permission_mode": "auto",
    }

    server = AgentServer(
        host="127.0.0.1",
        port=9122,
        agent_kwargs=agent_kwargs,
    )

    await server.start()
    try:
        token = server._auth_token
        async with aiohttp.ClientSession() as session:
            async with session.ws_connect("http://127.0.0.1:9122/ws") as ws:
                # Send auth handshake, receive session_info as response
                msg = await _send_auth(ws, token)
                assert msg["type"] == "session_info"
                assert "session_id" in msg
                assert msg["model_name"] == config.model
                print(f"[OK] session_info received: {msg}")

                await ws.close()
    finally:
        await server.stop()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_websocket_chat_roundtrip():
    """Test full chat round-trip: send message, receive streaming events."""
    config = load_llm_config()
    agent_kwargs = {
        "model_name": config.model,
        "backend": config.backend_type,
        "base_url": config.base_url,
        "context_window": config.context_window,
        "api_key": config.api_key,
        "api_key_env": config.api_key_env,
        "permission_mode": "auto",
    }

    server = AgentServer(
        host="127.0.0.1",
        port=9123,
        agent_kwargs=agent_kwargs,
    )

    await server.start()
    try:
        async with aiohttp.ClientSession() as session:
            async with session.ws_connect("http://127.0.0.1:9123/ws") as ws:
                # Auth handshake -> session_info
                msg = await _send_auth(ws, server._auth_token)
                assert msg["type"] == "session_info"

                # Send a simple chat message
                await ws.send_json({
                    "type": "chat_message",
                    "content": "Say hello in exactly 3 words.",
                })

                # Collect events until stream_end
                events = []
                event_types = set()
                try:
                    while True:
                        msg = await asyncio.wait_for(ws.receive_json(), timeout=30.0)
                        events.append(msg)
                        event_types.add(msg.get("type", "unknown"))
                        print(f"  Event: {msg.get('type')}")

                        if msg.get("type") == "stream_end":
                            break
                except asyncio.TimeoutError:
                    pytest.fail(f"Timed out waiting for stream_end. Got events: {event_types}")

                # Verify we got the expected event types
                assert "stream_start" in event_types, f"Missing stream_start. Got: {event_types}"
                assert "stream_end" in event_types, f"Missing stream_end. Got: {event_types}"

                # Should have received some text content
                text_events = [e for e in events if e.get("type") == "text_delta"]
                assert len(text_events) > 0, "No text_delta events received"

                full_text = "".join(e["content"] for e in text_events)
                print(f"\n[OK] Agent response: {full_text[:200]}")
                print(f"[OK] Event types: {event_types}")
                print(f"[OK] Total events: {len(events)}")

                await ws.close()
    finally:
        await server.stop()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_websocket_auto_approve_roundtrip():
    """Test set_auto_approve -> auto_approve_changed round-trip."""
    config = load_llm_config()
    agent_kwargs = {
        "model_name": config.model,
        "backend": config.backend_type,
        "base_url": config.base_url,
        "context_window": config.context_window,
        "api_key": config.api_key,
        "api_key_env": config.api_key_env,
        "permission_mode": "auto",
    }

    server = AgentServer(
        host="127.0.0.1",
        port=9124,
        agent_kwargs=agent_kwargs,
    )

    await server.start()
    try:
        async with aiohttp.ClientSession() as session:
            async with session.ws_connect("http://127.0.0.1:9124/ws") as ws:
                # Auth handshake -> session_info (includes default categories)
                msg = await _send_auth(ws, server._auth_token)
                assert msg["type"] == "session_info"
                assert msg["auto_approve_categories"] == {
                    "browser": False, "edit": False, "execute": False,
                }

                # Set edit=True, verify confirmed state
                await ws.send_json({
                    "type": "set_auto_approve",
                    "categories": {"edit": True},
                })
                msg = await asyncio.wait_for(ws.receive_json(), timeout=5.0)
                assert msg["type"] == "auto_approve_changed"
                assert msg["categories"]["edit"] is True
                assert msg["categories"]["execute"] is False

                # Query current state
                await ws.send_json({"type": "get_auto_approve"})
                msg = await asyncio.wait_for(ws.receive_json(), timeout=5.0)
                assert msg["type"] == "auto_approve_changed"
                assert msg["categories"]["edit"] is True

                await ws.close()
    finally:
        await server.stop()
