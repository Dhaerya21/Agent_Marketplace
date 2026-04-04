"""
Agent Proxy Layer
==================
Forwards user requests to A2A agents while hiding all internal details.
Designed with an abstract interface so MCP servers can be added in the future.
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
        self._clients = {}  # agent_id -> A2AClient (cached)

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
        """Execute a request against an A2A agent."""
        t0 = time.time()

        try:
            client = self._get_client(a2a_url)
            raw_response = client.ask(user_input)
            elapsed = round(time.time() - t0, 3)
        except Exception as e:
            self._clients.pop(a2a_url, None)
            return {
                "success": False,
                "error": f"Agent is currently unavailable. Please try again later.",
                "elapsed_sec": round(time.time() - t0, 3),
            }

        # Parse response
        try:
            data = json.loads(raw_response) if isinstance(raw_response, str) else raw_response
        except (json.JSONDecodeError, TypeError):
            data = {"raw_output": str(raw_response)}

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
        This is a placeholder for MCP protocol integration.
        """
        return {
            "success": False,
            "error": "MCP agent support coming soon.",
            "elapsed_sec": 0,
        }


# Singleton instance
proxy = AgentProxy()
