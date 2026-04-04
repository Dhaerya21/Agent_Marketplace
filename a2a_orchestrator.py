"""
A2A Orchestrator -- Multi-Agent Pipeline Client
=================================================
Discovers and connects to all three A2A agents via their Agent Cards,
then runs the full pipeline:

  1. Researcher Agent   (port 5001) -> Deep research on a topic
  2. Documentation Agent (port 5002) -> Structured document from research
  3. Citation Agent      (port 5003) -> Fact-check & citation verification

Each agent is an independent A2A server. The orchestrator communicates
with them using the standard A2A protocol (Agent Cards + task messaging).

Prerequisites -- start all three agents first:
  python a2a_researcher_agent.py       (port 5001)
  python a2a_documentation_agent.py    (port 5002)
  python a2a_citation_agent.py         (port 5003)

Then run:
  python a2a_orchestrator.py
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

# -- Imports ----------------------------------------------------------------
import os
import json
import time
from datetime import datetime

from python_a2a import A2AClient

# ==============================================================================
# AGENT REGISTRY -- Agent Card URLs
# ==============================================================================
AGENTS = {
    "researcher":     "http://localhost:5001",
    "documentation":  "http://localhost:5002",
    "citation":       "http://localhost:5003",
}


# ==============================================================================
# DISCOVERY -- Connect to agents and read their Agent Cards
# ==============================================================================
def discover_agents():
    """
    Connect to each agent, fetch its Agent Card, and display capabilities.
    Returns dict of {name: A2AClient}.
    """
    clients = {}
    print(f"\n{'-'*64}")
    print(f"  Agent Discovery -- Scanning A2A endpoints ...")
    print(f"{'-'*64}")

    for name, url in AGENTS.items():
        try:
            client = A2AClient(url)
            card   = client.agent_card
            clients[name] = client

            skills = [s.name for s in card.skills] if card.skills else []
            print(f"\n  [OK] {card.name}")
            print(f"     URL         : {url}")
            print(f"     Version     : {card.version}")
            print(f"     Description : {card.description[:80]}...")
            print(f"     Skills      : {skills}")
        except Exception as e:
            print(f"\n  [FAIL] {name} ({url})")
            print(f"     Error       : {e}")
            print(f"     Hint        : Start it with: python a2a_{name}_agent.py")

    print(f"\n{'-'*64}")
    online = len(clients)
    total  = len(AGENTS)
    print(f"  Discovery complete: {online}/{total} agents online")
    print(f"{'-'*64}")

    return clients


# ==============================================================================
# PIPELINE -- Research -> Documentation -> Citation
# ==============================================================================
def run_pipeline(clients, topic):
    """
    Execute the full multi-agent pipeline on a topic.
    Returns the results from each stage.
    """
    pipeline_start = time.time()
    stages = {}

    # -- Stage 1: Research ---------------------------------------------------
    print(f"\n{'='*64}")
    print(f"  STAGE 1 | Research & Analysis Agent")
    print(f"{'='*64}")

    if "researcher" not in clients:
        print("  [SKIP] Researcher Agent not available.")
        return stages

    print(f"  [->] Sending topic: \"{topic[:60]}...\"" if len(topic) > 60 else f"  [->] Sending topic: \"{topic}\"")
    t0 = time.time()

    try:
        research_response = clients["researcher"].ask(topic)
        research_time = round(time.time() - t0, 3)
    except Exception as e:
        print(f"  [X] Research failed: {e}")
        return stages

    # Parse research results
    try:
        research_data = json.loads(research_response)
    except (json.JSONDecodeError, TypeError):
        research_data = {"topic": topic, "summary": str(research_response), "findings": [], "sources": []}

    stages["research"] = research_data

    # Display research results
    summary   = research_data.get("summary", "N/A")
    findings  = research_data.get("findings", [])
    sources   = research_data.get("sources", [])
    metrics   = research_data.get("metrics", {})
    conf      = research_data.get("confidence", "?")

    print(f"\n  +-- Research Results {'-'*43}")
    print(f"  |  Topic      : {research_data.get('topic', topic)}")
    print(f"  |  Confidence : {conf}%")
    print(f"  |  Findings   : {len(findings)}")
    print(f"  |  Sources    : {len(sources)} passages")
    print(f"  |  Latency    : {metrics.get('latency_sec', research_time)}s")
    print(f"  |  Tokens     : {metrics.get('total_tokens', '?')}")
    print(f"  |")
    print(f"  |  Summary: {summary[:120]}...")
    if findings:
        print(f"  |")
        for i, f in enumerate(findings[:5], 1):
            fact = f.get("fact", f.get("key_fact", str(f)))
            print(f"  |  {i}. {fact[:80]}...")
    print(f"  +{'-'*63}")

    # -- Stage 2: Documentation ----------------------------------------------
    print(f"\n{'='*64}")
    print(f"  STAGE 2 | Documentation Writer Agent")
    print(f"{'='*64}")

    if "documentation" not in clients:
        print("  [SKIP] Documentation Agent not available.")
        return stages

    # Send research results to documentation agent
    doc_input = json.dumps(research_data)
    print(f"  [->] Sending research findings ({len(findings)} findings, {len(sources)} sources)...")
    t0 = time.time()

    try:
        doc_response = clients["documentation"].ask(doc_input)
        doc_time = round(time.time() - t0, 3)
    except Exception as e:
        print(f"  [X] Documentation failed: {e}")
        return stages

    # Parse documentation results
    try:
        doc_data = json.loads(doc_response)
    except (json.JSONDecodeError, TypeError):
        doc_data = {"document": {"title": "Document", "sections": [], "abstract": str(doc_response)}, "metadata": {}}

    stages["documentation"] = doc_data

    # Display documentation results
    doc_obj   = doc_data.get("document", {})
    doc_meta  = doc_data.get("metadata", {})
    sections  = doc_obj.get("sections", [])

    print(f"\n  +-- Documentation Results {'-'*38}")
    print(f"  |  Title      : {doc_obj.get('title', 'Untitled')}")
    print(f"  |  Sections   : {len(sections)}")
    print(f"  |  Words      : {doc_meta.get('word_count', '?')}")
    print(f"  |  References : {doc_meta.get('reference_count', '?')}")
    print(f"  |  Latency    : {doc_meta.get('latency_sec', doc_time)}s")
    print(f"  |  Tokens     : {doc_meta.get('total_tokens', '?')}")
    print(f"  |")
    abstract = doc_obj.get("abstract", "")
    if abstract:
        print(f"  |  Abstract: {abstract[:120]}...")
    print(f"  |")
    for i, sec in enumerate(sections, 1):
        heading = sec.get("heading", f"Section {i}")
        content_preview = sec.get("content", "")[:60]
        print(f"  |  S{i}. {heading}: {content_preview}...")
    print(f"  +{'-'*63}")

    # -- Stage 3: Citation & Fact-Check --------------------------------------
    print(f"\n{'='*64}")
    print(f"  STAGE 3 | Citation & Fact-Check Agent")
    print(f"{'='*64}")

    if "citation" not in clients:
        print("  [SKIP] Citation Agent not available.")
        return stages

    # Build combined input: document + sources
    citation_input = json.dumps({
        "document": doc_obj,
        "sources":  research_data.get("sources", []),
    })
    print(f"  [->] Sending document + {len(sources)} sources for verification...")
    t0 = time.time()

    try:
        cite_response = clients["citation"].ask(citation_input)
        cite_time = round(time.time() - t0, 3)
    except Exception as e:
        print(f"  [X] Fact-check failed: {e}")
        return stages

    # Parse citation results
    try:
        cite_data = json.loads(cite_response)
    except (json.JSONDecodeError, TypeError):
        cite_data = {"verification": {"trust_score": None, "flags": [str(cite_response)]}, "metrics": {}}

    stages["citation"] = cite_data

    # Display citation results
    verification = cite_data.get("verification", {})
    cite_metrics = cite_data.get("metrics", {})
    trust_score  = verification.get("trust_score", "?")
    fc_results   = verification.get("fact_check_results", [])
    cite_report  = verification.get("citation_report", {})
    flags        = verification.get("flags", [])

    print(f"\n  +-- Fact-Check Results {'-'*41}")
    print(f"  |  Trust Score : {trust_score}/100")
    print(f"  |  Claims      : {verification.get('claims_analyzed', '?')} analyzed")
    print(f"  |    Supported    : {verification.get('claims_supported', '?')}")
    print(f"  |    Partial      : {verification.get('claims_partial', '?')}")
    print(f"  |    Unsupported  : {verification.get('claims_unsupported', '?')}")
    print(f"  |  Citations   : {cite_report.get('total_citations', '?')} found, "
          f"{cite_report.get('valid_citations', '?')} valid")
    print(f"  |  Latency     : {cite_metrics.get('latency_sec', cite_time)}s")
    print(f"  |  Tokens      : {cite_metrics.get('total_tokens', '?')}")
    if flags:
        print(f"  |")
        print(f"  |  !! Flags:")
        for flag in flags[:5]:
            print(f"  |    * {flag[:80]}")
    if fc_results:
        print(f"  |")
        print(f"  |  Claim Details:")
        for i, fc in enumerate(fc_results[:5], 1):
            status = fc.get("status", "?")
            claim  = fc.get("claim", "?")[:60]
            icon   = {"SUPPORTED": "[OK]", "PARTIALLY_SUPPORTED": "[~~]", "UNSUPPORTED": "[NO]", "UNVERIFIABLE": "[??]"}.get(status, "[?]")
            print(f"  |    {icon} [{status}] {claim}...")
    print(f"  +{'-'*63}")

    # -- Pipeline Summary ----------------------------------------------------
    total_time = round(time.time() - pipeline_start, 3)

    print(f"\n{'='*64}")
    print(f"  PIPELINE COMPLETE")
    print(f"{'='*64}")
    print(f"  Topic        : {topic}")
    print(f"  Total time   : {total_time}s")
    print(f"  Trust score  : {trust_score}/100")
    print(f"  Stages       : {len(stages)}/3 completed")

    total_tokens = 0
    for stage_name, stage_data in stages.items():
        m = stage_data.get("metrics", stage_data.get("metadata", {}))
        total_tokens += m.get("total_tokens", 0)
    print(f"  Total tokens : {total_tokens}")
    print(f"{'='*64}")

    return stages


# ==============================================================================
# INTERACTIVE MODE
# ==============================================================================
def interactive_mode(clients):
    """Interactive mode -- user enters topics, pipeline runs end-to-end."""
    print(f"\n{'='*64}")
    print(f"  A2A Multi-Agent Pipeline -- Interactive Mode")
    print(f"")
    print(f"  Pipeline: Research -> Documentation -> Fact-Check")
    print(f"")
    print(f"  Enter a research topic to start the pipeline.")
    print(f"  Commands:")
    print(f"    'exit' / 'quit'    -- Stop")
    print(f"    'agents'           -- Show connected agents")
    print(f"    'research <topic>' -- Run only the Researcher")
    print(f"    'docs <text>'      -- Run only the Documentation Agent")
    print(f"    'check <text>'     -- Run only the Citation Agent")
    print(f"{'='*64}")

    turn = 0
    while True:
        turn += 1
        print(f"\n[{turn}] Your topic / command:")
        try:
            user_input = input("  > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n[info] Interrupted.")
            break

        if not user_input or user_input.lower() in ("exit", "quit", "q"):
            print("[info] Stopping ...")
            break

        # -- Command: show agents ----------------------------------------------
        if user_input.lower() == "agents":
            for name, client in clients.items():
                card = client.agent_card
                print(f"  {name:15} | {card.name} | v{card.version}")
            continue

        # -- Command: research only --------------------------------------------
        if user_input.lower().startswith("research "):
            topic = user_input[9:].strip()
            if "researcher" in clients:
                print(f"  [->] Sending to Researcher Agent ...")
                try:
                    response = clients["researcher"].ask(topic)
                    data = json.loads(response) if response else {}
                    print(f"\n  Result:\n{json.dumps(data, indent=2)[:2000]}")
                except Exception as e:
                    print(f"  [X] Error: {e}")
            else:
                print("  [X] Researcher Agent not connected.")
            continue

        # -- Command: docs only ------------------------------------------------
        if user_input.lower().startswith("docs "):
            text = user_input[5:].strip()
            if "documentation" in clients:
                print(f"  [->] Sending to Documentation Agent ...")
                try:
                    response = clients["documentation"].ask(text)
                    data = json.loads(response) if response else {}
                    print(f"\n  Result:\n{json.dumps(data, indent=2)[:2000]}")
                except Exception as e:
                    print(f"  [X] Error: {e}")
            else:
                print("  [X] Documentation Agent not connected.")
            continue

        # -- Command: check only -----------------------------------------------
        if user_input.lower().startswith("check "):
            text = user_input[6:].strip()
            if "citation" in clients:
                print(f"  [->] Sending to Citation Agent ...")
                try:
                    response = clients["citation"].ask(text)
                    data = json.loads(response) if response else {}
                    print(f"\n  Result:\n{json.dumps(data, indent=2)[:2000]}")
                except Exception as e:
                    print(f"  [X] Error: {e}")
            else:
                print("  [X] Citation Agent not connected.")
            continue

        # -- Full pipeline -----------------------------------------------------
        run_pipeline(clients, user_input)


# ==============================================================================
# MAIN
# ==============================================================================
def main():
    print(f"\n{'='*64}")
    print(f"  A2A Multi-Agent Orchestrator")
    print(f"  ----------------------------")
    print(f"  Researcher Agent     : {AGENTS['researcher']}")
    print(f"  Documentation Agent  : {AGENTS['documentation']}")
    print(f"  Citation Agent       : {AGENTS['citation']}")
    print(f"{'='*64}")

    # Discover agents
    clients = discover_agents()

    if not clients:
        print("\n[error] No agents are online. Start them first:")
        print("  python a2a_researcher_agent.py")
        print("  python a2a_documentation_agent.py")
        print("  python a2a_citation_agent.py")
        sys.exit(1)

    # Run interactive mode
    interactive_mode(clients)
    print("\n[done] Orchestrator stopped.")


if __name__ == "__main__":
    main()
