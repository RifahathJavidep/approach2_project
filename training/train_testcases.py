"""
train_testcases.py — Train the Test Case generator.

Usage:
    python train_testcases.py --gt-dir data/groundtruth/my-project/ --req-file data/outputs/my-project/requirements.json
    python train_testcases.py --config training/config_example.yaml
    python train_testcases.py --gt-dir data/groundtruth/ --req-file data/outputs/requirements.json --output-dir data/trained_models/

What this does:
    1. Loads requirements from --req-file
    2. Loads ground truth test cases from --gt-dir
    3. Matches requirements to ground truth test cases using semantic similarity
    4. Runs DSPy BootstrapFewShot optimizer on the ScenarioGenerator
    5. Saves the trained model to --output-dir
"""

import argparse
import json
import os
import sys
import yaml

# Ensure the project root is on the path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Train the PRISM Test Case generator"
    )
    parser.add_argument(
        "--gt-dir",
        type=str,
        default=None,
        help="Path to ground truth directory (JSON files with test cases)",
    )
    parser.add_argument(
        "--req-file",
        type=str,
        default=None,
        help="Path to requirements JSON file (output from BR extraction)",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="data/trained_models/testcases/",
        help="Directory to save the trained model (default: data/trained_models/testcases/)",
    )
    parser.add_argument(
        "--lm",
        type=str,
        default=None,
        help="Language model to use, e.g. groq/llama-3.1-70b-versatile (default: from config.yaml)",
    )
    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="Path to YAML config file (alternative to CLI args, see config_example.yaml)",
    )
    return parser.parse_args()


def load_config_file(config_path: str) -> dict:
    with open(config_path, "r") as f:
        return yaml.safe_load(f)


def load_requirements(req_file: str) -> list:
    """Load requirements from a JSON file."""
    with open(req_file, "r") as f:
        data = json.load(f)
    if isinstance(data, list):
        return data
    return data.get("requirements", [])


def load_gt_test_cases(gt_dir: str) -> list:
    """Load ground truth test cases from a directory of JSON files."""
    from pathlib import Path
    gt_path = Path(gt_dir)
    all_cases = []
    for f in gt_path.glob("*.json"):
        with open(f, "r") as fp:
            data = json.load(fp)
        if isinstance(data, list):
            all_cases.extend(data)
        elif isinstance(data, dict):
            all_cases.extend(data.get("test_cases", data.get("testCases", [])))
    print(f"  Loaded {len(all_cases)} ground truth test cases from {gt_dir}")
    return all_cases


def main():
    args = parse_args()

    # Load config from file if provided, then override with CLI args
    config = {}
    if args.config:
        print(f"Loading config from: {args.config}")
        config = load_config_file(args.config)

    gt_dir = args.gt_dir or config.get("tc_ground_truth_dir") or config.get("ground_truth_dir")
    req_file = args.req_file or config.get("requirements_file")
    output_dir = args.output_dir or config.get("output_dir", "data/trained_models/testcases/")
    lm_name = args.lm or config.get("language_model")

    if not gt_dir:
        print("ERROR: --gt-dir is required (ground truth test cases directory)")
        sys.exit(1)
    if not req_file:
        print("ERROR: --req-file is required (requirements JSON file)")
        sys.exit(1)

    # Setup LM
    from dotenv import load_dotenv
    load_dotenv()

    import dspy
    from extraction.pipeline import _get_lm

    lm = _get_lm() if lm_name is None else dspy.LM(lm_name)
    dspy.configure(lm=lm)
    print(f"Using language model: {lm}")

    # Load data
    print(f"\nLoading requirements from: {req_file}")
    requirements = load_requirements(req_file)
    print(f"  Loaded {len(requirements)} requirements")

    print(f"Loading ground truth test cases from: {gt_dir}")
    gt_test_cases = load_gt_test_cases(gt_dir)

    if not requirements or not gt_test_cases:
        print("ERROR: Need both requirements and ground truth test cases to train.")
        sys.exit(1)

    # Train
    os.makedirs(output_dir, exist_ok=True)
    model_path = os.path.join(output_dir, "tc_generator.json")

    from testgen.training import train_scenario_generator

    print("\nStarting test case generator training...")
    trained = train_scenario_generator(
        requirements=requirements,
        gt_test_cases=gt_test_cases,
        documents={},
        model_save_path=model_path,
    )

    if trained:
        print(f"\nTrained model saved to: {model_path}")
        print("Done.")
    else:
        print("\nERROR: Training failed — no matching examples found between requirements and GT.")
        sys.exit(1)


if __name__ == "__main__":
    main()
