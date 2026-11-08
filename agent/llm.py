"""
agent/llm.py
────────────────────────────────────────────────────────────────────────────────
Resilient Groq LLM Client for LedgerMind Resolution Agent.

Configured with:
  - Model: openai/gpt-oss-120b
  - Temperature: 0.0 (deterministic)
  - Response Format: JSON object
  - Tenacity backoff retries for 429 rate limits and transient connection drops.
"""

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import groq as groq_sdk
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

ROOT_DIR = Path(__file__).resolve().parent.parent

# Load environment
try:
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=ROOT_DIR / ".env")
except Exception:
    pass


class LLMError(RuntimeError):
    """Raised when the LLM service fails to generate a valid response."""
    pass


class GroqClient:
    """Wrapper around Groq API with robust retries, JSON enforcement, and token tracking."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
    ) -> None:
        self.api_key = api_key or os.getenv("GROQ_API_KEY", "")
        self.model = model or os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
        self.client = groq_sdk.Groq(api_key=self.api_key) if self.api_key else None

        self.last_prompt_tokens = 0
        self.last_completion_tokens = 0
        self.last_total_tokens = 0

    @retry(
        retry=retry_if_exception_type((groq_sdk.RateLimitError, groq_sdk.APIConnectionError, groq_sdk.InternalServerError)),
        wait=wait_exponential(multiplier=2, min=3, max=30),
        stop=stop_after_attempt(5),
        reraise=True,
    )
    def call_json(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.0,
        max_tokens: int = 1536,
    ) -> Tuple[Dict[str, Any], Dict[str, int]]:
        """
        Invoke Groq LLM enforcing JSON output.

        Returns:
            Tuple of (parsed_json_dict, usage_dict)
        """
        if not self.client:
            raise LLMError("Groq client cannot be initialized without a valid GROQ_API_KEY.")

        try:
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                response_format={"type": "json_object"},
            )

            # Record usage
            usage = resp.usage
            self.last_prompt_tokens = usage.prompt_tokens if usage else 0
            self.last_completion_tokens = usage.completion_tokens if usage else 0
            self.last_total_tokens = usage.total_tokens if usage else 0

            usage_dict = {
                "prompt_tokens": self.last_prompt_tokens,
                "completion_tokens": self.last_completion_tokens,
                "total_tokens": self.last_total_tokens,
            }

            raw_content = resp.choices[0].message.content or "{}"
            parsed = json.loads(raw_content)
            return parsed, usage_dict

        except groq_sdk.RateLimitError as e:
            err_str = str(e).lower()
            if ("tpd" in err_str or "tokens per day" in err_str) and self.model != "openai/gpt-oss-20b":
                print(f"⚠️  Groq TPD daily limit hit on {self.model}; failing over to openai/gpt-oss-20b...")
                resp = self.client.chat.completions.create(
                    model="openai/gpt-oss-20b",
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    response_format={"type": "json_object"},
                )
                usage = resp.usage
                usage_dict = {
                    "prompt_tokens": usage.prompt_tokens if usage else 0,
                    "completion_tokens": usage.completion_tokens if usage else 0,
                    "total_tokens": usage.total_tokens if usage else 0,
                }
                raw_content = resp.choices[0].message.content or "{}"
                parsed = json.loads(raw_content)
                return parsed, usage_dict
            raise LLMError(f"Groq API call failed: {e}")
        except json.JSONDecodeError as e:
            raise LLMError(f"LLM produced invalid JSON response: {e}")
        except Exception as e:
            raise LLMError(f"Groq API call failed: {e}")
