"""
A2A Researcher Agent — Agent-to-Agent Protocol
=================================================
Performs deep research on a given topic using BM25 document
retrieval and an Ollama LLM. Returns structured findings with
source passages, key facts, and confidence scores.

Agent Card: http://localhost:5001/.well-known/agent.json

Run:  python a2a_researcher_agent.py
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
_ensure("rank_bm25", "rank_bm25")
_ensure("tqdm")

# ── Imports ────────────────────────────────────────────────────────────────────
import os
import csv
import re
import time
import json
from collections import Counter

import requests
from tqdm import tqdm
from rank_bm25 import BM25Okapi
from python_a2a import A2AServer, skill, agent, run_server
from python_a2a import TaskStatus, TaskState

csv.field_size_limit(2 ** 31 - 1)

# ==============================================================================
# CONFIG
# ==============================================================================
OLLAMA_ENDPOINT = "http://localhost:11434/api/generate"
LLM_MODEL       = "qwen2.5:7b"
TOP_K           = 7          # retrieve more passages for deeper research
CHUNK_SIZE      = 1500
CHUNK_OVERLAP   = 300
DATASET_DIR     = os.path.dirname(os.path.abspath(__file__))
DOCS_CSV        = os.path.join(DATASET_DIR, "documents.csv")
A2A_PORT        = 5001


# ==============================================================================
# DOCUMENT LOADING & CHUNKING
# ==============================================================================
def _chunk_text(text, size=CHUNK_SIZE, overlap=CHUNK_OVERLAP):
    chunks = []
    start = 0
    while start < len(text):
        end = start + size
        chunk = text[start:end]
        if end < len(text):
            for sep in ["\n\n", "\n", ". ", "! ", "? "]:
                last = chunk.rfind(sep)
                if last > size // 2:
                    end = start + last + len(sep)
                    chunk = text[start:end]
                    break
        chunks.append(chunk.strip())
        start = end - overlap
        if start >= len(text):
            break
    return [c for c in chunks if len(c) > 20]


def load_and_chunk_documents(path):
    print(f"\n[data] Loading documents from {os.path.basename(path)} ...")
    raw_docs = []
    skipped = 0
    with open(path, encoding="utf-8", errors="replace", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                idx  = (row.get("index") or "").strip()
                url  = (row.get("source_url") or "").strip()
                text = (row.get("text") or "").strip()
                if text:
                    raw_docs.append({"index": idx, "source_url": url, "text": text})
            except Exception:
                skipped += 1
    print(f"[data] Read {len(raw_docs):,} raw documents.")

    chunks = []
    for doc in tqdm(raw_docs, desc="Chunking", unit="doc"):
        for i, c in enumerate(_chunk_text(doc["text"])):
            chunks.append({
                "doc_index":  doc["index"],
                "source_url": doc["source_url"],
                "chunk_id":   f"{doc['index']}_c{i}",
                "text":       c,
            })
    print(f"[data] Created {len(chunks):,} chunks.")
    return chunks


def _tokenize(text):
    return re.sub(r"[^a-z0-9\s]", " ", text.lower()).split()


def build_bm25(chunks):
    print(f"[index] Building BM25 index over {len(chunks):,} chunks ...")
    tok = [_tokenize(c["text"]) for c in tqdm(chunks, desc="Tokenizing", unit="chunk")]
    bm25 = BM25Okapi(tok)
    print("[index] BM25 ready.")
    return bm25


def retrieve(bm25, chunks, question, k=TOP_K):
    q_tok  = _tokenize(question)
    scores = bm25.get_scores(q_tok)
    top    = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:k]
    return [
        {"text": chunks[i]["text"], "source_url": chunks[i]["source_url"],
         "doc_index": chunks[i]["doc_index"], "chunk_id": chunks[i]["chunk_id"],
         "score": round(float(scores[i]), 4)}
        for i in top
    ]


# ==============================================================================
# LLM -- RESEARCH SYNTHESIS
# ==============================================================================
def synthesize_research(topic, hits):
    """Call LLM to produce a structured research report from retrieved passages."""
    ctx_block = "\n\n---\n\n".join(
        f"[Source {i+1} | doc:{h['doc_index']} | {h['source_url']}]:\n{h['text']}"
        for i, h in enumerate(hits)
    )

    prompt = (
        "You are a senior research analyst.\n"
        "Analyze the source passages below and produce a thorough research report "
        "on the given topic.\n\n"
        "Your output MUST be valid JSON with this exact structure:\n"
        "{\n"
        '  "topic": "<the research topic>",\n'
        '  "summary": "<executive summary — 2-3 sentences>",\n'
        '  "findings": [\n'
        '    {"fact": "<key finding>", "evidence": "<supporting quote or paraphrase>", '
        '"source_index": <1-based index of the source passage>},\n'
        "    ...\n"
        "  ],\n"
        '  "confidence": <0-100>\n'
        "}\n\n"
        "Rules:\n"
        "- Extract 3-7 distinct key findings from the passages.\n"
        "- Each finding must cite which source passage it came from.\n"
        "- Be factual. Do NOT invent information not in the passages.\n"
        "- Confidence = how well the sources cover the topic (0-100).\n\n"
        f"### Topic:\n{topic}\n\n"
        f"### Source Passages:\n{ctx_block}\n\n"
        "### Research Report (JSON):\n"
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


def parse_research_json(raw_text):
    """Extract JSON from LLM output, handling markdown code fences."""
    # Try to find JSON block in code fences
    match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", raw_text, re.DOTALL)
    if match:
        raw_text = match.group(1).strip()

    # Try to find JSON object directly
    start = raw_text.find("{")
    end   = raw_text.rfind("}") + 1
    if start >= 0 and end > start:
        try:
            return json.loads(raw_text[start:end])
        except json.JSONDecodeError:
            pass

    # Fallback: return raw as a simple dict
    return {"topic": "", "summary": raw_text, "findings": [], "confidence": None}


# ==============================================================================
# A2A AGENT
# ==============================================================================
@agent(
    name="Research & Analysis Agent",
    description=(
        "Performs deep research on a given topic using BM25 document retrieval "
        "and a local Ollama LLM (qwen2.5:7b). Retrieves relevant passages from "
        "a curated document corpus, synthesizes findings, and returns a structured "
        "research report with key facts, source citations, and confidence scores. "
        "Ideal for investigative analysis, fact-gathering, and knowledge extraction."
    ),
    version="1.0.0",
)
class ResearcherAgent(A2AServer):

    def __init__(self, bm25, chunks):
        super().__init__(url=f"http://localhost:{A2A_PORT}")
        self._bm25   = bm25
        self._chunks = chunks

    @skill(
        name="Research Topic",
        description=(
            "Deep-dive research on a topic. Retrieves relevant passages from the "
            "document corpus, analyzes them, and returns a structured JSON report "
            "containing: topic, executive summary, key findings with evidence and "
            "source citations, source passage metadata, and a confidence score."
        ),
        tags=["research", "analysis", "knowledge", "retrieval", "investigation"],
    )
    def research_topic(self, topic):
        """Perform deep research on a topic and return structured findings."""
        # 1. Retrieve relevant passages
        hits = retrieve(self._bm25, self._chunks, topic, k=TOP_K)

        # 2. Synthesize research report via LLM
        raw_report, p_tok, e_tok, total_tok, latency = synthesize_research(topic, hits)

        # 3. Parse the JSON report
        report = parse_research_json(raw_report)

        # 4. Attach source metadata
        sources = [
            {
                "index":      i + 1,
                "doc_index":  h["doc_index"],
                "chunk_id":   h["chunk_id"],
                "source_url": h["source_url"],
                "score":      h["score"],
                "text":       h["text"],
            }
            for i, h in enumerate(hits)
        ]

        # 5. Build final response
        result = {
            "topic":          report.get("topic", topic),
            "summary":        report.get("summary", ""),
            "findings":       report.get("findings", []),
            "confidence":     report.get("confidence"),
            "sources":        sources,
            "metrics": {
                "latency_sec":    latency,
                "prompt_tokens":  p_tok,
                "eval_tokens":    e_tok,
                "total_tokens":   total_tok,
                "passages_used":  len(hits),
            },
        }
        return json.dumps(result, ensure_ascii=False)

    def handle_task(self, task):
        """Handle incoming A2A task — extract topic, run research, return report."""
        message_data = task.message or {}
        content = message_data.get("content", {})
        if isinstance(content, dict):
            topic = content.get("text", "")
        elif isinstance(content, str):
            topic = content
        else:
            topic = str(content)

        if not topic.strip():
            task.status = TaskStatus(
                state=TaskState.INPUT_REQUIRED,
                message={
                    "role": "agent",
                    "content": {
                        "type": "text",
                        "text": "Please provide a research topic to investigate.",
                    },
                },
            )
            return task

        try:
            result_json = self.research_topic(topic)
            task.artifacts = [
                {"parts": [{"type": "text", "text": result_json}]}
            ]
            task.status = TaskStatus(state=TaskState.COMPLETED)
        except Exception as e:
            task.status = TaskStatus(
                state=TaskState.FAILED,
                message={
                    "role": "agent",
                    "content": {"type": "text", "text": f"Research failed: {str(e)}"},
                },
            )
        return task


# ==============================================================================
# MAIN
# ==============================================================================
def main():
    if not os.path.exists(DOCS_CSV):
        print(f"[error] documents.csv not found: {DOCS_CSV}")
        sys.exit(1)

    chunks = load_and_chunk_documents(DOCS_CSV)
    if not chunks:
        print("[error] No chunks.")
        sys.exit(1)

    bm25 = build_bm25(chunks)
    agent = ResearcherAgent(bm25, chunks)

    # Import auth middleware
    from a2a_auth import create_authenticated_server

    print(f"\n{'='*60}")
    print(f"  A2A Researcher Agent")
    print(f"  Port       : {A2A_PORT}")
    print(f"  Agent Card : http://localhost:{A2A_PORT}/.well-known/agent.json")
    print(f"  Chunks     : {len(chunks):,}")
    print(f"  LLM        : {LLM_MODEL}")
    print(f"  Top-K      : {TOP_K}")
    print(f"  Auth       : API Key required (X-API-Key header)")
    print(f"{'='*60}\n")

    app = create_authenticated_server(agent, agent_id="researcher", port=A2A_PORT)
    app.run(host="0.0.0.0", port=A2A_PORT)


if __name__ == "__main__":
    main()
