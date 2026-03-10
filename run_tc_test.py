import json
import os
import logging
from pathlib import Path
from testgen.pipeline import TestGenPipeline

# Setup basic logging to see the process
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

def run_test():
    # 1. Load the existing requirements JSON
    req_file = "/Users/javid/Documents/prism/approach2_project/requirements_20260309_232925.json"
    if not os.path.exists(req_file):
        print(f"Error: Requirement file {req_file} not found.")
        return

    with open(req_file, 'r') as f:
        data = json.load(f)
    
    # 2. Pick only the first 2 requirements for a quick demo
    all_requirements = data.get('requirements', [])
    if not all_requirements:
        print("No requirements found.")
        return
        
    test_requirements = all_requirements[:2]
    print(f"Running TC generation for: {[r.get('feature_name') for r in test_requirements]}")

    # 3. Path to the documents for context
    doc_paths = [
        "/Users/javid/Documents/prism/approach2_project/inputs/Play to Win SS Ph1 - Dashboard_Features.pdf",
        "/Users/javid/Documents/prism/approach2_project/inputs/Play to Win SS Ph1 - Warranty_Feature.pdf"
    ]

    # 4. Initialize the pipeline
    # Mode: 'hybrid' triggers our newly updated ScenarioBasedTCGenerator
    pipeline = TestGenPipeline(mode='hybrid')

    # 5. Run the pipeline
    output_dir = "/Users/javid/Documents/prism/approach2_project/output/test_run_new_code"
    result = pipeline.run(
        requirements=test_requirements,
        project_name="ptw_new_code_test",
        output_dir=output_dir,
        document_paths=doc_paths
    )

    print("\n" + "="*60)
    print("TC GENERATION TEST COMPLETE!")
    print(f"JSON Output: {result.get('json_path')}")
    print(f"Excel Output: {result.get('excel_path')}")
    print("="*60)

    # 6. Show a snippet of the first test case generated
    with open(result.get('json_path'), 'r') as f:
        gen_data = json.load(f)
        
    if gen_data.get('test_plans'):
        first_plan = gen_data['test_plans'][0]
        print(f"\nExample Generated TC for Feature: {first_plan.get('requirement_title')}")
        for tc in first_plan.get('test_cases', [])[:1]:
            print(f"TC ID: {tc.get('test_case_id')}")
            print(f"Description: {tc.get('description')}")
            print("Steps:")
            for s in tc.get('steps', []):
                print(f"  {s.get('step_num')}. {s.get('action')} -> {s.get('expected_result')}")

if __name__ == "__main__":
    run_test()
