"""
Universal evaluation script for any project.

Usage:
    python3 run_evaluation.py <project_name>
    python3 run_evaluation.py fintech_app
    python3 run_evaluation.py all  # Evaluate all projects
"""

import sys
import json
import dspy
import os
import openpyxl
from pathlib import Path
from typing import List, Dict
from dotenv import load_dotenv

# Load environment
load_dotenv()

# Import from evaluate.py
from evaluate import load_ground_truth, evaluate, _get_lm

def run_evaluation_for_project(project_name: str, config: dict):
    """Run evaluation for a single project."""

    if project_name not in config['projects']:
        print(f"❌ ERROR: Project '{project_name}' not found in config.")
        return None

    project_config = config['projects'][project_name]
    output_dir = Path(config.get('output_dir', 'output'))

    # Check ground truth
    gt_path = project_config.get('ground_truth')
    if not gt_path:
        print(f"⚠️  No ground truth file configured for '{project_name}' - skipping evaluation")
        return None

    gt_file = Path(gt_path)
    req_file = output_dir / f"{project_name}_requirements.json"

    if not gt_file.exists():
        print(f"❌ ERROR: Ground truth not found: {gt_file}")
        return None

    if not req_file.exists():
        print(f"❌ ERROR: Requirements not found: {req_file}")
        print(f"Run extraction first: python3 run_extraction.py {project_name}")
        return None

    print("=" * 80)
    print(f"EVALUATION - {project_name.upper().replace('_', ' ')}")
    print("=" * 80)

    # Load
    print(f"\nProject: {project_name}")
    print(f"Loading ground truth: {gt_file}")
    ground_truth = load_ground_truth(str(gt_file))
    print(f"Loaded {len(ground_truth)} ground truth requirements")

    print(f"\nLoading extracted requirements: {req_file}")
    with open(req_file) as f:
        data = json.load(f)
        extracted = data['requirements']
    print(f"Loaded {len(extracted)} extracted requirements")

    # Evaluate
    print(f"\nEvaluating...")
    evaluation = evaluate(extracted, ground_truth)

    # Print results
    print(f"\n{'=' * 80}")
    print("RESULTS:")
    print(f"{'=' * 80}")
    metrics = evaluation['metrics']
    counts = evaluation['counts']

    print(f"Precision:  {metrics['precision']:.2%}")
    print(f"Recall:     {metrics['recall']:.2%}")
    print(f"F1 Score:   {metrics['f1_score']:.2%}")
    print(f"")
    print(f"Ground Truth:      {counts['gt']}")
    print(f"Extracted:         {counts['extracted']}")
    print(f"True Positives:    {counts['true_positives']}")
    print(f"False Negatives:   {counts['false_negatives']} (missed)")
    print(f"False Positives:   {counts['false_positives']} (over-extracted)")
    print(f"{'=' * 80}")

    # Save
    eval_file = output_dir / f"{project_name}_evaluation.json"
    with open(eval_file, 'w') as f:
        json.dump(evaluation, f, indent=2)

    print(f"\nSaved to: {eval_file}")

    return {
        'project': project_name,
        'precision': metrics['precision'],
        'recall': metrics['recall'],
        'f1_score': metrics['f1_score'],
        'gt': counts['gt'],
        'extracted': counts['extracted'],
        'tp': counts['true_positives'],
        'fn': counts['false_negatives'],
        'fp': counts['false_positives']
    }

def main():
    # Configure DSPy LLM for semantic matching
    lm = _get_lm()
    dspy.configure(lm=lm)

    # Load config
    config_file = Path("config/config.json")
    with open(config_file) as f:
        config = json.load(f)

    # Get project name from command line
    if len(sys.argv) < 2:
        print("Usage: python3 run_evaluation.py <project_name>")
        print(f"\nAvailable projects:")
        for proj in config['projects'].keys():
            print(f"  - {proj}")
        print(f"\nOr use 'all' to evaluate all projects:")
        print(f"  python3 run_evaluation.py all")
        sys.exit(1)

    project_arg = sys.argv[1]

    if project_arg.lower() == 'all':
        # Evaluate all projects
        print("\n📊 Running evaluation on ALL projects...\n")
        results = []
        for project_name in config['projects'].keys():
            result = run_evaluation_for_project(project_name, config)
            if result:
                results.append(result)
            print("\n" + "=" * 80 + "\n")

        # Summary table
        print("\n" + "=" * 80)
        print("SUMMARY - ALL PROJECTS")
        print("=" * 80)
        print(f"{'Project':<20} {'F1':<8} {'Prec':<8} {'Rec':<8} {'GT':<6} {'Ext':<6} {'TP':<6} {'FN':<6} {'FP':<6}")
        print("-" * 80)
        for result in results:
            print(f"{result['project']:<20} "
                  f"{result['f1_score']:<8.2%} "
                  f"{result['precision']:<8.2%} "
                  f"{result['recall']:<8.2%} "
                  f"{result['gt']:<6} "
                  f"{result['extracted']:<6} "
                  f"{result['tp']:<6} "
                  f"{result['fn']:<6} "
                  f"{result['fp']:<6}")

        # Overall statistics
        avg_f1 = sum(r['f1_score'] for r in results) / len(results)
        avg_precision = sum(r['precision'] for r in results) / len(results)
        avg_recall = sum(r['recall'] for r in results) / len(results)

        print("-" * 80)
        print(f"{'AVERAGE':<20} {avg_f1:<8.2%} {avg_precision:<8.2%} {avg_recall:<8.2%}")
        print("=" * 80)

        # Target achievement
        projects_above_80 = sum(1 for r in results if r['f1_score'] >= 0.80)
        print(f"\n✅ Projects with F1 ≥ 0.80: {projects_above_80}/{len(results)}")
        if projects_above_80 == len(results):
            print("🎉 TARGET ACHIEVED! All projects have F1 ≥ 0.80!")
        else:
            below_80 = [r for r in results if r['f1_score'] < 0.80]
            print(f"\n⚠️  Projects below target:")
            for r in below_80:
                gap = 0.80 - r['f1_score']
                print(f"  - {r['project']}: F1={r['f1_score']:.2%} (gap: {gap:.2%})")

    else:
        # Evaluate single project
        result = run_evaluation_for_project(project_arg, config)
        if result:
            print(f"\n✅ Evaluation complete!")
            if result['f1_score'] >= 0.80:
                print(f"🎉 TARGET ACHIEVED! F1 Score: {result['f1_score']:.2%}")
            else:
                gap = 0.80 - result['f1_score']
                print(f"⚠️  Below target. F1: {result['f1_score']:.2%} (gap: {gap:.2%})")

if __name__ == "__main__":
    main()
