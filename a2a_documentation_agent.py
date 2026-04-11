"""
A2A Documentation Writer Agent — Agent-to-Agent Protocol
==========================================================
Takes research findings (from the Researcher Agent or any source)
and synthesizes them into well-structured, professional documentation
with proper sections, summaries, and cross-references.

Agent Card: http://localhost:5002/.well-known/agent.json

Run:  python a2a_documentation_agent.py
"""

import sys
import subprocess

def _ensure(pkg, import_name=None):
    import importlib
    try:
        importlib.import_module(import_name or pkg)
    except ImportError:
        print(f"[setup] Installing {pkg} ...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", pkg, "-q"])

_ensure("python-a2a", "python_a2a")

# ── Imports ────────────────────────────────────────────────────────────────────
import os
import re
import time
import json

import requests
from python_a2a import A2AServer, skill, agent, run_server
from python_a2a import TaskStatus, TaskState

# ==============================================================================
# CONFIG
# ==============================================================================
OLLAMA_ENDPOINT = "http://localhost:11434/api/generate"
LLM_MODEL       = "qwen2.5:7b"
A2A_PORT        = 5002


# ==============================================================================
# LLM -- DOCUMENTATION GENERATION
# ==============================================================================
def generate_documentation(research_input):
    """
    Call LLM to produce structured documentation from research findings.

    Accepts either:
      - A JSON string (structured research from the Researcher Agent)
      - A plain-text summary to document
    """
    # Parse input
    try:
        research_data = json.loads(research_input) if isinstance(research_input, str) else research_input
    except (json.JSONDecodeError, TypeError):
        research_data = {"topic": "Unknown", "summary": str(research_input), "findings": [], "sources": []}

    topic    = research_data.get("topic", "Research Findings")
    summary  = research_data.get("summary", "")
    findings = research_data.get("findings", [])
    sources  = research_data.get("sources", [])

    # Build context from findings
    findings_block = ""
    if findings:
        for i, f in enumerate(findings, 1):
            fact     = f.get("fact", f.get("key_fact", str(f)))
            evidence = f.get("evidence", "")
            src_idx  = f.get("source_index", "?")
            findings_block += f"\n{i}. FINDING: {fact}\n   EVIDENCE: {evidence}\n   SOURCE: Passage {src_idx}\n"
    else:
        findings_block = f"\n{summary}\n"

    # Build source references
    sources_block = ""
    if sources:
        for s in sources:
            sources_block += (
                f"\n- Source {s.get('index', '?')}: doc#{s.get('doc_index', '?')} "
                f"| URL: {s.get('source_url', 'N/A')} "
                f"| Relevance: {s.get('score', 'N/A')}"
            )

    prompt = (
        "You are a professional technical documentation writer.\n"
        "Transform the research findings below into a well-structured, "
        "publication-ready document.\n\n"
        "Your output MUST be valid JSON with this exact structure:\n"
        "{\n"
        '  "title": "<document title>",\n'
        '  "abstract": "<executive summary — 3-5 sentences>",\n'
        '  "sections": [\n'
        '    {\n'
        '      "heading": "<section heading>",\n'
        '      "content": "<section content — detailed, well-written prose>",\n'
        '      "source_refs": [<list of source indices referenced>]\n'
        '    },\n'
        "    ...\n"
        "  ],\n"
        '  "conclusion": "<concluding summary>",\n'
        '  "references": [\n'
        '    {"index": 1, "description": "<formatted reference entry>"},\n'
        "    ...\n"
        "  ]\n"
        "}\n\n"
        "Rules:\n"
        "- Create 3-6 well-organized sections with meaningful headings.\n"
        "- Write in clear, professional prose (not bullet points everywhere).\n"
        "- Reference sources inline using [Source X] notation.\n"
        "- Include a proper reference list at the end.\n"
        "- Be thorough but concise. No filler content.\n\n"
        f"### Topic:\n{topic}\n\n"
        f"### Research Summary:\n{summary}\n\n"
        f"### Key Findings:\n{findings_block}\n\n"
        f"### Available Sources:\n{sources_block}\n\n"
        "### Documentation (JSON):\n"
    )

    payload = {"model": LLM_MODEL, "prompt": prompt, "stream": False}
    t0 = time.time()
    resp = requests.post(OLLAMA_ENDPOINT, json=payload, timeout=300)
    latency = round(time.time() - t0, 3)
    resp.raise_for_status()

    data = resp.json()
    raw  = data.get("response", "").strip()
    p_tok = data.get("prompt_eval_count", 0)
    e_tok = data.get("eval_count", 0)

    return raw, p_tok, e_tok, p_tok + e_tok, latency


def parse_documentation_json(raw_text):
    """Extract JSON from LLM output, handling markdown code fences."""
    match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", raw_text, re.DOTALL)
    if match:
        raw_text = match.group(1).strip()

    start = raw_text.find("{")
    end   = raw_text.rfind("}") + 1
    if start >= 0 and end > start:
        try:
            return json.loads(raw_text[start:end])
        except json.JSONDecodeError:
            pass

    # Fallback
    return {
        "title": "Documentation",
        "abstract": raw_text[:500],
        "sections": [{"heading": "Content", "content": raw_text, "source_refs": []}],
        "conclusion": "",
        "references": [],
    }


# ==============================================================================
# A2A AGENT
# ==============================================================================
@agent(
    name="Documentation Writer Agent",
    description=(
        "A professional documentation writer that takes research findings "
        "and synthesizes them into well-structured, publication-ready documents. "
        "Produces documents with proper titles, abstracts, organized sections, "
        "inline source references, and formatted reference lists. Powered by "
        "Ollama LLM (qwen2.5:7b). Accepts structured JSON research input or "
        "plain text summaries."
    ),
    version="1.0.0",
)
class DocumentationAgent(A2AServer):

    def __init__(self):
        super().__init__(url=f"http://localhost:{A2A_PORT}")

    @skill(
        name="Write Documentation",
        description=(
            "Generate structured, professional documentation from research findings. "
            "Accepts JSON research output (from Research & Analysis Agent) or plain "
            "text. Returns a JSON document with title, abstract, organized sections "
            "with inline source citations, conclusion, and formatted references."
        ),
        tags=["documentation", "writing", "formatting", "synthesis", "technical-writing"],
    )
    def write_documentation(self, research_input):
        """Generate professional documentation from research findings."""
        # 1. Generate documentation via LLM
        raw_doc, p_tok, e_tok, total_tok, latency = generate_documentation(research_input)

        # 2. Parse the JSON documentation
        doc = parse_documentation_json(raw_doc)

        # 3. Calculate metadata
        total_words = 0
        if doc.get("abstract"):
            total_words += len(doc["abstract"].split())
        for section in doc.get("sections", []):
            total_words += len(section.get("content", "").split())
        if doc.get("conclusion"):
            total_words += len(doc["conclusion"].split())

        # 4. Build final response
        result = {
            "document": {
                "title":      doc.get("title", "Untitled Document"),
                "abstract":   doc.get("abstract", ""),
                "sections":   doc.get("sections", []),
                "conclusion": doc.get("conclusion", ""),
                "references": doc.get("references", []),
            },
            "metadata": {
                "word_count":     total_words,
                "section_count":  len(doc.get("sections", [])),
                "reference_count": len(doc.get("references", [])),
                "latency_sec":    latency,
                "prompt_tokens":  p_tok,
                "eval_tokens":    e_tok,
                "total_tokens":   total_tok,
            },
        }
        return json.dumps(result, ensure_ascii=False)

    def handle_task(self, task):
        """Handle incoming A2A task — extract research input, generate documentation."""
        message_data = task.message or {}
        content = message_data.get("content", {})
        if isinstance(content, dict):
            research_input = content.get("text", "")
        elif isinstance(content, str):
            research_input = content
        else:
            research_input = str(content)

        if not research_input.strip():
            task.status = TaskStatus(
                state=TaskState.INPUT_REQUIRED,
                message={
                    "role": "agent",
                    "content": {
                        "type": "text",
                        "text": (
                            "Please provide research findings to document. "
                            "You can send structured JSON from the Research & Analysis Agent "
                            "or plain text research notes."
                        ),
                    },
                },
            )
            return task

        try:
            result_json = self.write_documentation(research_input)
            task.artifacts = [
                {"parts": [{"type": "text", "text": result_json}]}
            ]
            task.status = TaskStatus(state=TaskState.COMPLETED)
        except Exception as e:
            task.status = TaskStatus(
                state=TaskState.FAILED,
                message={
                    "role": "agent",
                    "content": {"type": "text", "text": f"Documentation generation failed: {str(e)}"},
                },
            )
        return task


# ==============================================================================
# MAIN
# ==============================================================================
def main():
    doc_agent = DocumentationAgent()

    # Import auth middleware
    from a2a_auth import create_authenticated_server

    print(f"\n{'='*60}")
    print(f"  A2A Documentation Writer Agent")
    print(f"  Port       : {A2A_PORT}")
    print(f"  Agent Card : http://localhost:{A2A_PORT}/.well-known/agent.json")
    print(f"  LLM        : {LLM_MODEL}")
    print(f"  Auth       : API Key required (X-API-Key header)")
    print(f"  Input      : JSON research findings or plain text")
    print(f"{'='*60}\n")

    app = create_authenticated_server(doc_agent, agent_id="documentation", port=A2A_PORT)
    app.run(host="0.0.0.0", port=A2A_PORT)


if __name__ == "__main__":
    main()
