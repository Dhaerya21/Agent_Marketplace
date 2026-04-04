"""
A2A Citation & Fact-Check Agent — Agent-to-Agent Protocol
============================================================
Verifies claims in a document against source passages, validates
citations, flags unsupported statements, and produces a fact-check
report with trust scores.

Agent Card: http://localhost:5003/.well-known/agent.json

Run:  python a2a_citation_agent.py
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
A2A_PORT        = 5003


# ==============================================================================
# LLM -- CITATION & FACT-CHECK
# ==============================================================================
def fact_check_document(document_input):
    """
    Call LLM to fact-check a document against its source passages.

    Accepts either:
      - A JSON string with "document" and "sources" fields
        (from Documentation Agent + Research Agent pipeline)
      - A plain-text document with optional embedded source references
    """
    # Parse input — expect JSON with document + sources
    try:
        input_data = json.loads(document_input) if isinstance(document_input, str) else document_input
    except (json.JSONDecodeError, TypeError):
        input_data = {"document_text": str(document_input), "sources": []}

    # Extract document content
    doc_obj = input_data.get("document", {})
    if isinstance(doc_obj, dict):
        # Reconstruct full document text from sections
        parts = []
        if doc_obj.get("title"):
            parts.append(f"# {doc_obj['title']}")
        if doc_obj.get("abstract"):
            parts.append(f"\n## Abstract\n{doc_obj['abstract']}")
        for section in doc_obj.get("sections", []):
            heading = section.get("heading", "Section")
            content = section.get("content", "")
            parts.append(f"\n## {heading}\n{content}")
        if doc_obj.get("conclusion"):
            parts.append(f"\n## Conclusion\n{doc_obj['conclusion']}")
        document_text = "\n".join(parts)
    else:
        document_text = input_data.get("document_text", str(doc_obj or document_input))

    # Extract sources
    sources = input_data.get("sources", [])
    sources_block = ""
    if sources:
        for s in sources:
            idx      = s.get("index", "?")
            text     = s.get("text", s.get("preview", ""))[:500]
            url      = s.get("source_url", "N/A")
            doc_idx  = s.get("doc_index", "?")
            sources_block += (
                f"\n[SOURCE {idx}] (doc#{doc_idx} | {url}):\n{text}\n"
            )
    else:
        sources_block = "\n(No source passages provided — check citations against document internal consistency only)\n"

    prompt = (
        "You are an expert fact-checker and citation auditor.\n"
        "Analyze the document below against its source passages.\n\n"
        "Your output MUST be valid JSON with this exact structure:\n"
        "{\n"
        '  "trust_score": <0-100 overall trust score>,\n'
        '  "claims_analyzed": <total number of claims checked>,\n'
        '  "claims_supported": <number fully supported>,\n'
        '  "claims_partial": <number partially supported>,\n'
        '  "claims_unsupported": <number unsupported>,\n'
        '  "fact_check_results": [\n'
        '    {\n'
        '      "claim": "<extracted claim from the document>",\n'
        '      "status": "<SUPPORTED|PARTIALLY_SUPPORTED|UNSUPPORTED|UNVERIFIABLE>",\n'
        '      "evidence": "<supporting or contradicting evidence from sources>",\n'
        '      "source_ref": "<which source(s) this was checked against>",\n'
        '      "confidence": <0-100 confidence in this verification>\n'
        '    },\n'
        "    ...\n"
        "  ],\n"
        '  "citation_report": {\n'
        '    "total_citations": <number of source citations found in document>,\n'
        '    "valid_citations": <number that correctly reference existing sources>,\n'
        '    "invalid_citations": <number that reference non-existent sources>,\n'
        '    "missing_citations": <number of claims that should cite a source but don\'t>\n'
        "  },\n"
        '  "flags": [\n'
        '    "<warning or issue — e.g. unsupported claim, missing citation, etc.>",\n'
        "    ...\n"
        "  ],\n"
        '  "verified_summary": "<brief summary of the document\'s factual reliability>"\n'
        "}\n\n"
        "Rules:\n"
        "- Extract every factual claim from the document.\n"
        "- Cross-reference each claim against the source passages.\n"
        "- Mark claims as SUPPORTED only if source evidence directly supports them.\n"
        "- Mark claims as PARTIALLY_SUPPORTED if evidence is indirect or incomplete.\n"
        "- Mark claims as UNSUPPORTED if no source evidence supports them.\n"
        "- Mark claims as UNVERIFIABLE if they cannot be checked with available sources.\n"
        "- Flag any citation that references a non-existent source.\n"
        "- trust_score = (supported + 0.5*partial) / total_claims * 100.\n\n"
        f"### Document to Verify:\n{document_text}\n\n"
        f"### Source Passages:\n{sources_block}\n\n"
        "### Fact-Check Report (JSON):\n"
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


def parse_factcheck_json(raw_text):
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
        "trust_score": None,
        "claims_analyzed": 0,
        "claims_supported": 0,
        "claims_partial": 0,
        "claims_unsupported": 0,
        "fact_check_results": [],
        "citation_report": {
            "total_citations": 0,
            "valid_citations": 0,
            "invalid_citations": 0,
            "missing_citations": 0,
        },
        "flags": ["Failed to parse fact-check output"],
        "verified_summary": raw_text[:500],
    }


# ==============================================================================
# A2A AGENT
# ==============================================================================
@agent(
    name="Citation & Fact-Check Agent",
    description=(
        "An expert fact-checker and citation auditor that verifies claims "
        "in a document against source passages. Extracts all factual claims, "
        "cross-references them with source evidence, validates citation accuracy, "
        "flags unsupported or unverifiable statements, and produces a comprehensive "
        "fact-check report with a trust score (0-100). Powered by Ollama LLM "
        "(qwen2.5:7b). Accepts JSON input with document and sources, or the "
        "combined output from Research & Documentation agents."
    ),
    version="1.0.0",
)
class CitationAgent(A2AServer):

    def __init__(self):
        super().__init__(url=f"http://localhost:{A2A_PORT}")

    @skill(
        name="Verify & Cite",
        description=(
            "Fact-check a document against source passages and validate all "
            "citations. Extracts claims, cross-references with sources, checks "
            "citation validity, and returns a verification report with: "
            "trust score, claim-by-claim analysis (supported/unsupported/partial), "
            "citation accuracy metrics, and warning flags."
        ),
        tags=["citation", "fact-check", "verification", "trust", "audit"],
    )
    def verify_and_cite(self, document_input):
        """Fact-check a document and verify all citations."""
        # 1. Run fact-check via LLM
        raw_report, p_tok, e_tok, total_tok, latency = fact_check_document(document_input)

        # 2. Parse the JSON report
        report = parse_factcheck_json(raw_report)

        # 3. Build final response
        result = {
            "verification": {
                "trust_score":        report.get("trust_score"),
                "claims_analyzed":    report.get("claims_analyzed", 0),
                "claims_supported":   report.get("claims_supported", 0),
                "claims_partial":     report.get("claims_partial", 0),
                "claims_unsupported": report.get("claims_unsupported", 0),
                "fact_check_results": report.get("fact_check_results", []),
                "citation_report":    report.get("citation_report", {}),
                "flags":              report.get("flags", []),
                "verified_summary":   report.get("verified_summary", ""),
            },
            "metrics": {
                "latency_sec":   latency,
                "prompt_tokens": p_tok,
                "eval_tokens":   e_tok,
                "total_tokens":  total_tok,
            },
        }
        return json.dumps(result, ensure_ascii=False)

    def handle_task(self, task):
        """Handle incoming A2A task — extract document input, run fact-check."""
        message_data = task.message or {}
        content = message_data.get("content", {})
        if isinstance(content, dict):
            document_input = content.get("text", "")
        elif isinstance(content, str):
            document_input = content
        else:
            document_input = str(content)

        if not document_input.strip():
            task.status = TaskStatus(
                state=TaskState.INPUT_REQUIRED,
                message={
                    "role": "agent",
                    "content": {
                        "type": "text",
                        "text": (
                            "Please provide document content to fact-check. "
                            "Ideally, send a JSON payload with 'document' and 'sources' "
                            "fields (output from Documentation + Research agents)."
                        ),
                    },
                },
            )
            return task

        try:
            result_json = self.verify_and_cite(document_input)
            task.artifacts = [
                {"parts": [{"type": "text", "text": result_json}]}
            ]
            task.status = TaskStatus(state=TaskState.COMPLETED)
        except Exception as e:
            task.status = TaskStatus(
                state=TaskState.FAILED,
                message={
                    "role": "agent",
                    "content": {"type": "text", "text": f"Fact-check failed: {str(e)}"},
                },
            )
        return task


# ==============================================================================
# MAIN
# ==============================================================================
def main():
    citation_agent = CitationAgent()

    print(f"\n{'='*60}")
    print(f"  A2A Citation & Fact-Check Agent")
    print(f"  Port       : {A2A_PORT}")
    print(f"  Agent Card : http://localhost:{A2A_PORT}/.well-known/agent.json")
    print(f"  LLM        : {LLM_MODEL}")
    print(f"  Input      : JSON (document + sources) or plain text")
    print(f"{'='*60}\n")

    run_server(citation_agent, host="0.0.0.0", port=A2A_PORT)


if __name__ == "__main__":
    main()
