import os
from typing import Dict, Any, Optional

from groq import Groq


class ImageClassifier:
    """Classifies images as workflow diagrams or informational images using Groq Vision."""

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

    def classify(self, image_base64: str, source: str = "unknown") -> Dict[str, Any]:
        if not self.client:
            return self._default_result(source, "No Vision LLM configured")

        try:
            prompt = (
                "Analyze this image and classify it into ONE of these categories:\n\n"
                "1. WORKFLOW — flowchart, process diagram, state diagram, or any diagram "
                "showing steps/nodes connected by arrows or flow lines.\n\n"
                "2. INFORMATIONAL — screenshot, table, chart, graph, photo, text image, "
                "UI mockup, or any other non-workflow image.\n\n"
                "Respond in EXACTLY this format (no extra text):\n"
                "TYPE: workflow OR informational\n"
                "CONFIDENCE: high OR medium OR low\n"
                "DESCRIPTION: one line describing what the image shows"
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
                max_tokens=200,
                temperature=0.1,
            )

            reply = response.choices[0].message.content.strip()
            return self._parse_classification(reply, source)

        except Exception as e:
            print(f"  ⚠ Image classification failed for {source}: {e}")
            return self._default_result(source, str(e))

    def _parse_classification(self, reply: str, source: str) -> Dict[str, Any]:
        image_type = "informational"
        confidence = "medium"
        description = ""

        for line in reply.split("\n"):
            line = line.strip()
            if line.upper().startswith("TYPE:"):
                value = line.split(":", 1)[1].strip().lower()
                image_type = "workflow" if "workflow" in value else "informational"
            elif line.upper().startswith("CONFIDENCE:"):
                value = line.split(":", 1)[1].strip().lower()
                if value in {"high", "medium", "low"}:
                    confidence = value
            elif line.upper().startswith("DESCRIPTION:"):
                description = line.split(":", 1)[1].strip()

        return {
            "image_type": image_type,
            "is_workflow": image_type == "workflow",
            "confidence": confidence,
            "description": description,
            "source": source,
            "success": True,
        }

    @staticmethod
    def _default_result(source: str, reason: str) -> Dict[str, Any]:
        return {
            "image_type": "informational",
            "is_workflow": False,
            "confidence": "low",
            "description": "",
            "source": source,
            "success": False,
            "reason": reason,
        }
