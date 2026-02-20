"""
Universal test script for multi-layer extraction on any project.

Usage:
    python3 run_extraction.py <project_name>
    python3 run_extraction.py fintech_app
    python3 run_extraction.py healthcare_portal
    python3 run_extraction.py all  # Run on all projects
"""

import sys
import json
import dspy
import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment
load_dotenv()

# Import our updated extraction pipeline
from extraction.pipeline import ExtractionPipeline

def run_extraction_for_project(project_name: str, config: dict):
    """Run extraction for a single project."""

    if project_name not in config['projects']:
        print(f"❌ ERROR: Project '{project_name}' not found in config.")
        print(f"Available projects: {', '.join(config['projects'].keys())}")
        return None

    project_config = config['projects'][project_name]
    input_dir = Path(project_config['input_dir'])

    if not input_dir.exists():
        print(f"❌ ERROR: Input directory not found: {input_dir}")
        return None

    # Output to dedicated directory for this run
    output_dir = Path(f'outputs/output-{project_name}-new')
    output_dir.mkdir(exist_ok=True, parents=True)

    # Find input files
    pdf_files = sorted(input_dir.glob('*.pdf'))
    pptx_files = sorted(input_dir.glob('*.pptx'))
    all_files = pdf_files + pptx_files

    skip_patterns = ['about.txt', 'test_strategy', 'test strategy', 'traceability']
    filtered_files = [f for f in all_files if not any(pat in f.name.lower() for pat in skip_patterns)]

    if not filtered_files:
        print(f"❌ ERROR: No PDF/PPTX files found in {input_dir}")
        return None

    print("=" * 80)
    print(f"MULTI-LAYER EXTRACTION - {project_name.upper().replace('_', ' ')}")
    print("=" * 80)
    print(f"\nProject: {project_name}")
    print(f"Input dir: {input_dir}")
    print(f"Files to process: {len(filtered_files)}")
    for f in filtered_files:
        print(f"  - {f.name}")
    print()

    # Initialize the updated pipeline
    print("Initializing extraction pipeline...")
    pipeline = ExtractionPipeline(config)

    # Run extraction
    result_data = pipeline.run(
        file_paths=[str(f) for f in filtered_files],
        project_name=project_name,
        output_dir=str(output_dir)
    )

    # Get requirements from result
    requirements = result_data['requirements']
    for i, req in enumerate(requirements, 1):
        req['requirement_id'] = f"{project_name.upper().replace(' ', '_')}-{i:03d}"

    final_result = {
        'project': project_name,
        'requirements': requirements
    }

    # Save results
    output_file = output_dir / f"{project_name}_requirements.json"
    with open(output_file, 'w') as f:
        json.dump(final_result, f, indent=2)

    # Also copy to standard output directory for evaluation
    standard_output = Path('output')
    standard_output.mkdir(exist_ok=True)
    standard_output_file = standard_output / f"{project_name}_requirements.json"
    with open(standard_output_file, 'w') as f:
        json.dump(final_result, f, indent=2)

    print(f"\n{'=' * 80}")
    print("EXTRACTION COMPLETE")
    print(f"{'=' * 80}")
    print(f"Total requirements extracted: {len(requirements)}")
    print(f"Saved to: {output_file}")
    print(f"Also saved to: {standard_output_file} (for evaluation)")

    # Print breakdown by type
    type_counts = {}
    for req in requirements:
        req_type = req.get('type', 'Unknown')
        type_counts[req_type] = type_counts.get(req_type, 0) + 1

    print(f"\nBreakdown by type:")
    for req_type, count in sorted(type_counts.items(), key=lambda x: -x[1]):
        print(f"  {req_type}: {count}")

    return {
        'project': project_name,
        'total': len(requirements),
        'types': type_counts,
        'output_file': str(output_file)
    }

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

    # Get project name from command line
    if len(sys.argv) < 2:
        print("Usage: python3 run_extraction.py <project_name>")
        print(f"\nAvailable projects:")
        for proj in config['projects'].keys():
            print(f"  - {proj}")
        print(f"\nOr use 'all' to run on all projects:")
        print(f"  python3 run_extraction.py all")
        sys.exit(1)

    project_arg = sys.argv[1]

    if project_arg.lower() == 'all':
        # Run on all projects
        print("\n🚀 Running extraction on ALL projects...\n")
        results = []
        for project_name in config['projects'].keys():
            result = run_extraction_for_project(project_name, config)
            if result:
                results.append(result)
            print("\n" + "=" * 80 + "\n")

        # Summary
        print("\n" + "=" * 80)
        print("SUMMARY - ALL PROJECTS")
        print("=" * 80)
        for result in results:
            print(f"\n{result['project']}:")
            print(f"  Total: {result['total']} requirements")
            print(f"  Types: {', '.join(f'{k}={v}' for k, v in result['types'].items())}")
    else:
        # Run on single project
        result = run_extraction_for_project(project_arg, config)
        if result:
            print(f"\n✅ Ready for evaluation!")
            print(f"To evaluate, run:")
            print(f"  1. Update config.json: set 'current_project' to '{project_arg}'")
            print(f"  2. Run: python3 evaluate.py")

if __name__ == "__main__":
    main()
