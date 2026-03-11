"""
Compare generated test cases with ground truth test cases at the step level.
- Matches generated TCs to GT TCs using keyword/text similarity
- Aligns steps using sequence matching
- Classifies each comparison as: Good Match, Partial, or Missing
- Outputs results to an Excel file
"""

import re
import openpyxl
from difflib import SequenceMatcher
from openpyxl.styles import PatternFill, Font, Alignment, Border, Side
from openpyxl.utils import get_column_letter

GEN_TC_FILE = "output/ptw_complete_v4_20260310_222741/tc/ptw_complete_v4_test_plan.xlsx"
GT_TC_FILE = "TC_GT/PTW_E2E_TEST_CASES_JAN_19_.xlsx"
OUTPUT_FILE = "output/ptw_complete_v4_20260310_222741/tc/ptw_complete_v4_test_plan_step_comparison.xlsx"

GOOD_MATCH_THRESHOLD = 0.50
PARTIAL_MATCH_THRESHOLD = 0.22


def text_similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()


def classify_match(score: float) -> str:
    if score >= GOOD_MATCH_THRESHOLD:
        return "Good match"
    elif score >= PARTIAL_MATCH_THRESHOLD:
        return "Partial"
    else:
        return "No match"


def parse_generated_steps(steps_text: str) -> list[str]:
    """Split generated TC steps text (numbered, → separates action from expected)."""
    if not steps_text:
        return []
    # Split on newline followed by a digit+dot
    parts = re.split(r'\n(?=\d+\.)', steps_text.strip())
    result = []
    for part in parts:
        # Take only the action portion (before →)
        action = part.split('→')[0].strip()
        # Strip leading step number
        action = re.sub(r'^\d+\.\s*', '', action).strip()
        if action:
            result.append(action)
    return result


def parse_gt_file(filepath: str) -> list[dict]:
    """
    Parse the GT Excel file. Each sheet may have multiple test cases.
    A new test case starts when column A has the sheet feature ID.
    Returns a list of dicts: {feature, description, steps: [str]}
    """
    wb = openpyxl.load_workbook(filepath)
    gt_tcs = []

    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        rows = list(ws.iter_rows(values_only=True))

        current_desc = None
        current_steps = []

        def flush():
            if current_desc and current_steps:
                gt_tcs.append({
                    "feature": sheet_name,
                    "description": current_desc.strip(),
                    "steps": [s.strip() for s in current_steps if s and s.strip()],
                })

        for row in rows[1:]:  # skip header row
            feature_col = row[0]
            desc_col = row[1]
            step_col = row[2]

            # New TC group when feature column is populated
            if feature_col and str(feature_col).strip():
                flush()
                current_desc = str(desc_col).strip() if desc_col else ""
                current_steps = []
                if step_col:
                    current_steps.append(str(step_col))
            else:
                if step_col:
                    current_steps.append(str(step_col))

        flush()

    return gt_tcs


def parse_generated_file(filepath: str) -> list[dict]:
    """Parse generated TC Excel file."""
    wb = openpyxl.load_workbook(filepath)
    ws = wb["Test Cases"]
    gen_tcs = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        req_id, req_title, tc_title, tc_desc, phases, types, prereqs, steps, expected, status = row
        if tc_title:
            gen_tcs.append({
                "req_id": req_id or "",
                "req_title": req_title or "",
                "tc_title": tc_title or "",
                "description": tc_desc or "",
                "steps": parse_generated_steps(steps) if steps else [],
                "expected": expected or "",
            })
    return gen_tcs


def find_best_gt_match(gen_tc: dict, gt_tcs: list[dict]) -> tuple[dict | None, float]:
    """Find the best matching GT TC for a generated TC using text similarity."""
    gen_text = f"{gen_tc['req_title']} {gen_tc['tc_title']} {gen_tc['description']}"
    best_score = 0.0
    best_gt = None
    for gt in gt_tcs:
        gt_text = f"{gt['feature']} {gt['description']}"
        score = text_similarity(gen_text, gt_text)
        if score > best_score:
            best_score = score
            best_gt = gt
    return best_gt, best_score


def align_steps(gen_steps: list[str], gt_steps: list[str]) -> list[dict]:
    """
    Greedily align generated steps with GT steps.
    Returns list of dicts with: gen_step, gt_step, match_type, score
    """
    if not gt_steps:
        return [{"gen_step": s, "gt_step": "", "match_type": "No GT", "score": 0.0}
                for s in gen_steps]

    # Build similarity matrix
    used_gen = set()
    used_gt = set()
    pairs = []

    # Score all pairs and sort by descending similarity
    scored = []
    for gi, gs in enumerate(gen_steps):
        for ti, ts in enumerate(gt_steps):
            scored.append((text_similarity(gs, ts), gi, ti))
    scored.sort(reverse=True)

    for score, gi, ti in scored:
        if gi in used_gen or ti in used_gt:
            continue
        match_type = classify_match(score)
        pairs.append({
            "gen_step": gen_steps[gi],
            "gt_step": gt_steps[ti],
            "match_type": match_type,
            "score": score,
            "gi": gi,
            "ti": ti,
        })
        used_gen.add(gi)
        used_gt.add(ti)

    # Remaining GT steps with no generated match → Missing
    for ti, ts in enumerate(gt_steps):
        if ti not in used_gt:
            pairs.append({
                "gen_step": "",
                "gt_step": ts,
                "match_type": "Missing",
                "score": 0.0,
                "gi": 999,
                "ti": ti,
            })

    # Sort by GT step index for readability
    pairs.sort(key=lambda x: x["ti"])
    return pairs


def build_output_excel(comparisons: list[dict], output_path: str):
    """Write comparison results to Excel."""
    wb = openpyxl.Workbook()
    ws_summary = wb.active
    ws_summary.title = "Summary"

    # ── colour palette ──────────────────────────────────────────────────────────
    FILL_GOOD    = PatternFill("solid", fgColor="C6EFCE")   # green
    FILL_PARTIAL = PatternFill("solid", fgColor="FFEB9C")   # yellow
    FILL_MISSING = PatternFill("solid", fgColor="FFC7CE")   # red
    FILL_HEADER  = PatternFill("solid", fgColor="4472C4")   # blue
    FILL_TC_HDR  = PatternFill("solid", fgColor="D9E1F2")   # light blue

    FONT_HDR  = Font(bold=True, color="FFFFFF", size=11)
    FONT_TCHDR = Font(bold=True, size=10)
    FONT_BOLD = Font(bold=True)
    WRAP      = Alignment(wrap_text=True, vertical="top")
    CENTER    = Alignment(horizontal="center", vertical="center", wrap_text=True)

    thin = Side(style="thin")
    BORDER = Border(left=thin, right=thin, top=thin, bottom=thin)

    # ── Summary sheet ────────────────────────────────────────────────────────────
    summary_headers = ["#", "Generated TC Title", "Matched GT Description",
                       "TC Match Score", "Total Steps",
                       "Good Match", "Partial", "Missing", "Coverage %"]
    ws_summary.append(summary_headers)
    for ci, h in enumerate(summary_headers, 1):
        cell = ws_summary.cell(1, ci)
        cell.fill = FILL_HEADER
        cell.font = FONT_HDR
        cell.alignment = CENTER
        cell.border = BORDER

    # ── Detail sheet ─────────────────────────────────────────────────────────────
    ws_detail = wb.create_sheet("Step Comparison")
    detail_headers = ["TC #", "Generated TC Title", "GT Description",
                      "#", "Your Generated Step", "Ground Truth Step", "Match Type"]
    ws_detail.append(detail_headers)
    for ci, h in enumerate(detail_headers, 1):
        cell = ws_detail.cell(1, ci)
        cell.fill = FILL_HEADER
        cell.font = FONT_HDR
        cell.alignment = CENTER
        cell.border = BORDER

    detail_row = 2
    for idx, comp in enumerate(comparisons, 1):
        gen_tc_title  = comp["gen_tc_title"]
        gt_desc       = comp["gt_description"]
        tc_score      = comp["tc_match_score"]
        pairs         = comp["pairs"]

        # Counts
        good    = sum(1 for p in pairs if p["match_type"] == "Good match")
        partial = sum(1 for p in pairs if p["match_type"] == "Partial")
        missing = sum(1 for p in pairs if p["match_type"] == "Missing")
        total_gt = sum(1 for p in pairs if p["gt_step"])
        covered = good + partial
        coverage = round(covered / total_gt * 100, 1) if total_gt else 0

        # Summary row
        summary_row_data = [idx, gen_tc_title, gt_desc, f"{tc_score:.2f}",
                            total_gt, good, partial, missing, f"{coverage}%"]
        ws_summary.append(summary_row_data)
        sr = ws_summary.max_row
        for ci in range(1, len(summary_row_data) + 1):
            cell = ws_summary.cell(sr, ci)
            cell.border = BORDER
            cell.alignment = WRAP
        # Colour coverage cell
        cov_cell = ws_summary.cell(sr, 9)
        if coverage >= 70:
            cov_cell.fill = FILL_GOOD
        elif coverage >= 40:
            cov_cell.fill = FILL_PARTIAL
        else:
            cov_cell.fill = FILL_MISSING

        # TC header row in detail sheet
        ws_detail.cell(detail_row, 1, idx).fill = FILL_TC_HDR
        ws_detail.cell(detail_row, 2, gen_tc_title).fill = FILL_TC_HDR
        ws_detail.cell(detail_row, 3, gt_desc).fill = FILL_TC_HDR
        ws_detail.cell(detail_row, 4, "Step").fill = FILL_TC_HDR
        ws_detail.cell(detail_row, 5, "Your Generated Step").fill = FILL_TC_HDR
        ws_detail.cell(detail_row, 6, "Ground Truth Step").fill = FILL_TC_HDR
        ws_detail.cell(detail_row, 7, "Match Type").fill = FILL_TC_HDR
        for ci in range(1, 8):
            cell = ws_detail.cell(detail_row, ci)
            cell.font = FONT_TCHDR
            cell.alignment = WRAP
            cell.border = BORDER
        detail_row += 1

        # Step rows
        for step_idx, pair in enumerate(pairs, 1):
            match_type = pair["match_type"]
            fill = (FILL_GOOD if match_type == "Good match"
                    else FILL_PARTIAL if match_type == "Partial"
                    else FILL_MISSING)

            ws_detail.cell(detail_row, 1, idx)
            ws_detail.cell(detail_row, 2, "")
            ws_detail.cell(detail_row, 3, "")
            ws_detail.cell(detail_row, 4, step_idx)
            ws_detail.cell(detail_row, 5, pair["gen_step"])
            ws_detail.cell(detail_row, 6, pair["gt_step"])
            ws_detail.cell(detail_row, 7, match_type)
            for ci in range(1, 8):
                cell = ws_detail.cell(detail_row, ci)
                cell.alignment = WRAP
                cell.border = BORDER
            ws_detail.cell(detail_row, 7).fill = fill
            detail_row += 1

        # Blank separator
        detail_row += 1

    # ── Column widths ─────────────────────────────────────────────────────────────
    ws_summary.column_dimensions["A"].width = 5
    ws_summary.column_dimensions["B"].width = 45
    ws_summary.column_dimensions["C"].width = 55
    ws_summary.column_dimensions["D"].width = 14
    ws_summary.column_dimensions["E"].width = 12
    ws_summary.column_dimensions["F"].width = 12
    ws_summary.column_dimensions["G"].width = 10
    ws_summary.column_dimensions["H"].width = 10
    ws_summary.column_dimensions["I"].width = 13

    ws_detail.column_dimensions["A"].width = 5
    ws_detail.column_dimensions["B"].width = 40
    ws_detail.column_dimensions["C"].width = 50
    ws_detail.column_dimensions["D"].width = 6
    ws_detail.column_dimensions["E"].width = 45
    ws_detail.column_dimensions["F"].width = 55
    ws_detail.column_dimensions["G"].width = 14

    wb.save(output_path)
    print(f"\nSaved: {output_path}")


def main():
    print("Loading files...")
    gen_tcs = parse_generated_file(GEN_TC_FILE)
    gt_tcs  = parse_gt_file(GT_TC_FILE)

    print(f"  Generated TCs : {len(gen_tcs)}")
    print(f"  GT TCs        : {len(gt_tcs)}")

    comparisons = []
    print("\n--- TC Matching & Step Comparison ---")

    for gen_tc in gen_tcs:
        best_gt, tc_score = find_best_gt_match(gen_tc, gt_tcs)

        if best_gt is None or tc_score < 0.15:
            gt_desc  = "No matching GT TC found"
            gt_steps = []
        else:
            gt_desc  = best_gt["description"]
            gt_steps = best_gt["steps"]

        pairs = align_steps(gen_tc["steps"], gt_steps)

        good    = sum(1 for p in pairs if p["match_type"] == "Good match")
        partial = sum(1 for p in pairs if p["match_type"] == "Partial")
        missing = sum(1 for p in pairs if p["match_type"] == "Missing")
        total_gt = sum(1 for p in pairs if p["gt_step"])
        coverage = round((good + partial) / total_gt * 100, 1) if total_gt else 0

        print(f"\n[{gen_tc['tc_title']}]")
        print(f"  → GT: {gt_desc[:70]}  (TC score: {tc_score:.2f})")
        print(f"  Steps: Good={good}, Partial={partial}, Missing={missing}, Coverage={coverage}%")
        for p in pairs:
            icon = "✓" if p["match_type"] == "Good match" else ("~" if p["match_type"] == "Partial" else "✗")
            print(f"    {icon} [{p['match_type']:12s}] Gen: {p['gen_step'][:50]!r:54s} | GT: {p['gt_step'][:50]!r}")

        comparisons.append({
            "gen_tc_title":    gen_tc["tc_title"],
            "gt_description":  gt_desc,
            "tc_match_score":  tc_score,
            "pairs":           pairs,
        })

    build_output_excel(comparisons, OUTPUT_FILE)

    # Aggregate stats
    total_good    = sum(sum(1 for p in c["pairs"] if p["match_type"] == "Good match")    for c in comparisons)
    total_partial = sum(sum(1 for p in c["pairs"] if p["match_type"] == "Partial")        for c in comparisons)
    total_missing = sum(sum(1 for p in c["pairs"] if p["match_type"] == "Missing")        for c in comparisons)
    total_gt_steps = total_good + total_partial + total_missing
    overall_cov = round((total_good + total_partial) / total_gt_steps * 100, 1) if total_gt_steps else 0

    print("\n" + "=" * 60)
    print("OVERALL SUMMARY")
    print(f"  Test Cases compared : {len(comparisons)}")
    print(f"  Total GT steps      : {total_gt_steps}")
    print(f"  Good Match          : {total_good}")
    print(f"  Partial             : {total_partial}")
    print(f"  Missing             : {total_missing}")
    print(f"  Overall Coverage    : {overall_cov}%")
    print("=" * 60)


if __name__ == "__main__":
    main()
