"""
evaluate_tc.py v3.1
Handles per-scenario TCs: groups generated TCs by feature_id before matching to GT.
"""
import json
import logging
import argparse
from pathlib import Path
from datetime import datetime
from collections import defaultdict
from utils import (Config, TCGroundTruthReader, SemanticMatcher, find_gt_files, ROOT_DIR)

logger = logging.getLogger(__name__)

def evaluate_step_coverage(gen_steps, gt_steps, matcher, threshold=0.30):
    if not gen_steps or not gt_steps:
        return {"matched_steps": 0, "total_gen": len(gen_steps), "total_gt": len(gt_steps),
                "step_precision": 0, "step_recall": 0, "step_f1": 0,
                "matched_pairs": [], "missed_gt_actions": []}
    gen_a = [s.get('action', '') if isinstance(s, dict) else s.action for s in gen_steps]
    gt_a = [s.get('action', '') if isinstance(s, dict) else s.action for s in gt_steps]
    matches = matcher.match_lists(gen_a, gt_a, threshold=threshold)
    matched_gt = {m[1] for m in matches}
    p = len(matches) / len(gen_steps) if gen_steps else 0
    r = len(matches) / len(gt_steps) if gt_steps else 0
    f1 = 2 * p * r / (p + r) if (p + r) > 0 else 0
    pairs = [{"gen_step": gi + 1, "gt_step": gti + 1,
              "gen_action": gen_a[gi][:80], "gt_action": gt_a[gti][:80],
              "similarity": round(sc, 3)} for gi, gti, sc in matches]
    missed = [gt_a[i][:100] for i in range(len(gt_steps)) if i not in matched_gt]
    return {"matched_steps": len(matches), "total_gen": len(gen_steps), "total_gt": len(gt_steps),
            "step_precision": round(p, 4), "step_recall": round(r, 4), "step_f1": round(f1, 4),
            "matched_pairs": pairs, "missed_gt_actions": missed}

def _find_latest_tc_json(output_dir: Path) -> Path:
    json_files = sorted(output_dir.glob("test_cases_*.json"), reverse=True)
    if not json_files:
        raise FileNotFoundError(f"No test cases in {output_dir}")
    return json_files[0]

def _group_tcs_by_feature(gen_tcs: list) -> dict:
    """Group scenario TCs by parent feature_id, merge their steps."""
    groups = defaultdict(lambda: {"feature_name": "", "description": "", "steps": [], "tc_ids": []})
    for tc in gen_tcs:
        fid = tc.get('feature_id', '')
        if not fid:
            continue
        groups[fid]["feature_name"] = tc.get('feature_name', '').split(' - ')[0].strip()
        groups[fid]["description"] += tc.get('description', '') + " "
        groups[fid]["tc_ids"].append(tc.get('test_case_id', ''))
        groups[fid]["steps"].extend(tc.get('steps', []))
    return dict(groups)

def evaluate_tc(generated_path=None, tc_gt_dir=None, output_dir=None):
    cfg = Config.load()
    tc_gt_dir = Path(tc_gt_dir or ROOT_DIR / cfg['paths']['tc_gt_dir'])
    output_dir = Path(output_dir or ROOT_DIR / cfg['paths']['output_dir'] / 'tc')

    gen_file = Path(generated_path) if generated_path else _find_latest_tc_json(output_dir)
    with open(gen_file) as f:
        data = json.load(f)
    
    # Flatten test_plans into a single list of test cases if nested
    if "test_plans" in data:
        gen_tcs = []
        for plan in data["test_plans"]:
            gen_tcs.extend(plan.get("test_cases", []))
    else:
        gen_tcs = data.get('test_cases', [])
        
    logger.info(f"Loaded {len(gen_tcs)} generated TCs (scenario-level)")

    gt_files = find_gt_files(str(tc_gt_dir))
    if not gt_files:
        raise FileNotFoundError(f"No TC GT in {tc_gt_dir}")
    gt_tcs = TCGroundTruthReader.read(str(gt_files[0]))

    matcher = SemanticMatcher()
    step_th = cfg.get('evaluation', {}).get('step_match_threshold', 0.30)
    sim_th = cfg.get('evaluation', {}).get('similarity_threshold', 0.25)

    # Group generated TCs by feature for fair comparison with GT
    grouped = _group_tcs_by_feature(gen_tcs)
    logger.info(f"Grouped into {len(grouped)} feature-level TC groups")

    # Match grouped features to GT
    group_list = list(grouped.items())
    gen_texts = [f"{fid} {info['feature_name']} {info['description']}" for fid, info in group_list]
    gt_list = list(gt_tcs.values())
    gt_texts = [f"{tc.feature_id} {tc.feature_name} {tc.description}" for tc in gt_list]
    tc_matches = matcher.match_lists(gen_texts, gt_texts, threshold=sim_th)

    tp = len(tc_matches)
    fp, fn = len(grouped) - tp, len(gt_list) - tp
    tc_p = tp / (tp + fp) if (tp + fp) > 0 else 0
    tc_r = tp / (tp + fn) if (tp + fn) > 0 else 0
    tc_f1 = 2 * tc_p * tc_r / (tc_p + tc_r) if (tc_p + tc_r) > 0 else 0

    per_tc, totals = [], {"step_precision": 0, "step_recall": 0, "step_f1": 0}
    matched_gt_ids = set()
    for gi, gti, sc in tc_matches:
        fid, info = group_list[gi]
        gt_tc = gt_list[gti]
        matched_gt_ids.add(gt_tc.test_case_id)
        gt_sd = [{"action": s.action, "expected_result": s.expected_result} for s in gt_tc.steps]
        se = evaluate_step_coverage(info['steps'], gt_sd, matcher, step_th)
        per_tc.append({
            "gen_feature_id": fid,
            "gen_feature": info['feature_name'],
            "gen_scenario_tcs": info['tc_ids'],
            "gt_id": gt_tc.test_case_id,
            "gt_feature": gt_tc.feature_id,
            "tc_similarity": round(sc, 3),
            "gen_step_count": len(info['steps']),
            "gt_step_count": len(gt_tc.steps),
            "step_metrics": se
        })
        for k in totals:
            totals[k] += se[k]

    mc = max(len(tc_matches), 1)
    avg = {k: round(v / mc, 4) for k, v in totals.items()}
    missed_gt = [{"gt_id": tc.test_case_id, "gt_feature": tc.feature_id, "gt_step_count": len(tc.steps)}
                  for tc in gt_list if tc.test_case_id not in matched_gt_ids]

    report = {
        "evaluation_date": datetime.now().isoformat(),
        "generated_file": str(gen_file),
        "total_scenario_tcs": len(gen_tcs),
        "total_feature_groups": len(grouped),
        "tc_level_metrics": {
            "feature_groups": len(grouped), "gt_count": len(gt_list),
            "matched": tp, "false_positives": fp, "missed": fn,
            "precision": round(tc_p, 4), "recall": round(tc_r, 4), "f1_score": round(tc_f1, 4)
        },
        "step_level_metrics": {
            "avg_step_precision": avg["step_precision"],
            "avg_step_recall": avg["step_recall"],
            "avg_step_f1": avg["step_f1"],
            "total_gen_steps": sum(len(tc.get('steps', [])) for tc in gen_tcs),
            "total_gt_steps": sum(len(tc.steps) for tc in gt_list)
        },
        "per_tc_results": per_tc, "missed_gt": missed_gt
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / f"tc_evaluation_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(report_path, 'w') as f:
        json.dump(report, f, indent=2)

    print("\n" + "=" * 70)
    print("TEST CASE EVALUATION (Scenario-Level TCs → Feature-Level Grouping)")
    print("=" * 70)
    print(f"Scenario TCs: {len(gen_tcs)} | Feature Groups: {len(grouped)} | GT: {len(gt_list)} | Matched: {tp}")
    print(f"Feature P: {tc_p:.2%} | R: {tc_r:.2%} | F1: {tc_f1:.2%}")
    print(f"Step P: {avg['step_precision']:.2%} | R: {avg['step_recall']:.2%} | F1: {avg['step_f1']:.2%}")
    print(f"\nPER-FEATURE:")
    for r in per_tc:
        sm = r['step_metrics']
        print(f"  {r['gt_id']:15s} → Scenarios: {len(r['gen_scenario_tcs'])} | "
              f"Gen: {r['gen_step_count']} GT: {r['gt_step_count']} "
              f"Recall: {sm['step_recall']:.0%} F1: {sm['step_f1']:.0%}")
    if missed_gt:
        print(f"\nMISSED GT ({len(missed_gt)}):")
        for m in missed_gt:
            print(f"  ✗ {m['gt_id']}: {m['gt_feature']} ({m['gt_step_count']} steps)")
    print(f"\nReport: {report_path}")
    print("=" * 70)
    return report

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
    parser = argparse.ArgumentParser(description="Evaluate generated test cases against ground truth.")
    parser.add_argument("--generated_path", help="Path to the generated test cases JSON file.")
    parser.add_argument("--tc_gt_dir", help="Directory containing the ground truth Excel files.")
    parser.add_argument("--output_dir", help="Directory to save the evaluation report.")
    args = parser.parse_args()
    
    evaluate_tc(
        generated_path=args.generated_path,
        tc_gt_dir=args.tc_gt_dir,
        output_dir=args.output_dir
    )
