"""
Precision Pipeline Runner
=========================
Runs the full pipeline in PRECISION MODE:
  Step 1 — Extract requirements from documents
  Step 2 — Generate test cases
  Step 3 — Evaluate against ground truth and show score

Usage:
    venv/bin/python run_precision_pipeline.py
"""

import json
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

# ─── CONFIG — edit these paths if needed ─────────────────────────────────────

INPUT_FILES = [
    "inputs/Play to Win SS Ph1 - Dashboard_Features.pdf",
    "inputs/Play to Win SS Ph1 - Warranty_Feature.pdf",
    "inputs/PTW Self Serve Phase 1 Solution.pdf",
]

PROJECT_NAME      = "inuts"
REQUIREMENTS_OUT  = "output/inuts/requirements"
TESTCASES_OUT     = "output/inuts/testcases"
GT_DIR            = "groundtruth"
EVAL_OUT          = "evaluation/results/precision_eval.json"

# ─────────────────────────────────────────────────────────────────────────────


def step1_extract():
    print("\n" + "=" * 60)
    print("  STEP 1 — EXTRACT REQUIREMENTS (PRECISION MODE)")
    print("=" * 60)

    from extraction.pipeline import extract_from_files

    result = extract_from_files(
        project_name=PROJECT_NAME,
        file_paths=INPUT_FILES,
        output_dir=REQUIREMENTS_OUT,
        precision_mode=True,
    )

    reqs = result.get("requirements", [])
    print(f"\n  Done — {len(reqs)} requirements extracted")
    print(f"  Saved to: {REQUIREMENTS_OUT}/{PROJECT_NAME}_requirements.json")
    return reqs


def step2_generate(requirements):
    print("\n" + "=" * 60)
    print("  STEP 2 — GENERATE TEST CASES (PRECISION MODE)")
    print("=" * 60)

    from testgen.pipeline import TestGenPipeline

    pipeline = TestGenPipeline()
    result = pipeline.run(
        requirements=requirements,
        project_name=PROJECT_NAME,
        output_dir=TESTCASES_OUT,
        document_paths=INPUT_FILES,   # inject source docs for richer steps
        precision_mode=True,
    )

    print(f"\n  Done — {result['total_test_cases']} test cases generated")
    print(f"  JSON : {result['json_path']}")
    print(f"  Excel: {result['excel_path']}")
    return result


def step3_evaluate():
    print("\n" + "=" * 60)
    print("  STEP 3 — EVALUATE AGAINST GROUND TRUTH")
    print("=" * 60)

    from evaluation.run_evaluation import run_evaluation

    req_path = f"{REQUIREMENTS_OUT}/{PROJECT_NAME}_requirements.json"
    tc_path  = f"{TESTCASES_OUT}/{PROJECT_NAME}_test_plan.json"

    run_evaluation(
        requirements_path=req_path,
        test_plan_path=tc_path,
        gt_dir=GT_DIR,
        output_path=EVAL_OUT,
        verbose=True,
    )


if __name__ == "__main__":
    print("\n" + "█" * 60)
    print("  PRECISION PIPELINE — Play to Win (PTW)")
    print("█" * 60)

    # Step 1 — Extract
    requirements = step1_extract()

    if not requirements:
        print("\n  No requirements extracted. Check your input files.")
        sys.exit(1)

    # Step 2 — Generate test cases
    step2_generate(requirements)

    # Step 3 — Evaluate
    step3_evaluate()

    print("\n" + "█" * 60)
    print("  PIPELINE COMPLETE")
    print("█" * 60 + "\n")
