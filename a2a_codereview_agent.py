"""
A2A Code Review Agent — Agent-to-Agent Protocol
=================================================
Analyzes code snippets to identify bugs, security vulnerabilities, 
and performance optimizations, returning structured JSON audits.

Agent Card: http://localhost:5004/.well-known/agent.json
Run:  python a2a_codereview_agent.py
"""

import os
import re
import time
import json
import requests
from python_a2a import A2AServer, skill, agent, run_server

OLLAMA_ENDPOINT = "http://localhost:11434/api/generate"
LLM_MODEL       = "qwen2.5:7b"
A2A_PORT        = 5004

def perform_code_review(code_snippet):
    """Call LLM to audit a provided code snippet."""
    prompt = (
        "You are an expert Principal Senior Software Engineer conducting a thorough code review.\n"
        "Analyze the provided code snippet for logic bugs, security vulnerabilities, and optimizations.\n\n"
        "Your output MUST be valid JSON with this EXACT structure:\n"
        "{\n"
        '  "summary": "<Overall summary of code health in 2-3 sentences>",\n'
        '  "score": <integer from 0 to 100 representing code quality>,\n'
        '  "bugs": [\n'
        '    {"description": "<bug detail>", "severity": "<low|medium|high>"}\n'
        '  ],\n'
        '  "security_risks": [\n'
        '    {"description": "<security flaw detail>", "severity": "<critical|high|medium|low>"}\n'
        '  ],\n'
        '  "optimizations": [\n'
        '    {"suggestion": "<how to improve performance or readability>"}\n'
        '  ]\n'
        "}\n\n"
        "Rules:\n"
        "- Do not include markdown code fences (```json) in your final output. Return ONLY the raw JSON object.\n"
        "- If the code has no bugs or risks, return empty lists [] for those fields.\n\n"
        f"### Code Snippet to Audit:\n{code_snippet}\n\n"
        "### Review JSON:\n"
    )

    payload = {"model": LLM_MODEL, "prompt": prompt, "stream": False}
    t0 = time.time()
    try:
        resp = requests.post(OLLAMA_ENDPOINT, json=payload, timeout=300)
        resp.raise_for_status()
        data = resp.json()
        raw = data.get("response", "").strip()
        p_tok = data.get("prompt_eval_count", 0)
        e_tok = data.get("eval_count", 0)
        latency = round(time.time() - t0, 3)
    except Exception as e:
        return f'{{"error": "LLM failed: {str(e)}" }}', 0

    # Clean markdown fences
    match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", raw, re.DOTALL)
    if match:
        raw = match.group(1).strip()
    
    start = raw.find("{")
    end = raw.rfind("}") + 1
    if start >= 0 and end > start:
        raw = raw[start:end]

    try:
        parsed = json.loads(raw)
        return json.dumps(parsed, ensure_ascii=False), {"latency_sec": latency, "tokens": p_tok + e_tok}
    except json.JSONDecodeError:
        # Fallback
        fallback = {
            "summary": raw,
            "score": 0,
            "bugs": [],
            "security_risks": [],
            "optimizations": []
        }
        return json.dumps(fallback, ensure_ascii=False), {"latency_sec": latency, "tokens": 0}


@agent(
    name="Code Review & Audit Agent",
    description=(
        "An expert architectural auditor that evaluates provided source code. "
        "It spots logic errors, uncovers deep security vulnerabilities, and "
        "suggests syntactical optimizations, returning the structural analysis as JSON."
    ),
    version="1.0.0",
)
class CodeReviewAgent(A2AServer):
    def __init__(self):
        super().__init__(url=f"http://localhost:{A2A_PORT}")

    @skill(
        name="Review Code",
        description="Audits a snippet of code and returns a JSON report mapping bugs, security risks, and optimization advice."
    )
    def review_code(self, code: str) -> str:
        """
        Runs the LLM against the inputted code snippet.
        """
        print(f"[CodeReview] Analyzing snippet ({len(code)} chars)...")
        result_json, metrics = perform_code_review(code)
        print(f"[CodeReview] Finished in {metrics.get('latency_sec', 0)}s.")

        final_response = {
            "audit": json.loads(result_json),
            "metrics": metrics
        }
        return json.dumps(final_response, ensure_ascii=False)


if __name__ == "__main__":
    print(f"Starting A2A Code Review Agent on port {A2A_PORT}...")
    server = CodeReviewAgent()
    run_server(server, port=A2A_PORT)
