import re
import json
import logging
import os
import dspy
from pathlib import Path
from typing import List, Dict, Any, Optional

logger = logging.getLogger("prism.testcase_engine.scenario")

class ScenarioTestCaseSignature(dspy.Signature):
    """Generate a COMPLETE E2E test case for ONE SPECIFIC scenario of a feature.

    You are testing ONE scenario variant (e.g., "Data Tab" or "Export to CSV").
    Generate 8-20 detailed steps covering the full user journey for THIS scenario only.

    Each step must be specific:
    - Reference exact UI elements (button names, tab labels, column headers, URLs)
    - Include specific test data values where applicable
    - Include verification/assertion steps with expected outcomes
    - Cover login -> navigation -> action -> verification -> cleanup

    All arrays must contain STRINGS only, not objects.
    """
    feature_name: str = dspy.InputField(desc="Parent feature name")
    scenario_name: str = dspy.InputField(desc="Specific scenario being tested")
    feature_description: str = dspy.InputField(desc="Feature description")
    acceptance_criteria: str = dspy.InputField(desc="Acceptance criteria relevant to this scenario")
    scenario_steps_hint: str = dspy.InputField(desc="BR-extracted step hints for this scenario")
    document_context: str = dspy.InputField(desc="Source document text for this feature")

    test_case_json: str = dspy.OutputField(
        desc='JSON: {"description":"E2E test for [scenario] of [feature]","preconditions":["str1"],"expected_result":"overall success outcome","steps":[{"step_num":1,"action":"specific action","expected_result":"specific expected outcome","test_data":"relevant data"}]}'
    )

class ScenarioGeneratorModule(dspy.Module):
    def __init__(self):
        super().__init__()
        self.generate = dspy.ChainOfThought(ScenarioTestCaseSignature)

    def forward(self, feature_name, scenario_name, feature_description,
                acceptance_criteria, scenario_steps_hint, document_context):
        return self.generate(
            feature_name=feature_name, scenario_name=scenario_name,
            feature_description=feature_description,
            acceptance_criteria=acceptance_criteria,
            scenario_steps_hint=scenario_steps_hint,
            document_context=document_context
        )

class ScenarioBasedTCGenerator:
    """
    New_code v4.0 style TC generator.
    Direct LLM generation based on requirement context and scenario hints.
    """
    
    def __init__(self, model_state_path: Optional[str] = None):
        # 1. Initialize DSPy (New_code v4.0 standard)
        api_key = os.getenv('GROQ_API_KEY')
        if not api_key:
            from dotenv import load_dotenv
            load_dotenv()
            api_key = os.getenv('GROQ_API_KEY')

        # Load config to get model settings
        from requirement_engine.v4_utils import Config
        cfg = Config.load()
        
        lm = dspy.LM(
            model=f"groq/{cfg.get('llm', {}).get('model', 'llama-3.3-70b-versatile')}", 
            api_key=api_key,
            max_tokens=cfg.get('llm', {}).get('max_tokens', 8000),
            temperature=cfg.get('llm', {}).get('temperature', 0.3)
        )
        dspy.configure(lm=lm)
        
        self.generator = ScenarioGeneratorModule()
        
        if model_state_path and Path(model_state_path).exists():
            try:
                self.generator.load(model_state_path)
                logger.info("Loaded trained ScenarioGenerator model from %s", model_state_path)
            except Exception as e:
                logger.warning("Failed to load model state: %s", e)

    def generate_for_scenario(self, req: Dict[str, Any], scenario_name: str, context: str) -> Dict[str, Any]:
        """Generate a single test case for a specific scenario using New_code logic."""
        feature = req.get('feature_name', '')
        desc = req.get('description', '')
        
        # Extract scenario-specific AC and steps hint from the requirement
        ac_list = req.get('acceptance_criteria', [])
        ac_str = "\n".join(ac_list) if isinstance(ac_list, list) else str(ac_list)
        
        # Get hints from existing test steps if they match the scenario
        hints = []
        for s in req.get('test_steps', []):
            if isinstance(s, dict):
                action = s.get('action', '')
                tdata = s.get('test_data', '')
                if scenario_name.lower() in str(tdata).lower() or scenario_name.lower() in str(action).lower():
                    hints.append(f"{s.get('step_num', '')}: {action}")
        
        steps_hint = "\n".join(hints) if hints else "Generate comprehensive E2E steps."

        try:
            result = self.generator(
                feature_name=feature,
                scenario_name=scenario_name,
                feature_description=desc,
                acceptance_criteria=ac_str,
                scenario_steps_hint=steps_hint,
                document_context=context[:8000]
            )
            
            # Helper to safely parse JSON
            cleaned_json = result.test_case_json
            if '```' in cleaned_json:
                cleaned_json = cleaned_json.split('```')[1]
                if cleaned_json.startswith('json'):
                    cleaned_json = cleaned_json[4:]
            
            data = json.loads(cleaned_json.strip())
            
            # Post-process steps to ensure they are TestStep-like objects
            raw_steps = data.get('steps', [])
            final_steps = []
            for i, s in enumerate(raw_steps, 1):
                final_steps.append({
                    "step_num": i,
                    "action": s.get('action', ''),
                    "expected_result": s.get('expected_result', ''),
                    "test_data": s.get('test_data', '')
                })

            return {
                "description": data.get('description', f"E2E test for {scenario_name} of {feature}"),
                "preconditions": data.get('preconditions', ["User is logged into the system"]),
                "expected_result": data.get('expected_result', "Test executed successfully"),
                "steps": final_steps
            }
            
        except Exception as e:
            logger.error("LLM Generation failed for scenario %s: %s", scenario_name, e)
            return {
                "description": f"Verify {feature} functionality for {scenario_name}",
                "preconditions": ["User is logged into the system"],
                "steps": [
                    {"step_num": 1, "action": f"Navigate to {feature}", "expected_result": "Feature is visible", "test_data": ""},
                    {"step_num": 2, "action": f"Execute {scenario_name}", "expected_result": "Successful execution", "test_data": ""}
                ]
            }
