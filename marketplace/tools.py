"""
Hosted Tools Engine
====================
Three secure, server-side AI tools powered by the local Ollama LLM.
Users interact through the marketplace UI — no internal details are exposed.

Tools:
  1. Smart Summarizer    — Condense any text into a clear summary
  2. Entity Extractor    — Extract people, places, topics, keywords
  3. Content Rewriter    — Rewrite text in a different tone/style

Security:
  - All tool endpoints require JWT authentication
  - No model names, endpoints, or internals are exposed to users
  - Per-user rate limiting (configurable)
  - Input validation and sanitization
"""

import time
import json
import re
import requests
from datetime import datetime, timezone

# ==============================================================================
# CONFIG — Internal only, never exposed to users
# ==============================================================================
_OLLAMA_URL = "http://localhost:11434/api/generate"
_LLM_MODEL = "qwen2.5:7b"
_MAX_INPUT_LENGTH = 8000       # chars
_RATE_LIMIT_PER_MIN = 10       # max calls per user per minute

# Per-user rate tracking (in-memory, resets on restart)
_user_calls = {}  # user_id -> [(timestamp, tool_id), ...]


# ==============================================================================
# TOOL REGISTRY
# ==============================================================================
TOOLS = {
    "summarizer": {
        "id": "summarizer",
        "name": "Smart Summarizer",
        "tagline": "Condense any text into a clear, concise summary",
        "description": (
            "Paste any long document, article, research paper, or text and get "
            "a well-structured summary with key points highlighted. Supports "
            "adjustable summary length (brief, standard, detailed)."
        ),
        "icon": "📝",
        "color": "#00d4ff",
        "category": "Writing",
        "input_placeholder": "Paste the text you want to summarize...",
        "options": [
            {"id": "length", "label": "Summary Length", "type": "select",
             "choices": ["brief", "standard", "detailed"], "default": "standard"},
        ],
    },
    "extractor": {
        "id": "extractor",
        "name": "Entity & Keyword Extractor",
        "tagline": "Extract people, places, topics, and keywords from text",
        "description": (
            "Analyzes any text and extracts structured data: named entities "
            "(people, organizations, locations), key topics, important keywords, "
            "and a topic classification. Great for content tagging and analysis."
        ),
        "icon": "🔍",
        "color": "#a855f7",
        "category": "Analysis",
        "input_placeholder": "Paste the text to extract entities and keywords from...",
        "options": [],
    },
    "rewriter": {
        "id": "rewriter",
        "name": "Content Rewriter",
        "tagline": "Rewrite text in a different tone or style",
        "description": (
            "Transform any text into a different writing style while preserving "
            "the core meaning. Choose from professional, casual, technical, "
            "academic, or creative tones. Perfect for adapting content "
            "for different audiences."
        ),
        "icon": "✨",
        "color": "#00ff88",
        "category": "Writing",
        "input_placeholder": "Paste the text you want to rewrite...",
        "options": [
            {"id": "tone", "label": "Target Tone", "type": "select",
             "choices": ["professional", "casual", "technical", "academic", "creative"],
             "default": "professional"},
        ],
    },
}


def get_tools_public():
    """Return tool info safe for public display (no internals)."""
    return [
        {
            "id": t["id"],
            "name": t["name"],
            "tagline": t["tagline"],
            "description": t["description"],
            "icon": t["icon"],
            "color": t["color"],
            "category": t["category"],
            "input_placeholder": t["input_placeholder"],
            "options": t["options"],
        }
        for t in TOOLS.values()
    ]


# ==============================================================================
# RATE LIMITING
# ==============================================================================
def _check_rate_limit(user_id):
    """Check if user has exceeded rate limit. Returns (allowed, message)."""
    now = time.time()
    window = 60  # 1 minute

    if user_id not in _user_calls:
        _user_calls[user_id] = []

    # Clean old entries
    _user_calls[user_id] = [
        (ts, tid) for ts, tid in _user_calls[user_id]
        if now - ts < window
    ]

    if len(_user_calls[user_id]) >= _RATE_LIMIT_PER_MIN:
        return False, f"Rate limit exceeded. Max {_RATE_LIMIT_PER_MIN} calls per minute."

    return True, None


def _record_call(user_id, tool_id):
    """Record a tool call for rate limiting."""
    if user_id not in _user_calls:
        _user_calls[user_id] = []
    _user_calls[user_id].append((time.time(), tool_id))


# ==============================================================================
# INPUT VALIDATION
# ==============================================================================
def _validate_input(text, tool_id, options):
    """Validate user input. Returns (clean_text, error_message)."""
    if not text or not text.strip():
        return None, "Input text is required."

    text = text.strip()

    if len(text) > _MAX_INPUT_LENGTH:
        return None, f"Input too long. Maximum {_MAX_INPUT_LENGTH} characters."

    if len(text) < 10:
        return None, "Input too short. Please provide at least 10 characters."

    if tool_id not in TOOLS:
        return None, "Unknown tool."

    # Validate options
    tool_def = TOOLS[tool_id]
    for opt in tool_def["options"]:
        if opt["id"] in options:
            val = options[opt["id"]]
            if opt["type"] == "select" and val not in opt["choices"]:
                return None, f"Invalid option '{opt['id']}': must be one of {opt['choices']}."

    return text, None


# ==============================================================================
# LLM CALL (internal — never exposed)
# ==============================================================================
def _call_llm(prompt):
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

        data = resp.json()
        text = data.get("response", "").strip()
        return text, latency, None

    except requests.ConnectionError:
        return None, 0, "AI service is temporarily unavailable. Please try again later."
    except requests.Timeout:
        return None, 0, "Request timed out. Try with shorter input."
    except Exception as e:
        return None, 0, "An internal error occurred. Please try again."


def _extract_json(raw_text):
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

    # Try array
    start = raw_text.find("[")
    end = raw_text.rfind("]") + 1
    if start >= 0 and end > start:
        try:
            return json.loads(raw_text[start:end])
        except json.JSONDecodeError:
            pass

    return None


# ==============================================================================
# TOOL IMPLEMENTATIONS
# ==============================================================================

def run_summarizer(text, options):
    """Smart Summarizer — condense text into a clear summary."""
    length = options.get("length", "standard")

    length_instructions = {
        "brief": "Write a very concise summary in 2-3 sentences. Focus only on the most critical point.",
        "standard": "Write a clear summary in 4-6 sentences. Cover all main points.",
        "detailed": "Write a comprehensive summary in 8-12 sentences. Cover main points and important details.",
    }

    prompt = (
        "You are an expert summarizer. Summarize the following text.\n\n"
        f"Length: {length_instructions.get(length, length_instructions['standard'])}\n\n"
        "Your output MUST be valid JSON with this structure:\n"
        "{\n"
        '  "summary": "<the summary>",\n'
        '  "key_points": ["<point 1>", "<point 2>", ...],\n'
        '  "word_count_original": <approximate word count of input>,\n'
        '  "word_count_summary": <word count of your summary>\n'
        "}\n\n"
        "Rules:\n"
        "- Be accurate. Do not add information not in the original text.\n"
        "- Extract 3-5 key bullet points.\n"
        "- Maintain the original text's factual accuracy.\n\n"
        f"Text to summarize:\n{text}\n\n"
        "Summary (JSON):\n"
    )

    raw, latency, error = _call_llm(prompt)
    if error:
        return None, error

    result = _extract_json(raw)
    if not result:
        result = {
            "summary": raw[:1000],
            "key_points": [],
            "word_count_original": len(text.split()),
            "word_count_summary": len(raw.split()),
        }

    # Sanitize — ensure expected fields
    return {
        "summary": result.get("summary", raw[:500]),
        "key_points": result.get("key_points", [])[:8],
        "stats": {
            "original_words": result.get("word_count_original", len(text.split())),
            "summary_words": result.get("word_count_summary", len(result.get("summary", "").split())),
            "compression_ratio": round(
                len(result.get("summary", "").split()) / max(len(text.split()), 1) * 100, 1
            ),
        },
        "processing_time": latency,
    }, None


def run_extractor(text, options):
    """Entity & Keyword Extractor — extract structured data from text."""
    prompt = (
        "You are an expert NLP analyst. Extract entities and keywords from the text below.\n\n"
        "Your output MUST be valid JSON with this structure:\n"
        "{\n"
        '  "entities": {\n'
        '    "people": ["<person 1>", ...],\n'
        '    "organizations": ["<org 1>", ...],\n'
        '    "locations": ["<place 1>", ...],\n'
        '    "dates": ["<date/time reference>", ...]\n'
        "  },\n"
        '  "keywords": ["<keyword 1>", "<keyword 2>", ...],\n'
        '  "topics": ["<main topic 1>", "<main topic 2>", ...],\n'
        '  "category": "<overall category of the text>",\n'
        '  "language": "<detected language>"\n'
        "}\n\n"
        "Rules:\n"
        "- Extract ALL named entities you can find.\n"
        "- Keywords should be the most important terms (5-15 keywords).\n"
        "- Topics should be high-level themes (2-5 topics).\n"
        "- Category should be a single word or short phrase.\n\n"
        f"Text to analyze:\n{text}\n\n"
        "Extraction (JSON):\n"
    )

    raw, latency, error = _call_llm(prompt)
    if error:
        return None, error

    result = _extract_json(raw)
    if not result:
        result = {
            "entities": {"people": [], "organizations": [], "locations": [], "dates": []},
            "keywords": [],
            "topics": [],
            "category": "Unknown",
            "language": "English",
        }

    # Sanitize
    entities = result.get("entities", {})
    return {
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
        "stats": {
            "total_entities": sum(
                len(entities.get(k, []))
                for k in ["people", "organizations", "locations", "dates"]
            ),
            "total_keywords": len(result.get("keywords", [])),
        },
        "processing_time": latency,
    }, None


def run_rewriter(text, options):
    """Content Rewriter — rewrite text in a different tone/style."""
    tone = options.get("tone", "professional")

    tone_instructions = {
        "professional": (
            "Rewrite in a polished, professional business tone. "
            "Use formal language, clear structure, and authoritative voice."
        ),
        "casual": (
            "Rewrite in a friendly, casual conversational tone. "
            "Use everyday language, contractions, and a warm approachable voice."
        ),
        "technical": (
            "Rewrite in a precise, technical tone. "
            "Use domain-specific terminology, exact phrasing, and structured format."
        ),
        "academic": (
            "Rewrite in a formal academic tone. "
            "Use scholarly language, passive voice where appropriate, and cite-worthy phrasing."
        ),
        "creative": (
            "Rewrite in a creative, engaging tone. "
            "Use vivid language, metaphors, storytelling elements, and dynamic phrasing."
        ),
    }

    prompt = (
        "You are an expert content writer and editor.\n\n"
        f"Rewrite the following text in a {tone} tone.\n"
        f"Instructions: {tone_instructions.get(tone, tone_instructions['professional'])}\n\n"
        "Your output MUST be valid JSON with this structure:\n"
        "{\n"
        '  "rewritten_text": "<the rewritten version>",\n'
        '  "changes_made": ["<change 1>", "<change 2>", ...],\n'
        '  "tone_achieved": "<the tone you used>"\n'
        "}\n\n"
        "Rules:\n"
        "- Preserve the core meaning and facts of the original.\n"
        "- Do NOT add new information.\n"
        "- Make the tone change noticeable and consistent.\n"
        "- List 3-5 specific changes you made.\n\n"
        f"Original text:\n{text}\n\n"
        "Rewritten (JSON):\n"
    )

    raw, latency, error = _call_llm(prompt)
    if error:
        return None, error

    result = _extract_json(raw)
    if not result:
        result = {
            "rewritten_text": raw[:2000],
            "changes_made": [],
            "tone_achieved": tone,
        }

    # Sanitize
    return {
        "rewritten_text": result.get("rewritten_text", raw[:2000]),
        "changes_made": result.get("changes_made", [])[:8],
        "tone": result.get("tone_achieved", tone),
        "stats": {
            "original_words": len(text.split()),
            "rewritten_words": len(result.get("rewritten_text", "").split()),
        },
        "processing_time": latency,
    }, None


# ==============================================================================
# TOOL DISPATCHER
# ==============================================================================
_TOOL_RUNNERS = {
    "summarizer": run_summarizer,
    "extractor": run_extractor,
    "rewriter": run_rewriter,
}


def execute_tool(tool_id, user_id, text, options=None):
    """
    Execute a tool securely.

    Args:
        tool_id: Which tool to run
        user_id: Authenticated user's ID (for rate limiting)
        text: User's input text
        options: Optional tool-specific options

    Returns:
        (result_dict, error_string)
    """
    options = options or {}

    # 1. Rate limit check
    allowed, msg = _check_rate_limit(user_id)
    if not allowed:
        return None, msg

    # 2. Validate input
    clean_text, err = _validate_input(text, tool_id, options)
    if err:
        return None, err

    # 3. Get runner
    runner = _TOOL_RUNNERS.get(tool_id)
    if not runner:
        return None, "Unknown tool."

    # 4. Record call (for rate limiting)
    _record_call(user_id, tool_id)

    # 5. Execute
    try:
        result, error = runner(clean_text, options)
        if error:
            return None, error
        return result, None
    except Exception as e:
        return None, "Tool execution failed. Please try again."
