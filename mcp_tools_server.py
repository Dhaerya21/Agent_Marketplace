"""
=============================================================================
  MCP Server — AI Agent Marketplace Tools
=============================================================================

  Exposes the marketplace's 3 AI tools as MCP (Model Context Protocol)
  tools so any MCP-compatible client (Claude Desktop, Cursor, etc.)
  can use them directly.

  Tools:
    1. summarize_text    — Condense text into a clear summary
    2. extract_entities  — Extract people, places, topics, keywords
    3. rewrite_content   — Rewrite text in a different tone/style

  ==========================================================================
  HOW TO RUN
  ==========================================================================

  1. Install the MCP SDK:
         pip install "mcp[cli]"

  2. Make sure Ollama is running:
         ollama serve

  3. Start this MCP server:
         python mcp_tools_server.py

     This starts the server on SSE transport at http://localhost:8090/sse

  ==========================================================================
  HOW TO CONNECT
  ==========================================================================

  Option A: Claude Desktop / Cursor / Windsurf
  -----------------------------------------------
  Add this to your MCP settings config:

    {
      "mcpServers": {
        "agent-marketplace-tools": {
          "url": "http://localhost:8090/sse"
        }
      }
    }

  Option B: Python MCP Client
  -----------------------------------------------
    from mcp import ClientSession
    from mcp.client.sse import sse_client

    async with sse_client("http://localhost:8090/sse") as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # List available tools
            tools = await session.list_tools()
            for t in tools.tools:
                print(f"  {t.name}: {t.description}")

            # Call a tool
            result = await session.call_tool("summarize_text", {
                "text": "Your long text here...",
                "length": "brief"
            })
            print(result)

  ==========================================================================
"""

import sys
import subprocess
import json
import time
import re
import requests

# -- Auto-install dependencies -----------------------------------------------
def _ensure(pkg, import_name=None):
    import importlib
    try:
        importlib.import_module(import_name or pkg)
    except ImportError:
        print(f"[setup] Installing {pkg} ...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", pkg, "-q"])

_ensure("mcp", "mcp")

from mcp.server.fastmcp import FastMCP

# ==============================================================================
# CONFIG — Internal only, never exposed to MCP clients
# ==============================================================================
_OLLAMA_URL = "http://localhost:11434/api/generate"
_LLM_MODEL = "qwen2.5:7b"
_MAX_INPUT_LENGTH = 8000

# ==============================================================================
# MCP SERVER INSTANCE
# ==============================================================================
mcp = FastMCP(
    "Agent Marketplace Tools",
    version="1.0.0",
)


# ==============================================================================
# INTERNAL HELPERS (hidden from MCP clients)
# ==============================================================================
def _call_llm(prompt: str) -> tuple:
    """Call the local LLM. Returns (response_text, latency_sec, error)."""
    try:
        t0 = time.time()
        resp = requests.post(_OLLAMA_URL, json={
            "model": _LLM_MODEL,
            "prompt": prompt,
            "stream": False,
        }, timeout=120)
        latency = round(time.time() - t0, 2)
        resp.raise_for_status()
        text = resp.json().get("response", "").strip()
        return text, latency, None
    except requests.ConnectionError:
        return None, 0, "AI service unavailable. Make sure Ollama is running: ollama serve"
    except requests.Timeout:
        return None, 0, "Request timed out. Try shorter input."
    except Exception:
        return None, 0, "An internal error occurred."


def _extract_json(raw_text: str):
    """Extract JSON from LLM output, handling code fences."""
    match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", raw_text, re.DOTALL)
    if match:
        raw_text = match.group(1).strip()
    start = raw_text.find("{")
    end = raw_text.rfind("}") + 1
    if start >= 0 and end > start:
        try:
            return json.loads(raw_text[start:end])
        except json.JSONDecodeError:
            pass
    return None


# ==============================================================================
# MCP TOOL: SUMMARIZE TEXT
# ==============================================================================
@mcp.tool()
def summarize_text(text: str, length: str = "standard") -> str:
    """Condense any text into a clear, structured summary with key bullet points.

    Args:
        text: The text to summarize (max 8000 characters)
        length: Summary length — "brief" (2-3 sentences), "standard" (4-6 sentences), or "detailed" (8-12 sentences)

    Returns:
        JSON string with summary, key_points, and word count stats
    """
    if not text or len(text.strip()) < 10:
        return json.dumps({"error": "Input too short. Provide at least 10 characters."})
    if len(text) > _MAX_INPUT_LENGTH:
        return json.dumps({"error": f"Input too long. Max {_MAX_INPUT_LENGTH} characters."})
    if length not in ("brief", "standard", "detailed"):
        length = "standard"

    length_instructions = {
        "brief": "Write a very concise summary in 2-3 sentences.",
        "standard": "Write a clear summary in 4-6 sentences covering all main points.",
        "detailed": "Write a comprehensive summary in 8-12 sentences with important details.",
    }

    prompt = (
        "You are an expert summarizer. Summarize the following text.\n\n"
        f"Length: {length_instructions[length]}\n\n"
        "Output MUST be valid JSON:\n"
        '{"summary": "<text>", "key_points": ["<point>", ...], '
        '"word_count_original": <int>, "word_count_summary": <int>}\n\n'
        f"Text:\n{text}\n\nSummary (JSON):\n"
    )

    raw, latency, error = _call_llm(prompt)
    if error:
        return json.dumps({"error": error})

    result = _extract_json(raw)
    if not result:
        result = {"summary": raw[:1000], "key_points": []}

    return json.dumps({
        "summary": result.get("summary", raw[:500]),
        "key_points": result.get("key_points", [])[:8],
        "stats": {
            "original_words": result.get("word_count_original", len(text.split())),
            "summary_words": result.get("word_count_summary", len(result.get("summary", "").split())),
        },
        "processing_time_sec": latency,
    }, indent=2)


# ==============================================================================
# MCP TOOL: EXTRACT ENTITIES
# ==============================================================================
@mcp.tool()
def extract_entities(text: str) -> str:
    """Extract named entities (people, organizations, locations, dates), keywords, and topics from any text.

    Args:
        text: The text to analyze (max 8000 characters)

    Returns:
        JSON string with entities, keywords, topics, category, and language
    """
    if not text or len(text.strip()) < 10:
        return json.dumps({"error": "Input too short. Provide at least 10 characters."})
    if len(text) > _MAX_INPUT_LENGTH:
        return json.dumps({"error": f"Input too long. Max {_MAX_INPUT_LENGTH} characters."})

    prompt = (
        "You are an expert NLP analyst. Extract entities and keywords.\n\n"
        "Output MUST be valid JSON:\n"
        '{"entities": {"people": [...], "organizations": [...], "locations": [...], "dates": [...]}, '
        '"keywords": [...], "topics": [...], "category": "<text>", "language": "<text>"}\n\n'
        f"Text:\n{text}\n\nExtraction (JSON):\n"
    )

    raw, latency, error = _call_llm(prompt)
    if error:
        return json.dumps({"error": error})

    result = _extract_json(raw)
    if not result:
        result = {"entities": {}, "keywords": [], "topics": [], "category": "Unknown"}

    entities = result.get("entities", {})
    return json.dumps({
        "entities": {
            "people": entities.get("people", [])[:20],
            "organizations": entities.get("organizations", [])[:20],
            "locations": entities.get("locations", [])[:20],
            "dates": entities.get("dates", [])[:10],
        },
        "keywords": result.get("keywords", [])[:15],
        "topics": result.get("topics", [])[:5],
        "category": result.get("category", "Unknown"),
        "language": result.get("language", "English"),
        "processing_time_sec": latency,
    }, indent=2)


# ==============================================================================
# MCP TOOL: REWRITE CONTENT
# ==============================================================================
@mcp.tool()
def rewrite_content(text: str, tone: str = "professional") -> str:
    """Rewrite text in a different tone/style while preserving the core meaning.

    Args:
        text: The text to rewrite (max 8000 characters)
        tone: Target tone — "professional", "casual", "technical", "academic", or "creative"

    Returns:
        JSON string with rewritten_text, changes_made, and word count stats
    """
    if not text or len(text.strip()) < 10:
        return json.dumps({"error": "Input too short. Provide at least 10 characters."})
    if len(text) > _MAX_INPUT_LENGTH:
        return json.dumps({"error": f"Input too long. Max {_MAX_INPUT_LENGTH} characters."})
    if tone not in ("professional", "casual", "technical", "academic", "creative"):
        tone = "professional"

    tone_map = {
        "professional": "polished, professional business tone with formal language",
        "casual": "friendly, casual conversational tone with everyday language",
        "technical": "precise, technical tone with domain-specific terminology",
        "academic": "formal academic tone with scholarly language",
        "creative": "creative, engaging tone with vivid language and metaphors",
    }

    prompt = (
        f"Rewrite this text in a {tone} tone ({tone_map[tone]}).\n\n"
        "Output MUST be valid JSON:\n"
        '{"rewritten_text": "<text>", "changes_made": ["<change>", ...], "tone_achieved": "<tone>"}\n\n'
        "Rules: Preserve meaning. Do NOT add new information.\n\n"
        f"Original:\n{text}\n\nRewritten (JSON):\n"
    )

    raw, latency, error = _call_llm(prompt)
    if error:
        return json.dumps({"error": error})

    result = _extract_json(raw)
    if not result:
        result = {"rewritten_text": raw[:2000], "changes_made": [], "tone_achieved": tone}

    return json.dumps({
        "rewritten_text": result.get("rewritten_text", raw[:2000]),
        "changes_made": result.get("changes_made", [])[:8],
        "tone": result.get("tone_achieved", tone),
        "stats": {
            "original_words": len(text.split()),
            "rewritten_words": len(result.get("rewritten_text", "").split()),
        },
        "processing_time_sec": latency,
    }, indent=2)


# ==============================================================================
# MAIN — Start the MCP server
# ==============================================================================
if __name__ == "__main__":
    port = 8090

    print(f"\n{'=' * 60}")
    print(f"  MCP Tools Server — Agent Marketplace")
    print(f"{'=' * 60}")
    print(f"  Transport : SSE (Server-Sent Events)")
    print(f"  URL       : http://localhost:{port}/sse")
    print(f"  Tools     : 3")
    print(f"    1. summarize_text    — Condense text into summary")
    print(f"    2. extract_entities  — Extract people, places, keywords")
    print(f"    3. rewrite_content   — Rewrite in different tone")
    print(f"{'=' * 60}")
    print(f"\n  Connect from Claude Desktop / Cursor / any MCP client:")
    print(f'  {{"url": "http://localhost:{port}/sse"}}')
    print(f"\n  Or test with:  mcp dev mcp_tools_server.py")
    print(f"{'=' * 60}\n")

    mcp.run(transport="sse", host="0.0.0.0", port=port)
