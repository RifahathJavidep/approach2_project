"""
Diagram Analyzer Module

Extracts structured information from workflow diagrams using Groq Vision LLM.
Converts flowcharts, process diagrams, and state diagrams into:
    1. Graph JSON: Nodes, connections, decision points, flow paths
    2. Text Narrative: Readable text description of the workflow

The text narrative is then combined with document text and sent to
the DSPy requirement extractor.

Adapted from: ai_test_case/test_case_generator/processors/diagram_processor.py

Example:
    from extraction.processors import DiagramAnalyzer

    analyzer = DiagramAnalyzer(groq_api_key="gsk_...")
    graph = analyzer.extract_graph_json(image_base64)
    narrative = analyzer.convert_to_narrative(graph)
"""

import json
import os
from typing import Dict, Any, List, Optional

class DiagramAnalyzer:
    """
    Extract structured workflow information from diagram images.

    Uses Groq's Llama 3.2 Vision model to analyze workflow diagrams
    and extract:
    - Nodes (steps, actions, processes)
    - Connections (flows between nodes)
    - Decision points (branches, conditions)
    - Flow paths (start-to-end sequences)

    The extracted structure is then converted to a text narrative
    suitable for downstream AI processing (DSPy requirement extraction).
    """

    DEFAULT_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"

    def __init__(self, groq_api_key: str = None, model: str = None):
        """
        Initialize the diagram analyzer.

        Args:
            groq_api_key: Groq API key for Vision model access.
                          Falls back to GROQ_API_KEY env var.
            model: Vision model to use
        """
        self.client = None
        self.model = model or self.DEFAULT_MODEL

        api_key = groq_api_key or os.getenv("GROQ_API_KEY")

        if api_key:
            try:
                from groq import Groq
                self.client = Groq(
                    api_key=api_key,
                )
                # Test connection by making a dummy call
                self.client.models.list()
            except Exception as e:
                self.client = None
                if not isinstance(e, ImportError):
                    print(f"  ⚠ Groq initialization failed (check API key): {e}")

    @property
    def is_available(self) -> bool:
        """Check if diagram analysis is available."""
        return self.client is not None

    def extract_graph_json(self, image_base64: str, source: str = "diagram") -> Dict[str, Any]:
        """
        Extract the complete diagram structure as a graph JSON.

        Sends the diagram image to Groq Vision LLM and extracts all
        nodes, connections, decision points, and flow paths.

        Args:
            image_base64: Base64-encoded diagram image
            source: Source identifier for logging

        Returns:
            Dictionary containing:
                - has_diagram: Whether a diagram was detected
                - diagram_type: Type (flowchart, process, state, etc.)
                - diagram_title: Title if visible
                - nodes: List of nodes with id, label, type
                - connections: List of connections between nodes
                - decision_points: List of branching conditions
                - flow_paths: List of start-to-end paths
                - source: Source identifier
        """
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
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{image_base64}"}
                        },
                    ],
                }],
                max_tokens=4000,
                temperature=0.1,
            )

            raw = response.choices[0].message.content.strip()

            # Handle markdown-wrapped JSON
            if "```" in raw:
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]

            graph = json.loads(raw.strip())
            graph["source"] = source

            # Log summary
            nodes = len(graph.get("nodes", []))
            connections = len(graph.get("connections", []))
            decisions = len(graph.get("decision_points", []))
            print(f"  ✓ Diagram analyzed: {nodes} nodes, {connections} connections, {decisions} decisions")

            return graph

        except Exception as e:
            print(f"  ⚠ Diagram analysis failed for {source}: {e}")
            return self._empty_result(source, str(e))

    def convert_to_narrative(self, graph_json: Dict[str, Any]) -> str:
        """
        Convert diagram graph JSON into a readable text narrative.

        Creates a sequential description of the workflow that can be
        processed by the DSPy requirement extractor, including:
        - Diagram title and type
        - Step-by-step process flow
        - Decision points and their branches
        - All flow paths

        Args:
            graph_json: Graph structure from extract_graph_json()

        Returns:
            Human-readable text narrative of the workflow
        """
        if not graph_json.get("has_diagram"):
            return ""

        parts = []

        # Title
        title = graph_json.get("diagram_title") or "Untitled Workflow"
        diagram_type = graph_json.get("diagram_type", "diagram")
        parts.append(f"=== WORKFLOW DIAGRAM: {title} ({diagram_type}) ===\n")

        # Nodes summary
        nodes = graph_json.get("nodes", [])
        if nodes:
            parts.append("Process Steps:")
            node_map = {}
            for node in nodes:
                node_map[node["id"]] = node.get("label", node["id"])
                node_type = node.get("type", "process")
                parts.append(f"  - [{node_type.upper()}] {node.get('label', node['id'])}")
            parts.append("")

        # Connections (flow)
        connections = graph_json.get("connections", [])
        if connections:
            parts.append("Process Flow:")
            for conn in connections:
                from_label = node_map.get(conn["from"], conn["from"])
                to_label = node_map.get(conn["to"], conn["to"])
                arrow_label = f" ({conn['label']})" if conn.get("label") else ""
                parts.append(f"  {from_label} → {to_label}{arrow_label}")
            parts.append("")

        # Decision points
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

        # Flow paths
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
        """Return an empty diagram result."""
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
