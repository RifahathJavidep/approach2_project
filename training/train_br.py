"""
train_br.py — Train the Business Requirement (BR) extractor.

Usage:
    python train_br.py --gt-dir data/groundtruth/my-project/
    python train_br.py --config training/config_example.yaml
    python train_br.py --gt-dir data/groundtruth/ --output-dir data/trained_models/ --lm groq/llama-3.1-70b-versatile

What this does:
    1. Loads pattern-based positive and negative training examples (built-in)
    2. Optionally loads ground truth requirements from --gt-dir
    3. Runs DSPy BootstrapFewShot optimizer on the BR classifier
    4. Saves the trained model to --output-dir
"""

import argparse
import os
import sys
import yaml

# Ensure the project root is on the path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Train the PRISM Business Requirement (BR) extractor"
    )
    parser.add_argument(
        "--gt-dir",
        type=str,
        default=None,
        help="Path to ground truth directory (JSON or Excel files with requirements)",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="data/trained_models/br/",
        help="Directory to save the trained model (default: data/trained_models/br/)",
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
    parser.add_argument(
        "--project-dir",
        type=str,
        default=None,
        help="Path to project PDF documents directory (used for multi-project training)",
    )
    return parser.parse_args()


def load_config_file(config_path: str) -> dict:
    with open(config_path, "r") as f:
        return yaml.safe_load(f)


def main():
    args = parse_args()

    # Load config from file if provided, then override with CLI args
    config = {}
    if args.config:
        print(f"Loading config from: {args.config}")
        config = load_config_file(args.config)

    gt_dir = args.gt_dir or config.get("ground_truth_dir")
    output_dir = args.output_dir or config.get("output_dir", "data/trained_models/br/")
    lm_name = args.lm or config.get("language_model")
    project_dir = args.project_dir or config.get("documents_dir")

    # Setup LM
    from dotenv import load_dotenv
    load_dotenv()

    import dspy
    from extraction.pipeline import _get_lm

    lm = _get_lm() if lm_name is None else dspy.LM(lm_name)
    dspy.configure(lm=lm)
    print(f"Using language model: {lm}")

    # Build training config
    train_config = {}
    if gt_dir:
        train_config["gt_dir"] = gt_dir
        print(f"Ground truth directory: {gt_dir}")
    if project_dir:
        train_config["projects"] = {"current": {"input_dir": project_dir}}
        train_config["current_project"] = "current"

    # Load and train extractor
    from extraction.generators.trained_extractor import TrainedExtractor
    from extraction.generators.training import train_extractor

    print("\nInitializing BR extractor...")
    extractor = TrainedExtractor()

    print("Starting training...")
    trained = train_extractor(extractor, config=train_config if train_config else None)

    # Save trained model
    os.makedirs(output_dir, exist_ok=True)
    model_path = os.path.join(output_dir, "br_extractor.json")
    trained.save(model_path)
    print(f"\nTrained model saved to: {model_path}")
    print("Done.")


if __name__ == "__main__":
    main()
