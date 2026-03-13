"""
Image Classifier Module

Classifies embedded images as either:
    - Workflow Diagram: Flowcharts, process diagrams, state diagrams, etc.
    - Informational Image: Screenshots, tables, charts, text images, etc.

This classification determines how the image content is processed:
    - Workflow diagrams → Sent to DiagramAnalyzer for structured extraction
    - Informational images → OCR text is used directly

Uses Groq's Llama 3.2 Vision model for intelligent classification.

Example:
    from extraction.processors import ImageClassifier

    classifier = ImageClassifier(groq_api_key="gsk_...")
    result = classifier.classify(image_base64)
    if result['is_workflow']:
        # Send to DiagramAnalyzer
    else:
        # Use OCR text as-is
"""

import os
from typing import Dict, Any, Optional


class ImageClassifier:
    """
    Classify images as workflow diagrams or informational images.

    Uses Groq Vision LLM to analyze the visual structure of an image
    and determine if it's a workflow/process diagram (shapes + arrows)
    or an informational image (screenshot, chart, table, etc.).

    Falls back to 'informational' classification if:
    - No API key is provided
    - The Vision API call fails
    """

    DEFAULT_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"

    def __init__(self, groq_api_key: str = None, model: str = None):
        """
        Initialize the image classifier.

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
        """Check if classification is available."""
        return self.client is not None

    def classify(self, image_base64: str, source: str = "unknown") -> Dict[str, Any]:
        """
        Classify an image as workflow diagram or informational.

        Args:
            image_base64: Base64-encoded image data
            source: Source identifier for logging (e.g., "pdf_page1_img1.png")

        Returns:
            Dictionary containing:
                - image_type: 'workflow' or 'informational'
                - is_workflow: Boolean flag
                - confidence: Classification confidence ('high', 'medium', 'low')
                - description: Brief description of what the image shows
                - success: Whether classification completed
        """
        if not self.client:
            return self._default_result(source, "No Vision LLM configured")

        try:
            prompt = (
                "Analyze this image and classify it into ONE of these categories:\n\n"
                "1. WORKFLOW — This image is a flowchart, process diagram, "
                "state diagram, activity diagram, or any diagram showing "
                "steps/nodes connected by arrows or flow lines.\n\n"
                "2. INFORMATIONAL — This image is a screenshot, table, chart, "
                "graph, photo, text image, UI mockup, or any other non-workflow image.\n\n"
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
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{image_base64}"}
                        },
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
        """Parse the Vision LLM classification response."""
        image_type = "informational"
        confidence = "medium"
        description = ""

        for line in reply.split("\n"):
            line = line.strip()
            if line.upper().startswith("TYPE:"):
                value = line.split(":", 1)[1].strip().lower()
                if "workflow" in value:
                    image_type = "workflow"
                else:
                    image_type = "informational"
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
        """Return a default classification (informational) on failure."""
        return {
            "image_type": "informational",
            "is_workflow": False,
            "confidence": "low",
            "description": "",
            "source": source,
            "success": False,
            "reason": reason,
        }
