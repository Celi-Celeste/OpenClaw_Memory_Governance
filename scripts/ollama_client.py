#!/usr/bin/env python3
"""Ollama API client for memory governance thinking jobs.

This module provides a clean interface to Ollama's API for complex reasoning tasks,
separate from LM Studio which handles standard inference.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Configuration
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
DEFAULT_MODEL = "qwen3:4b-thinking"
MAX_RETRIES = 3
RETRY_DELAY = 2  # seconds
TIMEOUT = 120  # seconds


class OllamaError(Exception):
    """Raised when Ollama API calls fail."""
    pass


class ModelNotLoadedError(OllamaError):
    """Raised when the requested model is not available."""
    pass


def _make_request(
    endpoint: str,
    data: Dict,
    timeout: int = TIMEOUT
) -> Dict:
    """Make a POST request to Ollama API with retries."""
    url = f"{OLLAMA_HOST}/api/{endpoint}"
    headers = {"Content-Type": "application/json"}
    body = json.dumps(data).encode("utf-8")
    
    last_error = None
    for attempt in range(MAX_RETRIES):
        try:
            req = urllib.request.Request(
                url,
                data=body,
                headers=headers,
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=timeout) as response:
                return json.loads(response.read().decode())
        except urllib.error.HTTPError as e:
            last_error = f"HTTP {e.code}: {e.reason}"
            if e.code == 404:
                raise ModelNotLoadedError(f"Model not found: {data.get('model')}")
            time.sleep(RETRY_DELAY)
        except urllib.error.URLError as e:
            last_error = f"Connection error: {e.reason}"
            time.sleep(RETRY_DELAY)
        except Exception as e:
            last_error = str(e)
            time.sleep(RETRY_DELAY)
    
    raise OllamaError(f"Failed after {MAX_RETRIES} attempts: {last_error}")


def list_models() -> List[str]:
    """List available models in Ollama."""
    try:
        url = f"{OLLAMA_HOST}/api/tags"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode())
            return [m["name"] for m in data.get("models", [])]
    except Exception as e:
        raise OllamaError(f"Failed to list models: {e}")


def verify_model_loaded(model: str = DEFAULT_MODEL) -> bool:
    """Check if a model is available in Ollama."""
    try:
        models = list_models()
        return any(model in m for m in models)
    except Exception:
        return False


def load_model(model: str = DEFAULT_MODEL, timeout: int = 300) -> None:
    """Ensure a model is loaded in Ollama."""
    if verify_model_loaded(model):
        return
    
    # Try to pull/load the model
    try:
        result = subprocess.run(
            ["ollama", "pull", model],
            capture_output=True,
            text=True,
            timeout=timeout
        )
        if result.returncode != 0:
            raise OllamaError(f"Failed to load model: {result.stderr}")
    except subprocess.TimeoutExpired:
        raise OllamaError(f"Timeout loading model after {timeout}s")
    except FileNotFoundError:
        raise OllamaError("ollama command not found in PATH")


def chat_completion(
    prompt: str,
    model: str = DEFAULT_MODEL,
    system: Optional[str] = None,
    temperature: float = 0.7,
    max_tokens: int = 2000,
    timeout: int = TIMEOUT
) -> str:
    """Generate completion using Ollama chat API.
    
    Args:
        prompt: The user prompt
        model: Model name to use
        system: Optional system prompt
        temperature: Sampling temperature
        max_tokens: Maximum tokens to generate
        timeout: Request timeout
        
    Returns:
        Generated text response
        
    Raises:
        ModelNotLoadedError: If model not available
        OllamaError: On API failures
    """
    # Ensure model is loaded
    if not verify_model_loaded(model):
        raise ModelNotLoadedError(
            f"Model '{model}' not loaded in Ollama. "
            f"Available: {list_models()}"
        )
    
    # Build messages
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    
    # Make request
    data = {
        "model": model,
        "messages": messages,
        "stream": False,
        "options": {
            "temperature": temperature,
            "num_predict": max_tokens
        }
    }
    
    response = _make_request("chat", data, timeout)
    
    # Extract response text
    message = response.get("message", {})
    content = message.get("content", "").strip()
    
    if not content:
        raise OllamaError("Empty response from model")
    
    return content


def generate(
    prompt: str,
    model: str = DEFAULT_MODEL,
    system: Optional[str] = None,
    temperature: float = 0.7,
    max_tokens: int = 2000
) -> str:
    """Generate completion using Ollama generate API (simpler interface).
    
    This is an alternative to chat_completion for non-conversational tasks.
    """
    if not verify_model_loaded(model):
        raise ModelNotLoadedError(f"Model '{model}' not loaded")
    
    data = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": temperature,
            "num_predict": max_tokens
        }
    }
    
    if system:
        data["system"] = system
    
    response = _make_request("generate", data)
    return response.get("response", "").strip()


def main():
    """CLI test interface."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Test Ollama client")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--prompt", default="Say 'Ollama is working'")
    args = parser.parse_args()
    
    print(f"Testing Ollama with model: {args.model}")
    print(f"Available models: {list_models()}")
    
    try:
        result = chat_completion(args.prompt, model=args.model)
        print(f"Success: {result}")
    except Exception as e:
        print(f"Error: {e}")
        return 1
    
    return 0


if __name__ == "__main__":
    exit(main())
