import json
import logging
import os
import dspy
from typing import Dict, Any, List

logger = logging.getLogger(__name__)

class StepExpanderSignature(dspy.Signature):
    """
    You are an expert QA Automation Engineer.
    Your task is to take a high-level test scenario and expand it into a detailed, executable click-by-click User Journey.
    
    You MUST output the steps in this specific flow:
    1. Preconditions & Login (e.g. Navigating to portal and authenticating)
    2. Navigation (exactly where to click to reach the feature)
    3. Action (the specific actions to test the scenario)
    4. Verification (asserting the expected outcomes)
    5. Cleanup (if applicable)

    Use EXACT UI element names referenced in the Document Context.
    Do not skip steps. Do not group multiple actions into one step.
    Output 10-20 granular steps.
    """
    feature_name: str = dspy.InputField(desc="The feature being tested")
    scenario_name: str = dspy.InputField(desc="The specific scenario to test")
    feature_context: str = dspy.InputField(desc="Detailed context about the feature from BR and supporting docs")
    high_level_steps: str = dspy.InputField(desc="Optional high-level steps to guide the flow")

    expanded_steps_json: str = dspy.OutputField(
        desc='JSON: {"expanded_steps":[{"step_num":1,"action":"Click on Login","expected_result":"Login page appears","test_data":""}]}'
    )

class StepExpanderModule(dspy.Module):
    def __init__(self):
        super().__init__()
        self.generate = dspy.ChainOfThought(StepExpanderSignature)
        
    def forward(self, feature_name: str, scenario_name: str, feature_context: str, high_level_steps: str = ""):
        return self.generate(
            feature_name=feature_name, 
            scenario_name=scenario_name,
            feature_context=feature_context,
            high_level_steps=high_level_steps
        )

class StepExpanderAgent:
    def __init__(self):
        # DSPy expects the LM to be configured globally, but we can ensure it here
        api_key = os.getenv('GROQ_API_KEY')
        if not api_key:
            from dotenv import load_dotenv
            load_dotenv()
            api_key = os.getenv('GROQ_API_KEY')

        from extraction.v4_utils import Config
        cfg = Config.load()
        
        lm = dspy.LM(
            model=f"groq/{cfg.get('llm', {}).get('model', 'llama-3.3-70b-versatile')}", 
            api_key=api_key,
            max_tokens=cfg.get('llm', {}).get('max_tokens', 6000),
            temperature=0.1 # Very low temp for precise steps
        )
        dspy.configure(lm=lm)
        self.expander = StepExpanderModule()

    def expand_steps(self, feature_name: str, scenario_name: str, context: str, current_steps: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        high_level = "\n".join([f"{s.get('step_num', i+1)}. {s.get('action', '')}" for i, s in enumerate(current_steps)])
        
        try:
            result = self.expander(
                feature_name=feature_name,
                scenario_name=scenario_name,
                feature_context=context[:10000],
                high_level_steps=high_level
            )
            
            cleaned_json = result.expanded_steps_json
            if '```' in cleaned_json:
                cleaned_json = cleaned_json.split('```')[1]
                if cleaned_json.startswith('json'):
                    cleaned_json = cleaned_json[4:]
            
            data = json.loads(cleaned_json.strip())
            raw_steps = data.get('expanded_steps', [])
            
            final_steps = []
            for i, s in enumerate(raw_steps, 1):
                final_steps.append({
                    "step_num": i,
                    "action": s.get('action', ''),
                    "expected_result": s.get('expected_result', ''),
                    "test_data": s.get('test_data', '')
                })
            
            if len(final_steps) > 3:
                return final_steps
            else:
                return current_steps
            
        except Exception as e:
            logger.error("Step Expander failed for %s: %s", scenario_name, e)
            return current_steps
