# LLM Contradiction Client

## Overview

The `LLMContradictionClient` provides LLM-based classification of relationships between memory entries. It uses Ollama's chat API to classify pairs of memories into one of four categories:

- **REINFORCES**: Second memory supports/validates first
- **REFINES**: Second adds detail without contradiction
- **SUPERSEDES**: Second contradicts/replaces first
- **UNRELATED**: No meaningful relationship

## Installation

No additional installation required. The client uses standard library modules and requires Ollama to be running locally.

## Usage

```python
from llm_contradiction_client import LLMContradictionClient

# Initialize client
client = LLMContradictionClient(model="qwen3:4b", timeout=120)

# Classify a pair of memories
memory_a = {
    "entry_id": "mem-old",
    "meta": {
        "time": "2024-01-15T10:00:00Z",
        "importance": 0.8,
        "tags": ["decision", "python"]
    },
    "body": "Project uses Python 3.9"
}

memory_b = {
    "entry_id": "mem-new",
    "meta": {
        "time": "2024-03-01T14:00:00Z",
        "importance": 0.9,
        "tags": ["decision", "python"]
    },
    "body": "Migrated to Python 3.11"
}

result = client.classify_pair(memory_a, memory_b)
print(result)
# {
#   "relationship": "SUPERSEDES",
#   "confidence": 0.95,
#   "reasoning": "Migration makes Python 3.9 obsolete",
#   "cached": False
# }
```

## API Reference

### `LLMContradictionClient`

#### `__init__(model="qwen3:4b", timeout=120)`
Initialize the client.

- `model`: Ollama model name to use
- `timeout`: Request timeout in seconds

#### `classify_pair(memory_a, memory_b) -> Dict`
Classify the relationship between two memory entries.

**Parameters:**
- `memory_a`: First memory entry dict with `entry_id`, `meta`, and `body` keys
- `memory_b`: Second memory entry dict with `entry_id`, `meta`, and `body` keys

**Returns:**
```python
{
    "relationship": "REINFORCES|REFINES|SUPERSEDES|UNRELATED",
    "confidence": 0.0-1.0,
    "reasoning": "explanation string",
    "cached": True|False
}
```

**Raises:**
- `LLMUnavailableError`: If Ollama is unreachable
- `LLMContradictionError`: On other failures after retries

#### `get_cache_stats() -> Dict`
Get cache statistics.

Returns:
```python
{
    "cache_hits": int,
    "cache_misses": int,
    "cache_size": int
}
```

#### `clear_cache()`
Clear the classification cache.

## Error Handling

The client handles several error conditions:

1. **Timeout**: Retries once after 1 second delay
2. **JSON Parse Error**: Falls back to UNRELATED with low confidence (0.3)
3. **LLM Unavailable**: Raises `LLMUnavailableError` for caller to handle
4. **Invalid Relationship**: Normalizes to UNRELATED

## Caching

Results are cached to avoid re-classifying the same pair. The cache key is a hash of the sorted entry IDs, making it order-independent.

## Testing

Run the built-in test suite:

```bash
python3 llm_contradiction_client.py
```

This runs 10 test cases (5 contradictions, 5 non-contradictions) and validates:
- Correct classification of SUPERSEDES relationships
- Correct classification of REINFORCES relationships
- Correct classification of REFINES relationships
- Correct classification of UNRELATED relationships
- Cache functionality
- Confidence scores within valid range (0.0-1.0)

## Requirements

- Ollama running locally (default: http://localhost:11434)
- qwen3:4b model (or compatible) installed in Ollama
- Python 3.8+

## Configuration

Environment variables:
- `OLLAMA_HOST`: Ollama API endpoint (default: http://localhost:11434)
