"""
evaluate_br.py v4.0 - includes document classification in report
"""
import json
import logging
from pathlib import Path
from datetime import datetime
from utils import (Config, BRGroundTruthReader, SemanticMatcher, validate_gt_file, find_gt_files, ROOT_DIR)

logger = logging.getLogger(__name__)

def _find_latest_json(output_dir: Path) -> Path:
    json_files = sorted(output_dir.glob("requirements_*.json"), reverse=True)
    if not json_files:
        raise FileNotFoundError(f"No extracted requirements in {output_dir}")
    return json_files[0]

def evaluate_br(extracted_path=None, br_gt_dir=None, output_dir=None):
    cfg = Config.load()
    br_gt_dir = Path(br_gt_dir or ROOT_DIR / cfg['paths']['br_gt_dir'])
    output_dir = Path(output_dir or ROOT_DIR / cfg['paths']['output_dir'] / 'br')

    extracted_file = Path(extracted_path) if extracted_path else _find_latest_json(output_dir)
    with open(extracted_file) as f:
        data = json.load(f)
    extracted = data.get('requirements', [])
    docs_processed = list(set(r.get('source_file','') for r in extracted))
    doc_classification = data.get('document_classification', {})
    token_usage = data.get('token_usage', {})
    logger.info(f"Loaded {len(extracted)} extracted from {extracted_file.name}")

    gt_files = find_gt_files(str(br_gt_dir))
    if not gt_files:
        raise FileNotFoundError(f"No GT files in {br_gt_dir}")
    validate_gt_file(gt_files[0], cfg.get('br_gt', {}).get('sheet_name', 'Requirements Summary'))
    gt_reqs = BRGroundTruthReader.read(str(gt_files[0]))

    matcher = SemanticMatcher()
    threshold = cfg.get('evaluation', {}).get('similarity_threshold', 0.25)

    ext_texts = [f"{r.get('feature_name', '')} {r.get('description', '')}" for r in extracted]
    gt_texts = [f"{r.feature_name} {r.description} {r.requirements_text}" for r in gt_reqs]
    matches = matcher.match_lists(ext_texts, gt_texts, threshold=threshold)

    tp, fp, fn = len(matches), len(extracted) - len(matches), len(gt_reqs) - len(matches)
    p = tp / (tp + fp) if (tp + fp) > 0 else 0
    r = tp / (tp + fn) if (tp + fn) > 0 else 0
    f1 = 2 * p * r / (p + r) if (p + r) > 0 else 0

    matched_gt_ids = set()
    matched_details = []
    for ei, gi, score in matches:
        matched_gt_ids.add(gt_reqs[gi].requirement_id)
        ext_req = extracted[ei]
        matched_details.append({
            "extracted_id": ext_req.get('requirement_id', ''),
            "extracted_title": ext_req.get('feature_name', ''),
            "gt_id": gt_reqs[gi].requirement_id,
            "gt_title": gt_reqs[gi].feature_name,
            "similarity_score": round(score, 3),
            "source_file": ext_req.get('source_file', ''),
            "page_start": ext_req.get('page_start', 0),
            "page_end": ext_req.get('page_end', 0),
            "line_start": ext_req.get('line_start', 0),
            "line_end": ext_req.get('line_end', 0),
            "scenario_count": len(ext_req.get('test_scenarios', [])),
            "step_count": len(ext_req.get('test_steps', [])),
            "acceptance_criteria_count": len(ext_req.get('acceptance_criteria', []))
        })

    missed_gt = [{"gt_id": r.requirement_id, "gt_title": r.feature_name,
                   "gt_description": r.description[:100]}
                  for r in gt_reqs if r.requirement_id not in matched_gt_ids]
    matched_ext = {m[0] for m in matches}
    false_pos = [{"extracted_id": extracted[i].get('requirement_id', ''),
                   "extracted_title": extracted[i].get('feature_name', ''),
                   "source_file": extracted[i].get('source_file', '')}
                  for i in range(len(extracted)) if i not in matched_ext]

    reqs_with_scenarios = sum(1 for r in extracted if r.get('test_scenarios'))
    reqs_with_steps = sum(1 for r in extracted if r.get('test_steps'))
    total_scenarios = sum(len(r.get('test_scenarios', [])) for r in extracted)
    total_steps = sum(len(r.get('test_steps', [])) for r in extracted)

    doc_breakdown = {}
    for req in extracted:
        sf = req.get('source_file', 'unknown')
        if sf not in doc_breakdown:
            doc_breakdown[sf] = {"count": 0, "matched": 0}
        doc_breakdown[sf]["count"] += 1
    for ei, gi, score in matches:
        sf = extracted[ei].get('source_file', 'unknown')
        if sf in doc_breakdown:
            doc_breakdown[sf]["matched"] += 1

    report = {
        "evaluation_date": datetime.now().isoformat(),
        "extracted_file": str(extracted_file),
        "documents_processed": docs_processed,
        "document_classification": doc_classification,
        "token_usage": token_usage,
        "summary": {
            "extracted_count": len(extracted), "gt_count": len(gt_reqs),
            "matched": tp, "false_positives": fp, "missed": fn,
            "precision": round(p, 4), "recall": round(r, 4), "f1_score": round(f1, 4)
        },
        "enrichment_analysis": {
            "reqs_with_scenarios": reqs_with_scenarios,
            "total_scenarios": total_scenarios,
            "avg_scenarios_per_req": round(total_scenarios / len(extracted), 1) if extracted else 0,
            "reqs_with_steps": reqs_with_steps,
            "total_steps": total_steps,
            "avg_steps_per_req": round(total_steps / reqs_with_steps, 1) if reqs_with_steps else 0
        },
        "per_document_breakdown": doc_breakdown,
        "matched_details": matched_details,
        "missed_gt": missed_gt,
        "false_positives": false_pos[:15]
    }

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = output_dir / f"br_evaluation_{timestamp}.json"
    with open(report_path, 'w') as f:
        json.dump(report, f, indent=2)

    print("\n" + "=" * 70)
    print("BR EVALUATION RESULTS")
    print("=" * 70)
    print(f"Extracted: {len(extracted)}  |  GT: {len(gt_reqs)}  |  Matched: {tp}")
    print(f"Precision: {p:.2%}  |  Recall: {r:.2%}  |  F1: {f1:.2%}")
    if doc_classification:
        print(f"\nDOCUMENT CLASSIFICATION:")
        for d in doc_classification.get('primary', []):
            print(f"  [PRIMARY]    {d}")
        for d in doc_classification.get('supporting', []):
            print(f"  [SUPPORTING] {d}")
    if token_usage:
        print(f"\nTOKEN USAGE: {token_usage.get('llm_calls',0)} calls | "
              f"Input: {token_usage.get('total_input_tokens',0):,} | "
              f"Output: {token_usage.get('total_output_tokens',0):,} | "
              f"Total: {token_usage.get('total_tokens',0):,}")
    print(f"\nPER-DOCUMENT:")
    for doc, info in doc_breakdown.items():
        print(f"  {doc}: {info['count']} extracted, {info['matched']} matched")
    print(f"\nENRICHMENT:")
    print(f"  Scenarios: {total_scenarios} across {reqs_with_scenarios}/{len(extracted)} reqs")
    print(f"  Steps: {total_steps} across {reqs_with_steps}/{len(extracted)} reqs")
    if missed_gt:
        print(f"\nMISSED GT ({len(missed_gt)}):")
        for m in missed_gt:
            print(f"  x {m['gt_id']}: {m['gt_title']}")
    if false_pos:
        print(f"\nFALSE POS ({len(false_pos)}):")
        for fp_item in false_pos[:10]:
            print(f"  x {fp_item['extracted_id']}: {fp_item['extracted_title']} [{fp_item['source_file']}]")
    print(f"\nReport: {report_path}")
    print("=" * 70)
    return report


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
    evaluate_br()
