"""
Agent Proxy Layer
==================
Forwards user requests to A2A agents while hiding all internal details.
Designed with an abstract interface so MCP servers can be added in the future.

Supported protocols:
  - A2A (Agent-to-Agent) — current, fully implemented
  - MCP (Model Context Protocol) — future, placeholder ready
"""

import json
import time
import traceback
from python_a2a import A2AClient


class AgentProxy:
    """
    Proxy that sits between the marketplace API and the actual A2A agents.
    Users never see agent URLs, ports, or internal implementation details.
    """

    def __init__(self):
        self._clients = {}      # url -> A2AClient (cached)
        self._card_cache = {}   # url -> {card_data, fetched_at}
        self._CARD_TTL = 60     # cache agent cards for 60 seconds
        # Master key for authenticating with A2A agents on behalf of users
        import os
        self._master_key = os.environ.get(
            "MARKETPLACE_MASTER_KEY", "mk_internal_proxy_2a9f8b3e"
        )

    def _get_client(self, a2a_url):
        """Get or create a cached A2AClient for an agent URL."""
        if a2a_url not in self._clients:
            try:
                self._clients[a2a_url] = A2AClient(a2a_url)
            except Exception as e:
                raise ConnectionError(f"Agent unavailable: {e}")
        return self._clients[a2a_url]

    def check_health(self, a2a_url):
        """Check if an agent is online by fetching its Agent Card."""
        try:
            client = self._get_client(a2a_url)
            card = client.agent_card
            return {"online": True, "name": card.name, "version": card.version}
        except Exception:
            # Remove cached client on failure
            self._clients.pop(a2a_url, None)
            return {"online": False}

    # ------------------------------------------------------------------
    # AGENT CARD FETCHING
    # ------------------------------------------------------------------
    def get_agent_card(self, a2a_url):
        """
        Fetch the live Agent Card JSON from an A2A server, with caching.
        Returns (card_dict, error_string).
        """
        now = time.time()
        cached = self._card_cache.get(a2a_url)
        if cached and (now - cached["fetched_at"]) < self._CARD_TTL:
            return cached["card_data"], None

        try:
            import requests as http_requests
            card_url = a2a_url + "/.well-known/agent.json"
            resp = http_requests.get(card_url, timeout=5)
            resp.raise_for_status()
            card_data = resp.json()
            self._card_cache[a2a_url] = {"card_data": card_data, "fetched_at": now}
            return card_data, None
        except Exception as e:
            return None, f"Agent is currently offline: {e}"

    def get_skills_preview(self, a2a_url):
        """
        Extract skill names, descriptions, and tags from an agent's card.
        Returns a list of {name, description, tags} dicts.
        """
        card_data, err = self.get_agent_card(a2a_url)
        if not card_data:
            return []

        skills = card_data.get("skills", [])
        preview = []
        for s in skills:
            preview.append({
                "name": s.get("name", "Unknown"),
                "description": s.get("description", "")[:120],
                "tags": s.get("tags", []),
            })
        return preview

    # ------------------------------------------------------------------
    # CODE SNIPPET GENERATION
    # ------------------------------------------------------------------
    def generate_snippets(self, a2a_url, agent_name, agent_type="a2a", api_key="YOUR_API_KEY"):
        """
        Generate integration code snippets for an agent.
        Returns dict with python, curl, and (future) mcp snippets.
        All snippets now include API key authentication.
        """
        card_url = a2a_url + "/.well-known/agent.json"

        if agent_type == "mcp":
            return self._generate_mcp_snippets(a2a_url, agent_name)

        python_snippet = (
            'import requests, json\n'
            '\n'
            f'# {agent_name} -- Authenticated A2A Integration\n'
            f'A2A_URL = "{a2a_url}"\n'
            f'API_KEY = "{api_key}"  # Your personal API key\n'
            '\n'
            '# 1. View the Agent Card (public -- no key needed)\n'
            'card = requests.get(f"{A2A_URL}/.well-known/agent.json").json()\n'
            'print(f"Agent: {card[\'name\']}")\n'
            '\n'
            '# 2. Send a task (requires API key)\n'
            'payload = {\n'
            '    "jsonrpc": "2.0", "method": "tasks/send", "id": "1",\n'
            '    "params": {"id": "task-1", "message": {\n'
            '        "role": "user",\n'
            '        "content": {"type": "text", "text": "Your input here"}\n'
            '    }}\n'
            '}\n'
            'resp = requests.post(\n'
            '    f"{A2A_URL}/a2a",\n'
            '    json=payload,\n'
            '    headers={"X-API-Key": API_KEY}\n'
            ')\n'
            'print(json.dumps(resp.json(), indent=2))\n'
        )

        curl_card_snippet = (
            '# Fetch the Agent Card (public -- no key needed)\n'
            f'curl -s {card_url} | python -m json.tool\n'
        )

        curl_run_snippet = (
            '# Send a task (requires API key)\n'
            f'curl -X POST {a2a_url}/a2a \\\n'
            '  -H "Content-Type: application/json" \\\n'
            f'  -H "X-API-Key: {api_key}" \\\n'
            '  -d \'{"jsonrpc":"2.0","method":"tasks/send","id":"1",'
            '"params":{"id":"task-1","message":{"role":"user",'
            '"content":{"type":"text","text":"Your input"}}}}\' \\\n'
            '  | python -m json.tool\n'
        )

        js_snippet = (
            f'// {agent_name} -- Authenticated A2A Integration\n'
            f'const A2A_URL = "{a2a_url}";\n'
            f'const API_KEY = "{api_key}";  // Your personal API key\n'
            '\n'
            '// 1. Fetch Agent Card (public)\n'
            'const card = await fetch(`${A2A_URL}/.well-known/agent.json`);\n'
            'console.log("Agent:", (await card.json()).name);\n'
            '\n'
            '// 2. Send a task (requires API key)\n'
            'const res = await fetch(`${A2A_URL}/a2a`, {\n'
            '  method: "POST",\n'
            '  headers: {\n'
            '    "Content-Type": "application/json",\n'
            '    "X-API-Key": API_KEY\n'
            '  },\n'
            '  body: JSON.stringify({\n'
            '    jsonrpc: "2.0", method: "tasks/send", id: "1",\n'
            '    params: { id: "task-1", message: {\n'
            '      role: "user", content: { type: "text", text: "Your input" }\n'
            '    }}\n'
            '  })\n'
            '});\n'
            'console.log(await res.json());\n'
        )

        return {
            "python": python_snippet,
            "curl_card": curl_card_snippet,
            "curl_run": curl_run_snippet,
            "javascript": js_snippet,
        }

    def _generate_mcp_snippets(self, mcp_url, agent_name):
        """Future: generate MCP integration snippets."""
        return {
            "python": (
                f'# MCP integration for {agent_name}\n'
                f'# Coming soon -- install: pip install mcp-client\n'
                f'#\n'
                f'# from mcp_client import MCPClient\n'
                f'# client = MCPClient("{mcp_url}")\n'
                f'# tools = client.list_tools()\n'
                f'# result = client.call_tool("tool_name", {{"input": "..."}})\n'
            ),
            "curl_card": f'# MCP server metadata (coming soon)\n# curl -s {mcp_url}/mcp/metadata\n',
            "curl_run": f'# MCP tool call (coming soon)\n# curl -X POST {mcp_url}/mcp/call ...\n',
            "javascript": f'// MCP integration for {agent_name} -- coming soon\n',
        }

    # ------------------------------------------------------------------
    # AGENT EXECUTION
    # ------------------------------------------------------------------
    def run_agent(self, a2a_url, user_input, agent_type="a2a"):
        """
        Run an agent with the given input, returning sanitized results.

        Args:
            a2a_url: Internal URL of the A2A agent
            user_input: The user's input text
            agent_type: "a2a" (current) or "mcp" (future)

        Returns:
            dict with sanitized results (no internal URLs, ports, etc.)
        """
        if agent_type == "mcp":
            return self._run_mcp_agent(a2a_url, user_input)

        return self._run_a2a_agent(a2a_url, user_input)

    def _run_a2a_agent(self, a2a_url, user_input):
        """Execute a request against an A2A agent, authenticating with master key."""
        import requests as http_requests

        t0 = time.time()

        # Build JSON-RPC payload
        payload = {
            "jsonrpc": "2.0",
            "method": "tasks/send",
            "id": f"proxy-{int(time.time())}",
            "params": {
                "id": f"task-{int(time.time())}",
                "message": {
                    "role": "user",
                    "content": {"type": "text", "text": user_input},
                },
            },
        }

        try:
            resp = http_requests.post(
                a2a_url + "/a2a",
                json=payload,
                headers={
                    "Content-Type": "application/json",
                    "X-API-Key": self._master_key,
                },
                timeout=120,
            )
            elapsed = round(time.time() - t0, 3)

            if resp.status_code in (401, 403):
                return {
                    "success": False,
                    "error": "Agent authentication failed. Internal proxy error.",
                    "elapsed_sec": elapsed,
                }

            resp.raise_for_status()
            rpc_result = resp.json()

        except Exception as e:
            return {
                "success": False,
                "error": "Agent is currently unavailable. Please try again later.",
                "elapsed_sec": round(time.time() - t0, 3),
            }

        # Extract the text content from RPC response
        try:
            result = rpc_result.get("result", {})
            artifacts = result.get("artifacts", [])
            if artifacts:
                parts = artifacts[0].get("parts", [])
                if parts:
                    raw_text = parts[0].get("text", "")
                    try:
                        data = json.loads(raw_text)
                    except (json.JSONDecodeError, TypeError):
                        data = {"raw_output": raw_text}
                else:
                    data = {"raw_output": str(rpc_result)}
            else:
                data = {"raw_output": str(rpc_result)}
        except Exception:
            data = {"raw_output": str(rpc_result)}

        # Sanitize -- remove internal fields
        sanitized = self._sanitize_response(data)
        sanitized["success"] = True
        sanitized["elapsed_sec"] = elapsed

        return sanitized

    def _sanitize_response(self, data):
        """
        Remove internal implementation details from agent responses.
        Users should never see: a2a_url, port numbers, doc_index, chunk_id, etc.
        """
        if not isinstance(data, dict):
            return {"output": str(data)}

        sanitized = {}

        # Copy safe top-level fields
        safe_fields = [
            "topic", "summary", "findings", "confidence",
            "answer", "confidence_pct",
            "document", "metadata",
            "verification", "trust_score",
            "title", "abstract", "sections", "conclusion", "references",
            "raw_output",
        ]
        for field in safe_fields:
            if field in data:
                sanitized[field] = data[field]

        # Sanitize nested sources -- remove internal IDs
        if "sources" in data:
            sanitized["sources_count"] = len(data["sources"])
            sanitized["sources"] = []
            for src in data["sources"][:5]:  # Limit to 5
                clean_src = {}
                if "source_url" in src and src["source_url"]:
                    clean_src["url"] = src["source_url"]
                if "score" in src:
                    clean_src["relevance"] = src["score"]
                if "text" in src:
                    clean_src["preview"] = src["text"][:200] + "..."
                sanitized["sources"].append(clean_src)

        # Sanitize metrics -- keep useful ones, remove token counts
        if "metrics" in data:
            m = data["metrics"]
            sanitized["metrics"] = {
                "latency_sec": m.get("latency_sec"),
                "passages_used": m.get("passages_used"),
            }

        # Sanitize findings -- keep facts, remove source_index
        if "findings" in sanitized and isinstance(sanitized["findings"], list):
            clean_findings = []
            for f in sanitized["findings"]:
                if isinstance(f, dict):
                    clean_findings.append({
                        "fact": f.get("fact", f.get("key_fact", str(f))),
                        "evidence": f.get("evidence", ""),
                    })
                else:
                    clean_findings.append({"fact": str(f), "evidence": ""})
            sanitized["findings"] = clean_findings

        return sanitized

    def _run_mcp_agent(self, mcp_url, user_input):
        """
        Future: Execute a request against an MCP server.

        When implemented, this will:
          1. Connect to the MCP server at mcp_url
          2. List available tools
          3. Select the appropriate tool based on the input
          4. Execute the tool call
          5. Return sanitized results

        For now, returns a placeholder response.
        """
        return {
            "success": False,
            "error": "MCP agent support coming soon. Stay tuned!",
            "agent_type": "mcp",
            "elapsed_sec": 0,
        }


# Singleton instance
proxy = AgentProxy()
