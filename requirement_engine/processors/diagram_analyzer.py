import json
import os
from typing import Dict, Any, List, Optional

from groq import Groq


class DiagramAnalyzer:
    """Extracts structured workflow information from diagram images using Groq Vision."""

    DEFAULT_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"

    def __init__(self, groq_api_key: str = None, model: str = None):
        self.client = None
        self.model = model or self.DEFAULT_MODEL

        api_key = groq_api_key or os.getenv("GROQ_API_KEY")

        if api_key:
            try:
                self.client = Groq(api_key=api_key)
                self.client.models.list()
            except Exception as e:
                self.client = None
                if not isinstance(e, ImportError):
                    print(f"  ⚠ Groq initialization failed (check API key): {e}")

    @property
    def is_available(self) -> bool:
        return self.client is not None

    def extract_graph_json(self, image_base64: str, source: str = "diagram") -> Dict[str, Any]:
        if not self.client:
            return self._empty_result(source, "No Vision LLM configured")

        try:
            prompt = (
                "Analyze this workflow diagram and extract its complete structure.\n\n"
                "Return a JSON object with these fields:\n"
                "{\n"
                '  "has_diagram": true,\n'
                '  "diagram_type": "flowchart" | "process" | "state" | "activity" | "sequence",\n'
                '  "diagram_title": "title if visible, else null",\n'
                '  "nodes": [\n'
                '    {"id": "node_1", "label": "exact text in node", "type": "start|end|process|decision|io"}\n'
                "  ],\n"
                '  "connections": [\n'
                '    {"from": "node_1", "to": "node_2", "label": "text on arrow if any"}\n'
                "  ],\n"
                '  "decision_points": [\n'
                '    {"node_id": "node_3", "condition": "condition text", "yes_path": "node_4", "no_path": "node_5"}\n'
                "  ],\n"
                '  "flow_paths": [\n'
                '    {"name": "happy path", "steps": ["node_1", "node_2", "node_4"]}\n'
                "  ]\n"
                "}\n\n"
                "Extract ALL nodes and connections visible in the diagram. "
                "Use the exact text from each node/label. "
                "Return ONLY the JSON object, no extra text."
            )

            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_base64}"}},
                    ],
                }],
                max_tokens=4000,
                temperature=0.1,
            )

            raw = response.choices[0].message.content.strip()

            if "```" in raw:
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]

            graph = json.loads(raw.strip())
            graph["source"] = source

            nodes = len(graph.get("nodes", []))
            connections = len(graph.get("connections", []))
            decisions = len(graph.get("decision_points", []))
            print(f"  ✓ Diagram analyzed: {nodes} nodes, {connections} connections, {decisions} decisions")

            return graph

        except Exception as e:
            print(f"  ⚠ Diagram analysis failed for {source}: {e}")
            return self._empty_result(source, str(e))

    def convert_to_narrative(self, graph_json: Dict[str, Any]) -> str:
        if not graph_json.get("has_diagram"):
            return ""

        parts = []

        title = graph_json.get("diagram_title") or "Untitled Workflow"
        diagram_type = graph_json.get("diagram_type", "diagram")
        parts.append(f"=== WORKFLOW DIAGRAM: {title} ({diagram_type}) ===\n")

        nodes = graph_json.get("nodes", [])
        if nodes:
            parts.append("Process Steps:")
            node_map = {}
            for node in nodes:
                node_map[node["id"]] = node.get("label", node["id"])
                node_type = node.get("type", "process")
                parts.append(f"  - [{node_type.upper()}] {node.get('label', node['id'])}")
            parts.append("")

        connections = graph_json.get("connections", [])
        if connections:
            parts.append("Process Flow:")
            for conn in connections:
                from_label = node_map.get(conn["from"], conn["from"])
                to_label = node_map.get(conn["to"], conn["to"])
                arrow_label = f" ({conn['label']})" if conn.get("label") else ""
                parts.append(f"  {from_label} → {to_label}{arrow_label}")
            parts.append("")

        decisions = graph_json.get("decision_points", [])
        if decisions:
            parts.append("Decision Points:")
            for dp in decisions:
                condition = dp.get("condition", "?")
                yes_node = node_map.get(dp.get("yes_path", ""), dp.get("yes_path", "?"))
                no_node = node_map.get(dp.get("no_path", ""), dp.get("no_path", "?"))
                parts.append(f"  IF {condition}:")
                parts.append(f"    YES → {yes_node}")
                parts.append(f"    NO  → {no_node}")
            parts.append("")

        flow_paths = graph_json.get("flow_paths", [])
        if flow_paths:
            parts.append("End-to-End Paths:")
            for path in flow_paths:
                path_name = path.get("name", "unnamed")
                steps = [node_map.get(s, s) for s in path.get("steps", [])]
                parts.append(f"  [{path_name}]: {' → '.join(steps)}")
            parts.append("")

        return "\n".join(parts)

    @staticmethod
    def _empty_result(source: str, reason: str) -> Dict[str, Any]:
        return {
            "has_diagram": False,
            "diagram_type": "none",
            "diagram_title": None,
            "nodes": [],
            "connections": [],
            "decision_points": [],
            "flow_paths": [],
            "source": source,
            "error": reason,
        }
