"""
A2A Data Extraction Agent — Agent-to-Agent Protocol
=====================================================
Takes unstructured text (like raw web scraps, emails, logs) and extracts
relevant entities securely into a strict JSON dictionary mapping.

Agent Card: http://localhost:5005/.well-known/agent.json
Run:  python a2a_dataextractor_agent.py
"""

import os
import re
import time
import json
import requests
from python_a2a import A2AServer, skill, agent, run_server

OLLAMA_ENDPOINT = "http://localhost:11434/api/generate"
LLM_MODEL       = "qwen2.5:7b"
A2A_PORT        = 5005

def perform_data_extraction(raw_text):
    """Call LLM to extract entities from raw text."""
    prompt = (
        "You are an expert Data Extraction Engine. Your job is to read unstructured text "
        "and extract specific entities strictly into a JSON dictionary.\n\n"
        "Your output MUST be valid JSON with this EXACT structure:\n"
        "{\n"
        '  "people": ["<list of people mentioned>"],\n'
        '  "organizations": ["<list of companies or orgs>"],\n'
        '  "dates": ["<any dates or timeframes mentioned>"],\n'
        '  "emails_urls": ["<any emails or hyperlinks>"],\n'
        '  "keywords": ["<3-5 major keywords characterizing the text>"]\n'
        "}\n\n"
        "Rules:\n"
        "- Do not include markdown code fences (```json) in your final output. Return ONLY the raw JSON object.\n"
        "- If an entity type isn't present, return an empty array [].\n"
        "- Never hallucinate. Ensure extracted entities actually exist in the raw text.\n\n"
        f"### Raw Unstructured Text:\n{raw_text}\n\n"
        "### Extracted Entities (JSON):\n"
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
        fallback = {
            "people": [],
            "organizations": [],
            "dates": [],
            "emails_urls": [],
            "keywords": ["Failed Parsing"]
        }
        return json.dumps(fallback, ensure_ascii=False), {"latency_sec": latency, "tokens": 0}


@agent(
    name="Data Extraction Agent",
    description=(
        "An automated parser that rips through completely unstructured text "
        "(like logs, raw emails, scraping data) and extracts specific structured "
        "entities such as People, Orgs, Dates, and Contact Info into strict JSON lists."
    ),
    version="1.0.0",
)
class DataExtractorAgent(A2AServer):
    def __init__(self):
        super().__init__(url=f"http://localhost:{A2A_PORT}")

    @skill(
        name="Extract Entities",
        description="Extracts named entities (People, Orgs, Dates) from raw input text and returns JSON mapping."
    )
    def extract_data(self, unstructured_text: str) -> str:
        """
        Runs the LLM against the inputted raw text.
        """
        print(f"[DataExtractor] Sifting unstructured text ({len(unstructured_text)} chars)...")
        result_json, metrics = perform_data_extraction(unstructured_text)
        print(f"[DataExtractor] Finished in {metrics.get('latency_sec', 0)}s.")

        final_response = {
            "extracted_data": json.loads(result_json),
            "metrics": metrics
        }
        return json.dumps(final_response, ensure_ascii=False)


if __name__ == "__main__":
    print(f"Starting A2A Data Extraction Agent on port {A2A_PORT}...")
    server = DataExtractorAgent()
    run_server(server, port=A2A_PORT)
