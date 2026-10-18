"""
QuantaSHI - Central AI Agent Client & OpenRouter Gateway.
Provides unified LLM connectivity for the specialized AI agents in
user_interface, server_interface, and system_interface.
"""

from __future__ import annotations
import os
import json
import logging
from typing import Dict, List, Optional, Any
import requests

logger = logging.getLogger("QuantaSHI.AIAgent")

# Load environment variable or local .env file safely
def _load_env_key() -> str:
    key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not key:
        env_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
        if os.path.exists(env_file):
            try:
                with open(env_file, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith("OPENROUTER_API_KEY="):
                            key = line.split("=", 1)[1].strip().strip('"').strip("'")
                            break
            except Exception:
                pass
    return key

OPENROUTER_API_KEY = _load_env_key()
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "openai/gpt-4o-mini"


def call_llm(
    messages: List[Dict[str, str]],
    model: str = DEFAULT_MODEL,
    temperature: float = 0.7,
    max_tokens: int = 500,
    json_mode: bool = False,
    timeout_sec: float = 12.0,
) -> Dict[str, Any]:
    """
    Sends a chat completion request to OpenRouter.
    Includes automatic error handling and fallback for robustness.
    """
    if not OPENROUTER_API_KEY or OPENROUTER_API_KEY.startswith("sk-placeholder"):
        logger.warning("No valid OpenRouter API key found. Falling back to agent deterministic engine.")
        return {"success": False, "error": "MISSING_API_KEY", "content": None}

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/QuantaSHI",
        "X-Title": "QuantaSHI Autonomous AI Agents",
    }

    payload: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    if json_mode:
        payload["response_format"] = {"type": "json_object"}

    try:
        response = requests.post(
            OPENROUTER_BASE_URL,
            headers=headers,
            json=payload,
            timeout=timeout_sec,
        )

        if response.status_code == 200:
            data = response.json()
            content = data["choices"][0]["message"]["content"]
            return {
                "success": True,
                "content": content,
                "model": data.get("model", model),
                "usage": data.get("usage", {}),
            }
        else:
            logger.warning(f"OpenRouter returned status {response.status_code}: {response.text[:120]}")
            return {
                "success": False,
                "error": f"HTTP_{response.status_code}",
                "detail": response.text[:200],
                "content": None,
            }
    except requests.exceptions.RequestException as e:
        logger.warning(f"OpenRouter request failed: {e}")
        return {
            "success": False,
            "error": "NETWORK_EXCEPTION",
            "detail": str(e),
            "content": None,
        }
