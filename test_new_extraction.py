"""
Test script for the new multi-layer extraction pipeline.
Tests the updated extraction/pipeline.py with 4-pass extraction.
"""

import json
import dspy
import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment
load_dotenv()

# Import our updated extraction pipeline
from extraction.pipeline import ExtractionPipeline

def main():
    # Configure DSPy LLM
    groq_key = os.getenv("GROQ_API_KEY")
    if not groq_key:
        raise ValueError("GROQ_API_KEY not found in .env")

    lm = dspy.LM('groq/llama-3.3-70b-versatile', api_key=groq_key)
    dspy.configure(lm=lm)

    # Load config
    config_file = Path("config/config.json")
    with open(config_file) as f:
        config = json.load(f)

    # Override to use crm_cloud project
    current_project = 'crm_cloud'
    project_config = config['projects'][current_project]

    input_dir = Path(project_config['input_dir'])
    output_dir = Path('outputs/output-crm-03')  # New output directory for new extraction
    output_dir.mkdir(exist_ok=True, parents=True)

    # Find input files
    pdf_files = sorted(input_dir.glob('*.pdf'))
    skip_patterns = ['about.txt']
    filtered_files = [f for f in pdf_files if not any(pat in f.name.lower() for pat in skip_patterns)]

    print("=" * 80)
    print("MULTI-LAYER EXTRACTION TEST - CRM Cloud")
    print("=" * 80)
    print(f"\nProject: {current_project}")
    print(f"Input dir: {input_dir}")
    print(f"Files to process: {len(filtered_files)}")
    for f in filtered_files:
        print(f"  - {f.name}")
    print()

    # Initialize the updated pipeline
    print("Initializing extraction pipeline with multi-layer architecture...")
    pipeline = ExtractionPipeline(config)

    # Run extraction (this will use our new 4-pass extraction)
    result_data = pipeline.run(
        file_paths=[str(f) for f in filtered_files],
        project_name=current_project,
        output_dir=str(output_dir)
    )

    # Get requirements from result
    requirements = result_data['requirements']
    for i, req in enumerate(requirements, 1):
        req['requirement_id'] = f"{current_project.upper().replace(' ', '_')}-{i:03d}"

    final_result = {
        'project': current_project,
        'requirements': requirements
    }

    # Save results
    output_file = output_dir / f"{current_project}_requirements.json"
    with open(output_file, 'w') as f:
        json.dump(final_result, f, indent=2)

    print(f"\n{'=' * 80}")
    print("EXTRACTION COMPLETE")
    print(f"{'=' * 80}")
    print(f"Total requirements extracted: {len(requirements)}")
    print(f"Saved to: {output_file}")

    # Print breakdown by type
    type_counts = {}
    for req in requirements:
        req_type = req.get('type', 'Unknown')
        type_counts[req_type] = type_counts.get(req_type, 0) + 1

    print(f"\nBreakdown by type:")
    for req_type, count in sorted(type_counts.items(), key=lambda x: -x[1]):
        print(f"  {req_type}: {count}")

    print(f"\nReady for evaluation!")
    print(f"Run: python evaluate.py (after updating config.json to set current_project = 'crm_cloud')")

if __name__ == "__main__":
    main()
