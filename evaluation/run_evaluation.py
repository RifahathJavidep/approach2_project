"""
Evaluation Runner — CLI for measuring extraction & generation quality

Compares generated requirements / test cases against ground truth Excel files
and prints a detailed report with Precision / Recall / F1 / Step Accuracy.

Usage:
    # Evaluate both requirements and test plan
    python -m evaluation.run_evaluation \
        --requirements output/inuts/requirements/inuts_requirements.json \
        --test-plan    output/inuts/testcases/inuts_test_plan.json \
        --gt-dir       groundtruth \
        --output       evaluation/results/inuts_eval.json

    # Evaluate only test plan (when requirements GT is not available)
    python -m evaluation.run_evaluation \
        --test-plan output/inuts/testcases/inuts_test_plan.json

    # Quiet mode (just the numbers)
    python -m evaluation.run_evaluation \
        --requirements output/inuts/requirements/inuts_requirements.json \
        --quiet
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional

# Allow running as both `python evaluation/run_evaluation.py` and
# `python -m evaluation.run_evaluation` from the project root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from evaluation.gt_evaluator import RequirementEvaluator, TestCaseEvaluator
from extraction.groundtruth_loader import GroundTruthLoader


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _load_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _bar(value: float, width: int = 30) -> str:
    """ASCII progress bar for 0–1 values."""
    filled = int(value * width)
    return "[" + "█" * filled + "░" * (width - filled) + f"] {value:.1%}"


def _section(title: str, width: int = 62):
    print(f"\n{'═' * width}")
    print(f"  {title}")
    print(f"{'═' * width}")


def _metric_row(label: str, value: float, extra: str = ""):
    bar = _bar(value)
    print(f"  {label:<22} {bar}  {extra}")


# ─────────────────────────────────────────────────────────────────────────────
# Core evaluation function
# ─────────────────────────────────────────────────────────────────────────────

def run_evaluation(
    requirements_path: Optional[str] = None,
    test_plan_path: Optional[str] = None,
    gt_dir: str = "groundtruth",
    output_path: Optional[str] = None,
    verbose: bool = True,
) -> Dict:
    """
    Run full evaluation of extracted requirements and/or generated test plan.

    Args:
        requirements_path: Path to extracted requirements JSON
                           (output of ExtractionPipeline.run())
        test_plan_path:    Path to generated test plan JSON
                           (output of TestCasePlanner.generate())
        gt_dir:            Directory containing GT Excel files
        output_path:       Optional path to save full evaluation JSON
        verbose:           Print detailed report to stdout

    Returns:
        Evaluation result dict with 'requirement_evaluation' and/or
        'test_case_evaluation' keys.
    """
    results: Dict = {}

    # 1. Load ground truth ────────────────────────────────────────────────────
    _section("Loading Ground Truth")
    loader = GroundTruthLoader(gt_dir=gt_dir)
    gt_data = loader.load_all()

    gt_requirements: List[Dict] = gt_data.get("requirements", [])
    gt_test_cases: List[Dict] = gt_data.get("test_cases", [])

    if not gt_requirements and not gt_test_cases:
        print(
            "\n  ⚠ No ground truth loaded — nothing to compare against.\n"
            "    Make sure the groundtruth/ directory contains .xlsx files."
        )
        return results

    # 2. Requirement evaluation ───────────────────────────────────────────────
    if requirements_path and Path(requirements_path).exists():
        _section("Requirement Extraction Evaluation")
        req_data = _load_json(requirements_path)
        extracted_reqs: List[Dict] = req_data.get("requirements", [])

        if not gt_requirements:
            print("  ⚠ No GT requirements loaded — skipping requirement evaluation")
        else:
            evaluator = RequirementEvaluator(threshold=0.35)
            req_results = evaluator.evaluate(extracted_reqs, gt_requirements)
            results["requirement_evaluation"] = req_results

            if verbose:
                print(
                    f"\n  Extracted:    {req_results['n_extracted']} requirements\n"
                    f"  Ground truth: {req_results['n_gt']} requirements\n"
                    f"  Matched:      {req_results['n_matched']} pairs\n"
                )
                _metric_row("Precision", req_results["precision"],
                            "(extracted reqs that match GT)")
                _metric_row("Recall",    req_results["recall"],
                            "(GT reqs covered by extracted)")
                _metric_row("F1 Score",  req_results["f1"])

                matched = req_results["matched_pairs"]
                if matched:
                    print(f"\n  ✓ Matched pairs (top {min(8, len(matched))}):")
                    for p in matched[:8]:
                        print(
                            f"    [{p['similarity']:.2f}] "
                            f"{p['extracted_title'][:45]!r}\n"
                            f"           ↔ {p['gt_title'][:45]!r}"
                        )

                unmatched_ext = req_results["unmatched_extracted"]
                if unmatched_ext:
                    print(
                        f"\n  ✗ Unmatched extracted (first 5 — likely false positives):"
                    )
                    for t in unmatched_ext[:5]:
                        print(f"    • {t}")

                unmatched_gt = req_results["unmatched_gt"]
                if unmatched_gt:
                    print(f"\n  ✗ Unmatched GT (first 5 — missed requirements):")
                    for t in unmatched_gt[:5]:
                        print(f"    • {t}")

    elif requirements_path:
        print(f"  ⚠ Requirements file not found: {requirements_path}")

    # 3. Test-case evaluation ─────────────────────────────────────────────────
    if test_plan_path and Path(test_plan_path).exists():
        _section("Test Case Generation Evaluation")
        test_plan = _load_json(test_plan_path)

        if not gt_test_cases:
            print("  ⚠ No GT test cases loaded — skipping TC evaluation")
        else:
            evaluator = TestCaseEvaluator(tc_threshold=0.35, step_threshold=0.25)
            tc_results = evaluator.evaluate(test_plan, gt_test_cases)
            results["test_case_evaluation"] = tc_results

            if verbose:
                print(
                    f"\n  Generated:    {tc_results['n_generated']} test cases\n"
                    f"  Ground truth: {tc_results['n_gt']} test cases\n"
                    f"  Matched:      {tc_results['n_matched']} pairs\n"
                )
                _metric_row("TC Precision",     tc_results["tc_precision"],
                            "(generated TCs matching GT)")
                _metric_row("TC Recall",        tc_results["tc_recall"],
                            "(GT TCs covered)")
                _metric_row("TC F1",            tc_results["tc_f1"])
                _metric_row("Avg Step Accuracy", tc_results["avg_step_accuracy"],
                            "(GT steps covered by generated steps)")

                matched_tcs = [c for c in tc_results["comparisons"] if c["matched"]]
                if matched_tcs:
                    print(f"\n  ✓ Matched TCs (top {min(5, len(matched_tcs))}):")
                    for c in matched_tcs[:5]:
                        print(
                            f"    [{c['similarity']:.2f}] "
                            f"{c['generated_title'][:45]!r}\n"
                            f"           ↔ {c['gt_match_title'][:45]!r}\n"
                            f"           Steps: {c['n_generated_steps']} generated "
                            f"/ {c['n_gt_steps']} GT "
                            f"| step acc {c['step_accuracy']:.1%}"
                        )

                unmatched_tcs = [c for c in tc_results["comparisons"] if not c["matched"]]
                if unmatched_tcs:
                    print(
                        f"\n  ✗ Unmatched generated TCs (first 5 — no GT match):"
                    )
                    for c in unmatched_tcs[:5]:
                        print(
                            f"    [{c['similarity']:.2f}] "
                            f"{c['generated_title'][:60]!r}"
                        )

    elif test_plan_path:
        print(f"  ⚠ Test plan file not found: {test_plan_path}")

    # 4. Summary ──────────────────────────────────────────────────────────────
    if results:
        _section("SUMMARY")
        if "requirement_evaluation" in results:
            r = results["requirement_evaluation"]
            print(
                f"  Requirements — "
                f"P: {r['precision']:.1%}  "
                f"R: {r['recall']:.1%}  "
                f"F1: {r['f1']:.1%}  "
                f"({r['n_matched']}/{r['n_gt']} GT covered)"
            )
        if "test_case_evaluation" in results:
            t = results["test_case_evaluation"]
            print(
                f"  Test Cases   — "
                f"P: {t['tc_precision']:.1%}  "
                f"R: {t['tc_recall']:.1%}  "
                f"F1: {t['tc_f1']:.1%}  "
                f"Avg step acc: {t['avg_step_accuracy']:.1%}"
            )

    # 5. Save results ─────────────────────────────────────────────────────────
    if output_path and results:
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        print(f"\n  Results saved → {output_path}")

    print()
    return results


# ─────────────────────────────────────────────────────────────────────────────
# CLI entry point
# ─────────────────────────────────────────────────────────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Evaluate requirement extraction and test case generation quality",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m evaluation.run_evaluation \\
      --requirements output/inuts/requirements/inuts_requirements.json \\
      --test-plan    output/inuts/testcases/inuts_test_plan.json \\
      --gt-dir       groundtruth \\
      --output       evaluation/results/inuts_eval.json

  # Quiet mode — just the numbers
  python -m evaluation.run_evaluation \\
      --requirements output/inuts/requirements/inuts_requirements.json --quiet
        """,
    )
    p.add_argument(
        "--requirements", "-r",
        metavar="PATH",
        help="Path to extracted requirements JSON",
    )
    p.add_argument(
        "--test-plan", "-t",
        metavar="PATH",
        help="Path to generated test plan JSON",
    )
    p.add_argument(
        "--gt-dir", "-g",
        metavar="DIR",
        default="groundtruth",
        help="Ground truth directory (default: groundtruth)",
    )
    p.add_argument(
        "--output", "-o",
        metavar="PATH",
        help="Save full evaluation results to this JSON file",
    )
    p.add_argument(
        "--quiet", "-q",
        action="store_true",
        help="Suppress detailed output (summary only)",
    )
    return p


def main():
    parser = _build_parser()
    args = parser.parse_args()

    if not args.requirements and not args.test_plan:
        parser.print_help()
        print("\nError: provide at least --requirements or --test-plan")
        sys.exit(1)

    run_evaluation(
        requirements_path=args.requirements,
        test_plan_path=args.test_plan,
        gt_dir=args.gt_dir,
        output_path=args.output,
        verbose=not args.quiet,
    )


if __name__ == "__main__":
    main()
