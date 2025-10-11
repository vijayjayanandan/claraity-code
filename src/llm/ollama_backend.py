"""Ollama backend implementation."""

import json
import requests
from typing import List, Dict, Any, Iterator, Optional
import tiktoken

from .base import LLMBackend, LLMConfig, LLMResponse, StreamChunk


class OllamaBackend(LLMBackend):
    """Ollama backend for local LLM inference."""

    def __init__(self, config: LLMConfig):
        """
        Initialize Ollama backend.

        Args:
            config: LLM configuration
        """
        super().__init__(config)
        self.api_url = f"{config.base_url}/api"

        # Token counter (fallback, Ollama doesn't provide exact counts)
        try:
            self.encoding = tiktoken.get_encoding("cl100k_base")
        except:
            self.encoding = None

    def generate(
        self,
        messages: List[Dict[str, str]],
        **kwargs: Any
    ) -> LLMResponse:
        """Generate completion from messages."""
        self.validate_messages(messages)

        # Prepare request
        payload = {
            "model": self.config.model_name,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": kwargs.get("temperature", self.config.temperature),
                "top_p": kwargs.get("top_p", self.config.top_p),
                "top_k": kwargs.get("top_k", self.config.top_k),
                "repeat_penalty": kwargs.get("repeat_penalty", self.config.repeat_penalty),
            }
        }

        if self.config.num_ctx:
            payload["options"]["num_ctx"] = self.config.num_ctx

        if kwargs.get("max_tokens") or self.config.max_tokens:
            payload["options"]["num_predict"] = kwargs.get("max_tokens", self.config.max_tokens)

        try:
            response = requests.post(
                f"{self.api_url}/chat",
                json=payload,
                timeout=self.config.timeout
            )
            response.raise_for_status()

            data = response.json()

            # Extract content
            content = data.get("message", {}).get("content", "")

            # Calculate token counts (approximate)
            prompt_text = self._messages_to_text(messages)
            prompt_tokens = self.count_tokens(prompt_text)
            completion_tokens = self.count_tokens(content)

            return LLMResponse(
                content=content,
                model=data.get("model", self.config.model_name),
                finish_reason=data.get("done_reason"),
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=prompt_tokens + completion_tokens,
                eval_duration=data.get("total_duration", 0) / 1e9,  # Convert to seconds
                raw_response=data
            )

        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"Ollama API error: {e}")

    def generate_stream(
        self,
        messages: List[Dict[str, str]],
        **kwargs: Any
    ) -> Iterator[StreamChunk]:
        """Generate streaming completion."""
        self.validate_messages(messages)

        payload = {
            "model": self.config.model_name,
            "messages": messages,
            "stream": True,
            "options": {
                "temperature": kwargs.get("temperature", self.config.temperature),
                "top_p": kwargs.get("top_p", self.config.top_p),
                "top_k": kwargs.get("top_k", self.config.top_k),
            }
        }

        if self.config.num_ctx:
            payload["options"]["num_ctx"] = self.config.num_ctx

        try:
            response = requests.post(
                f"{self.api_url}/chat",
                json=payload,
                stream=True,
                timeout=self.config.timeout
            )
            response.raise_for_status()

            for line in response.iter_lines():
                if line:
                    data = json.loads(line)

                    content = data.get("message", {}).get("content", "")
                    done = data.get("done", False)

                    yield StreamChunk(
                        content=content,
                        done=done,
                        model=data.get("model"),
                        finish_reason=data.get("done_reason") if done else None
                    )

                    if done:
                        break

        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"Ollama streaming error: {e}")

    def count_tokens(self, text: str) -> int:
        """Count tokens in text (approximate)."""
        if self.encoding:
            return len(self.encoding.encode(text))
        else:
            # Fallback: rough approximation
            return len(text.split()) * 1.3

    def is_available(self) -> bool:
        """Check if Ollama is available."""
        try:
            response = requests.get(
                f"{self.api_url}/tags",
                timeout=5.0
            )
            return response.status_code == 200
        except:
            return False

    def list_models(self) -> List[str]:
        """List available models in Ollama."""
        try:
            response = requests.get(
                f"{self.api_url}/tags",
                timeout=5.0
            )
            response.raise_for_status()

            data = response.json()
            models = data.get("models", [])

            return [model.get("name") for model in models]

        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"Failed to list models: {e}")

    def pull_model(self, model_name: str) -> None:
        """
        Pull a model from Ollama library.

        Args:
            model_name: Name of model to pull
        """
        try:
            response = requests.post(
                f"{self.api_url}/pull",
                json={"name": model_name},
                stream=True,
                timeout=600.0  # 10 minutes for download
            )
            response.raise_for_status()

            # Stream progress
            for line in response.iter_lines():
                if line:
                    data = json.loads(line)
                    status = data.get("status", "")
                    print(f"Pulling {model_name}: {status}")

                    if data.get("status") == "success":
                        break

        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"Failed to pull model: {e}")

    def _messages_to_text(self, messages: List[Dict[str, str]]) -> str:
        """Convert messages to text for token counting."""
        return "\n".join([f"{m['role']}: {m['content']}" for m in messages])
