"""
=============================================================================
  Test Integration Demo — Generate Research Text with Local LLM
=============================================================================

This script generates research text using your local Ollama LLM.
It does NOT connect to any agent — that's YOUR job!

After running this script, you'll have research text ready to send
to the Documentation Agent via its Agent Card.

=============================================================================
  HOW TO USE THIS FILE (Step-by-Step)
=============================================================================

  STEP 1: Make sure Ollama is running
  ------------------------------------
  Open a terminal and run:
      ollama serve

  Then make sure you have the model:
      ollama pull qwen2.5:7b


  STEP 2: Run this script to generate research text
  ---------------------------------------------------
      python test_integration_demo.py

  This will:
    - Ask you for a research topic (or use a default one)
    - Call your local LLM to generate research findings
    - Save the output to "research_output.json"
    - Print it to the terminal


  STEP 3: Start the Documentation Agent
  ---------------------------------------
  Open a NEW terminal and run:
      python a2a_documentation_agent.py

  You should see:
      ============================================================
        A2A Documentation Writer Agent
        Port       : 5002
        Agent Card : http://localhost:5002/.well-known/agent.json
      ============================================================


  STEP 4: Connect to the Documentation Agent using its Agent Card
  ----------------------------------------------------------------
  Now open a Python shell (or create a new .py file) and do this:

      # ---- COPY THIS CODE INTO A NEW FILE OR PYTHON SHELL ----

      from python_a2a import A2AClient
      import json

      # 1. Connect using the Agent Card URL
      client = A2AClient("http://localhost:5002")

      # 2. Check the Agent Card (optional — see what the agent can do)
      card = client.agent_card
      print(f"Agent Name: {card.name}")
      print(f"Version:    {card.version}")
      print(f"Skills:     {[s.name for s in card.skills]}")

      # 3. Load the research text we generated
      with open("research_output.json", "r") as f:
          research_text = f.read()

      # 4. Send it to the Documentation Agent
      print("\\nSending research to Documentation Agent...")
      response = client.ask(research_text)

      # 5. See the result
      result = json.loads(response)
      print("\\n" + "=" * 60)
      print(f"  DOCUMENT TITLE: {result['document']['title']}")
      print("=" * 60)
      print(f"  Abstract: {result['document']['abstract'][:200]}...")
      print(f"  Sections: {len(result['document']['sections'])}")
      print(f"  Words:    {result['metadata']['word_count']}")
      print(f"  Latency:  {result['metadata']['latency_sec']}s")
      print("=" * 60)

      # 6. Save the full document
      with open("documentation_output.json", "w") as f:
          json.dump(result, f, indent=2)
      print("\\nFull document saved to: documentation_output.json")

      # ---- END OF INTEGRATION CODE ----


  STEP 5 (OPTIONAL): Test via the Marketplace Website instead
  -------------------------------------------------------------
  If the marketplace is running (python -m marketplace.app):

    1. Open http://localhost:8080 in your browser
    2. Register / Login
    3. Purchase the "Documentation Writer Agent"
    4. Go to "My Agents"
    5. Click the "Integrate" tab — you'll see the Agent Card URL
    6. Click the "Code" tab — you'll see ready-to-use Python code
    7. Click the "Run" tab — paste your research text and click "Run Agent"


  STEP 6 (OPTIONAL): Use curl instead of Python
  -----------------------------------------------
  You can also test the Agent Card directly with curl:

    # Fetch the Agent Card:
    curl -s http://localhost:5002/.well-known/agent.json | python -m json.tool

    # The Agent Card JSON tells you:
    #   - Agent name, version, description
    #   - Available skills and what they do
    #   - How to send tasks to this agent


=============================================================================
  WHAT IS AN AGENT CARD?
=============================================================================

  An Agent Card is a JSON file served at:
      http://<agent-url>/.well-known/agent.json

  It describes:
    - Who the agent is (name, version, description)
    - What it can do (skills with descriptions and tags)
    - How to talk to it (A2A protocol endpoint)

  Think of it like an API spec, but for AI agents.
  Any A2A-compatible client can read the card and start sending tasks.

  Example Agent Card:
  {
    "name": "Documentation Writer Agent",
    "description": "Transforms research into polished documents...",
    "version": "1.0.0",
    "skills": [
      {
        "name": "Write Documentation",
        "description": "Generate structured documentation from research...",
        "tags": ["documentation", "writing", "synthesis"]
      }
    ]
  }

=============================================================================
"""

import sys
import json
import time
import requests

# ==============================================================================
# CONFIG — Change these if needed
# ==============================================================================
OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = "qwen2.5:7b"
OUTPUT_FILE = "research_output.json"


# ==============================================================================
# GENERATE RESEARCH TEXT
# ==============================================================================
def generate_research(topic):
    """Use local Ollama LLM to generate structured research findings."""

    print(f"\n{'=' * 60}")
    print(f"  Generating Research with Local LLM")
    print(f"  Model: {MODEL}")
    print(f"  Topic: {topic}")
    print(f"{'=' * 60}\n")

    prompt = (
        "You are a research analyst. Generate a detailed research report "
        "on the following topic. Your output MUST be valid JSON with this structure:\n\n"
        "{\n"
        '  "topic": "<the topic>",\n'
        '  "summary": "<executive summary, 3-5 sentences>",\n'
        '  "findings": [\n'
        '    {"fact": "<key finding>", "evidence": "<supporting detail>", "source_index": 1},\n'
        '    {"fact": "<key finding>", "evidence": "<supporting detail>", "source_index": 2},\n'
        "    ...\n"
        "  ],\n"
        '  "sources": [\n'
        '    {"index": 1, "text": "<source passage>", "source_url": "N/A"},\n'
        "    ...\n"
        "  ],\n"
        '  "confidence": <0-100>\n'
        "}\n\n"
        "Rules:\n"
        "- Generate 4-6 detailed findings with evidence\n"
        "- Create 3-5 source passages that support the findings\n"
        "- Be factual and thorough\n"
        "- confidence = how well-researched the topic is\n\n"
        f"Topic: {topic}\n\n"
        "Research Report (JSON):\n"
    )

    print("[1/3] Calling Ollama LLM... (this may take 30-60 seconds)")

    try:
        t0 = time.time()
        resp = requests.post(OLLAMA_URL, json={
            "model": MODEL,
            "prompt": prompt,
            "stream": False,
        }, timeout=300)
        elapsed = round(time.time() - t0, 2)
        resp.raise_for_status()
    except requests.ConnectionError:
        print("\n[ERROR] Cannot connect to Ollama!")
        print("  Make sure Ollama is running:  ollama serve")
        print(f"  And the model is available:   ollama pull {MODEL}")
        sys.exit(1)
    except Exception as e:
        print(f"\n[ERROR] LLM call failed: {e}")
        sys.exit(1)

    data = resp.json()
    raw = data.get("response", "").strip()
    tokens = data.get("prompt_eval_count", 0) + data.get("eval_count", 0)

    print(f"[2/3] LLM responded in {elapsed}s ({tokens} tokens)")

    # Parse JSON from response
    import re
    match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", raw, re.DOTALL)
    if match:
        raw = match.group(1).strip()

    start = raw.find("{")
    end = raw.rfind("}") + 1
    if start >= 0 and end > start:
        try:
            research = json.loads(raw[start:end])
        except json.JSONDecodeError:
            research = {"topic": topic, "summary": raw[:500], "findings": [], "sources": [], "confidence": 50}
    else:
        research = {"topic": topic, "summary": raw[:500], "findings": [], "sources": [], "confidence": 50}

    # Save to file
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(research, f, indent=2, ensure_ascii=False)

    print(f"[3/3] Saved to: {OUTPUT_FILE}")

    return research


def display_research(research):
    """Pretty-print the research results."""
    print(f"\n{'=' * 60}")
    print(f"  RESEARCH RESULTS")
    print(f"{'=' * 60}")
    print(f"  Topic      : {research.get('topic', 'N/A')}")
    print(f"  Confidence : {research.get('confidence', '?')}%")
    print(f"  Findings   : {len(research.get('findings', []))}")
    print(f"  Sources    : {len(research.get('sources', []))}")
    print(f"\n  Summary:")
    print(f"  {research.get('summary', 'N/A')[:300]}")

    findings = research.get("findings", [])
    if findings:
        print(f"\n  Key Findings:")
        for i, f in enumerate(findings[:6], 1):
            fact = f.get("fact", str(f))
            print(f"    {i}. {fact[:100]}")

    print(f"{'=' * 60}")


# ==============================================================================
# MAIN
# ==============================================================================
def main():
    print("\n" + "=" * 60)
    print("  Research Text Generator")
    print("  (generates input for the Documentation Agent)")
    print("=" * 60)

    # Ask for topic
    print("\nEnter a research topic (or press Enter for default):")
    topic = input("  > ").strip()

    if not topic:
        topic = "The impact of artificial intelligence on modern healthcare systems"
        print(f"  Using default: \"{topic}\"")

    # Generate research
    research = generate_research(topic)
    display_research(research)

    # Next steps
    print(f"\n{'=' * 60}")
    print(f"  WHAT TO DO NEXT")
    print(f"{'=' * 60}")
    print(f"")
    print(f"  Your research is saved in: {OUTPUT_FILE}")
    print(f"")
    print(f"  Now connect it to the Documentation Agent!")
    print(f"  Read the instructions at the top of this file,")
    print(f"  or do this quick test:")
    print(f"")
    print(f"  1. Start the agent:  python a2a_documentation_agent.py")
    print(f"  2. Open Python shell and run:")
    print(f"")
    print(f'     from python_a2a import A2AClient')
    print(f'     import json')
    print(f'     client = A2AClient("http://localhost:5002")')
    print(f'     card = client.agent_card')
    print(f'     print(f"Connected to: {{card.name}}")')
    print(f'     with open("{OUTPUT_FILE}") as f: data = f.read()')
    print(f'     result = json.loads(client.ask(data))')
    print(f'     print(result["document"]["title"])')
    print(f"")
    print(f"{'=' * 60}\n")


if __name__ == "__main__":
    main()
