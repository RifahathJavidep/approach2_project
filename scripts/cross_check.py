"""
Cross-Check Script: Ground Truth Test Cases vs Source PDFs
Outputs a color-coded Excel report with:
  - Per test case: which doc + page the Description comes from
  - Per step: which doc + page each step comes from
  - Match status: Accurate / Partial / Missing
"""

import os
import json
import re
import groq
import pdfplumber
import openpyxl
from openpyxl.styles import PatternFill, Font, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from dotenv import load_dotenv

load_dotenv()

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────

INPUTS_DIR = "inputs"
GROUNDTRUTH_FILE = "groundtruth/PTW E2E TEST CASES JAN 19  (1).xlsx"
OUTPUT_EXCEL = "output/cross_check_report.xlsx"
CACHE_FILE = "output/cross_check_raw.json"

# All source PDFs (filenames only, relative to INPUTS_DIR)
ALL_PDFS = [
    "BBMBT-3917.pdf",
    "BBMBT-3920.pdf",
    "BBMOMNI-4424.pdf",
    "BBMOMNI-5101.pdf",
    "BBMOMNI-5111.pdf",
    "BBMOMNI-5113.pdf",
    "BBMOMNI-5114.pdf",
    "BBMSA-13025.pdf",
    "PTW Self Serve Phase 1 Solution.pdf",
    "Play to Win SS Ph1 - Dashboard_Features.pdf",
    "Play to Win SS Ph1 - Warranty_Feature.pdf",
    "Requirements Traceability Matrix.pdf",
]

# Feature → primary source PDFs (from RTM analysis)
FEATURE_PDF_MAP = {
    "PTWPH1-1":      ["BBMBT-3917.pdf", "Play to Win SS Ph1 - Dashboard_Features.pdf", "PTW Self Serve Phase 1 Solution.pdf"],
    "PTWPH1-2":      ["BBMOMNI-5111.pdf", "Play to Win SS Ph1 - Dashboard_Features.pdf", "PTW Self Serve Phase 1 Solution.pdf"],
    "PTWPH1-3":      ["BBMOMNI-5111.pdf", "Play to Win SS Ph1 - Dashboard_Features.pdf", "PTW Self Serve Phase 1 Solution.pdf"],
    "PTWPH1-4":      ["BBMOMNI-5101.pdf", "Play to Win SS Ph1 - Dashboard_Features.pdf", "PTW Self Serve Phase 1 Solution.pdf"],
    "PTWPH1-5":      ["BBMBT-3917.pdf", "Play to Win SS Ph1 - Dashboard_Features.pdf", "PTW Self Serve Phase 1 Solution.pdf"],
    "PTWPH1-6":      ["BBMBT-3917.pdf", "BBMOMNI-5111.pdf", "Play to Win SS Ph1 - Dashboard_Features.pdf"],
    "PTWPH1-7":      ["BBMBT-3917.pdf", "BBMOMNI-5111.pdf", "Play to Win SS Ph1 - Dashboard_Features.pdf"],
    "PTWPH1-8":      ["BBMBT-3920.pdf", "Play to Win SS Ph1 - Dashboard_Features.pdf"],
    "PTWPH1-9":      ["BBMBT-3917.pdf", "BBMOMNI-5111.pdf", "Play to Win SS Ph1 - Dashboard_Features.pdf"],
    "PTWPH1-10":     ["BBMBT-3917.pdf", "BBMOMNI-5111.pdf", "Play to Win SS Ph1 - Dashboard_Features.pdf"],
    "PTWPH1-11":     ["BBMBT-3917.pdf", "BBMOMNI-5111.pdf", "Play to Win SS Ph1 - Dashboard_Features.pdf"],
    "PTWPH1-12":     ["BBMBT-3917.pdf", "BBMOMNI-5111.pdf", "Play to Win SS Ph1 - Dashboard_Features.pdf"],
    "PTWPH1-13 & 16": ["BBMBT-3920.pdf", "Play to Win SS Ph1 - Dashboard_Features.pdf"],
    "PTWPH1-14":     ["BBMBT-3917.pdf", "BBMOMNI-5111.pdf", "Play to Win SS Ph1 - Dashboard_Features.pdf"],
    "PTWPH1-15":     ["BBMBT-3917.pdf", "BBMOMNI-5111.pdf", "Play to Win SS Ph1 - Dashboard_Features.pdf"],
    "PTWPH1-1W":     ["BBMOMNI-4424.pdf", "Play to Win SS Ph1 - Warranty_Feature.pdf", "PTW Self Serve Phase 1 Solution.pdf"],
    "PTWPH1-2W":     ["BBMOMNI-4424.pdf", "Play to Win SS Ph1 - Warranty_Feature.pdf", "PTW Self Serve Phase 1 Solution.pdf"],
}

# ─────────────────────────────────────────────
# COLORS
# ─────────────────────────────────────────────

GREEN  = PatternFill("solid", fgColor="C6EFCE")
YELLOW = PatternFill("solid", fgColor="FFEB9C")
RED    = PatternFill("solid", fgColor="FFC7CE")
BLUE   = PatternFill("solid", fgColor="BDD7EE")   # description rows
GREY   = PatternFill("solid", fgColor="D9D9D9")   # header
ORANGE = PatternFill("solid", fgColor="FCE4D6")   # sheet header


def match_fill(status: str) -> PatternFill:
    s = status.lower()
    if "accurate" in s or "✅" in s or "yes" in s or "found" in s:
        return GREEN
    elif "partial" in s or "⚠️" in s or "partial" in s:
        return YELLOW
    else:
        return RED


# ─────────────────────────────────────────────
# STAGE 2: Extract PDF text with page numbers
# ─────────────────────────────────────────────

def extract_all_pdfs() -> dict:
    """Returns { pdf_filename: { page_num: text } }"""
    print("\n[Stage 2] Extracting PDF text...")
    pdf_data = {}
    for pdf_name in ALL_PDFS:
        path = os.path.join(INPUTS_DIR, pdf_name)
        if not os.path.exists(path):
            print(f"  SKIP (not found): {pdf_name}")
            continue
        pages = {}
        with pdfplumber.open(path) as pdf:
            for i, page in enumerate(pdf.pages, start=1):
                text = page.extract_text() or ""
                pages[i] = text.strip()
        pdf_data[pdf_name] = pages
        print(f"  ✓ {pdf_name}: {len(pages)} pages")
    return pdf_data


# ─────────────────────────────────────────────
# STAGE 3: Parse ground truth Excel sheets
# ─────────────────────────────────────────────

def parse_ground_truth() -> dict:
    """
    Returns {
      sheet_name: {
        "feature_id": str,
        "description": str,
        "precondition": str,
        "steps": [ {"step_num": int, "step": str, "expected": str} ]
      }
    }
    """
    print("\n[Stage 3] Parsing ground truth Excel...")
    wb = openpyxl.load_workbook(GROUNDTRUTH_FILE)
    result = {}

    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            continue

        feature_id = None
        description = None
        precondition = None
        steps = []
        step_num = 0

        for i, row in enumerate(rows):
            if i == 0:
                # header row — skip
                continue

            col_a = str(row[0]).strip() if row[0] else None
            col_b = str(row[1]).strip() if row[1] else None  # Description
            col_c = str(row[2]).strip() if row[2] else None  # Steps
            col_d = str(row[3]).strip() if row[3] else None  # Pre-condition
            col_e = str(row[4]).strip() if row[4] else None  # Actual result

            # First data row has feature id + description
            if i == 1:
                feature_id = col_a or sheet_name
                description = col_b
                precondition = col_d
                if col_c:
                    step_num += 1
                    steps.append({
                        "step_num": step_num,
                        "step": col_c,
                        "expected": col_e or ""
                    })
            else:
                # continuation rows — only steps
                if col_c:
                    step_num += 1
                    steps.append({
                        "step_num": step_num,
                        "step": col_c,
                        "expected": col_e or ""
                    })
                # sometimes precondition spans rows
                if col_d and not precondition:
                    precondition = col_d

        result[sheet_name] = {
            "feature_id": feature_id or sheet_name,
            "description": description or "",
            "precondition": precondition or "",
            "steps": steps
        }
        print(f"  ✓ {sheet_name}: {len(steps)} steps")

    return result


# ─────────────────────────────────────────────
# STAGE 4: Build relevant PDF context per sheet
# ─────────────────────────────────────────────

def build_pdf_context(sheet_name: str, pdf_data: dict, max_chars: int = 12000) -> str:
    """
    For a given sheet, retrieve text from mapped PDFs.
    Returns a formatted string: [PDF: xxx | Page N]\n<text>\n...
    Limits total chars to avoid huge Claude prompts.
    """
    mapped_pdfs = FEATURE_PDF_MAP.get(sheet_name, list(pdf_data.keys()))
    context_parts = []
    total = 0

    for pdf_name in mapped_pdfs:
        if pdf_name not in pdf_data:
            continue
        pages = pdf_data[pdf_name]
        for page_num, text in pages.items():
            if not text:
                continue
            header = f"[PDF: {pdf_name} | Page {page_num}]"
            chunk = f"{header}\n{text}\n"
            if total + len(chunk) > max_chars:
                # Still add a truncated version if we have space for at least the header
                remaining = max_chars - total
                if remaining > len(header) + 100:
                    context_parts.append(f"{header}\n{text[:remaining - len(header) - 10]}...\n")
                break
            context_parts.append(chunk)
            total += len(chunk)
        if total >= max_chars:
            break

    return "\n".join(context_parts)


# ─────────────────────────────────────────────
# STAGE 5: Claude cross-check
# ─────────────────────────────────────────────

SYSTEM_PROMPT = """You are a QA traceability analyst. Your job is to cross-check test cases against source requirement documents.

You will be given:
1. SOURCE PDF CONTENT: Excerpts from requirement PDFs, each labeled with [PDF: <filename> | Page <N>]
2. A TEST CASE: Feature ID, Description, and numbered Steps

Your task: For each element, identify which source document and page number it comes from, and whether it is accurate.

Return ONLY a valid JSON object with this exact structure:
{
  "description": {
    "source_doc": "<pdf filename or 'Not Found'>",
    "source_page": "<page number or 'N/A'>",
    "match_status": "Accurate | Partial | Not Found",
    "notes": "<brief explanation of what matches, what is missing, or what is wrong>"
  },
  "steps": [
    {
      "step_num": 1,
      "step_text": "<step text>",
      "source_doc": "<pdf filename or 'Not Found'>",
      "source_page": "<page number or 'N/A'>",
      "match_status": "Accurate | Partial | Not Found",
      "notes": "<brief explanation>"
    }
  ]
}

Rules:
- match_status must be exactly one of: "Accurate", "Partial", "Not Found"
- source_doc must be the exact PDF filename from the source content headers, or "Not Found"
- source_page must be a number string (e.g. "3") or "N/A"
- Be specific in notes — mention what the PDF says vs what the test case says
- If a step is generic (e.g. "Login into portal") and not explicitly in the PDF, mark as "Partial" and note it is an implied prerequisite
- Return ONLY the JSON object, no other text"""


def claude_cross_check(sheet_name: str, tc: dict, pdf_context: str, client: groq.Groq) -> dict:
    """Call Groq LLM to cross-check one test case sheet. Returns parsed JSON."""

    steps_text = "\n".join(
        f"  Step {s['step_num']}: {s['step']}" + (f"\n  Expected: {s['expected']}" if s['expected'] else "")
        for s in tc["steps"]
    )

    user_message = f"""SOURCE PDF CONTENT:
{pdf_context}

---

TEST CASE:
Feature ID: {tc['feature_id']}
Description: {tc['description']}
Pre-condition: {tc['precondition']}

Steps:
{steps_text}

Cross-check this test case against the source PDF content above. Return the JSON."""

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        max_tokens=8000,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_message}
        ]
    )

    raw = response.choices[0].message.content.strip()

    # Clean up markdown code fences if present
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)

    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"  ⚠ JSON parse error for {sheet_name}: {e}")
        print(f"  Raw: {raw[:300]}")
        return {"error": str(e), "raw": raw}


# ─────────────────────────────────────────────
# STAGE 6: Build Excel report
# ─────────────────────────────────────────────

HEADERS = [
    "Feature ID",
    "Row Type",          # "DESCRIPTION" or "STEP N"
    "Text",
    "Source Document",
    "Page #",
    "Match Status",
    "Notes",
]

COL_WIDTHS = [18, 14, 60, 45, 8, 16, 60]


def style_header_row(ws, row_num: int):
    for col, (header, width) in enumerate(zip(HEADERS, COL_WIDTHS), start=1):
        cell = ws.cell(row=row_num, column=col, value=header)
        cell.fill = GREY
        cell.font = Font(bold=True, size=10)
        cell.alignment = Alignment(wrap_text=True, vertical="center")
        ws.column_dimensions[get_column_letter(col)].width = width


def add_row(ws, row_data: list, fill: PatternFill = None):
    row_num = ws.max_row + 1
    for col, val in enumerate(row_data, start=1):
        cell = ws.cell(row=row_num, column=col, value=val)
        cell.alignment = Alignment(wrap_text=True, vertical="top")
        cell.font = Font(size=9)
        if fill:
            cell.fill = fill
    # Apply match-based fill to match status column (col 6)
    if row_data[5]:  # match status
        ws.cell(row=row_num, column=6).fill = match_fill(str(row_data[5]))
    return row_num


def build_excel_report(ground_truth: dict, results: dict):
    print("\n[Stage 6] Building Excel report...")
    wb = openpyxl.Workbook()
    wb.remove(wb.active)  # remove default sheet

    summary_data = []  # for summary sheet

    for sheet_name, tc in ground_truth.items():
        result = results.get(sheet_name, {})

        # Create sheet (Excel sheet names max 31 chars)
        safe_name = sheet_name[:31]
        ws = wb.create_sheet(title=safe_name)

        # Sheet title row
        ws.merge_cells("A1:G1")
        title_cell = ws["A1"]
        title_cell.value = f"{sheet_name} — {tc['description']}"
        title_cell.fill = ORANGE
        title_cell.font = Font(bold=True, size=11)
        title_cell.alignment = Alignment(wrap_text=True, vertical="center")
        ws.row_dimensions[1].height = 40

        # Column headers
        style_header_row(ws, 2)

        if "error" in result:
            # Error row
            add_row(ws, [
                tc["feature_id"], "ERROR", result.get("raw", result["error"]),
                "", "", "Error", "Claude API or JSON parse error"
            ])
            summary_data.append({
                "sheet": sheet_name,
                "desc_match": "Error",
                "steps_total": len(tc["steps"]),
                "steps_accurate": 0,
                "steps_partial": 0,
                "steps_missing": 0,
            })
            continue

        # ── Description row ──
        desc_info = result.get("description", {})
        add_row(ws, [
            tc["feature_id"],
            "DESCRIPTION",
            tc["description"],
            desc_info.get("source_doc", ""),
            desc_info.get("source_page", ""),
            desc_info.get("match_status", ""),
            desc_info.get("notes", ""),
        ], fill=BLUE)

        # ── Step rows ──
        step_results = {s["step_num"]: s for s in result.get("steps", [])}
        acc = partial = missing = 0

        for step in tc["steps"]:
            snum = step["step_num"]
            sr = step_results.get(snum, {})
            status = sr.get("match_status", "Not Found")

            add_row(ws, [
                "",
                f"Step {snum}",
                step["step"],
                sr.get("source_doc", ""),
                sr.get("source_page", ""),
                status,
                sr.get("notes", ""),
            ])

            if "accurate" in status.lower():
                acc += 1
            elif "partial" in status.lower():
                partial += 1
            else:
                missing += 1

        # Fix row heights
        for row in ws.iter_rows(min_row=3):
            ws.row_dimensions[row[0].row].height = 30

        summary_data.append({
            "sheet": sheet_name,
            "desc_match": desc_info.get("match_status", ""),
            "steps_total": len(tc["steps"]),
            "steps_accurate": acc,
            "steps_partial": partial,
            "steps_missing": missing,
        })

        print(f"  ✓ Sheet written: {sheet_name}")

    # ── Summary sheet ──
    ws_sum = wb.create_sheet(title="SUMMARY", index=0)
    sum_headers = ["Feature", "Description Match", "Total Steps",
                   "Accurate", "Partial", "Not Found", "% Accurate"]
    for col, h in enumerate(sum_headers, start=1):
        c = ws_sum.cell(row=1, column=col, value=h)
        c.fill = GREY
        c.font = Font(bold=True)
        c.alignment = Alignment(horizontal="center")

    for i, row in enumerate(summary_data, start=2):
        pct = (row["steps_accurate"] / row["steps_total"] * 100) if row["steps_total"] else 0
        vals = [
            row["sheet"],
            row["desc_match"],
            row["steps_total"],
            row["steps_accurate"],
            row["steps_partial"],
            row["steps_missing"],
            f"{pct:.0f}%",
        ]
        for col, val in enumerate(vals, start=1):
            c = ws_sum.cell(row=i, column=col, value=val)
            c.alignment = Alignment(horizontal="center")
        # Color desc match
        ws_sum.cell(row=i, column=2).fill = match_fill(row["desc_match"])
        # Color % accurate
        ws_sum.cell(row=i, column=7).fill = match_fill("Accurate" if pct >= 80 else ("Partial" if pct >= 50 else "Not Found"))

    # Summary column widths
    for col, w in enumerate([20, 18, 14, 12, 12, 12, 12], start=1):
        ws_sum.column_dimensions[get_column_letter(col)].width = w

    os.makedirs(os.path.dirname(OUTPUT_EXCEL), exist_ok=True)
    wb.save(OUTPUT_EXCEL)
    print(f"\n✅ Report saved: {OUTPUT_EXCEL}")


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def main():
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise ValueError("GROQ_API_KEY not set. Add it to .env or export it.")

    client = groq.Groq(api_key=api_key)

    # Stage 2: Extract PDFs
    pdf_data = extract_all_pdfs()

    # Stage 3: Parse ground truth
    ground_truth = parse_ground_truth()

    # Load cache if exists (avoid re-calling Claude on re-runs)
    os.makedirs("output", exist_ok=True)
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE) as f:
            results = json.load(f)
        print(f"\n[Cache] Loaded {len(results)} cached results from {CACHE_FILE}")
    else:
        results = {}

    # Stage 4 + 5: For each sheet, build context and call Claude
    print("\n[Stage 4+5] Running Claude cross-checks...")
    for sheet_name, tc in ground_truth.items():
        if sheet_name in results:
            print(f"  SKIP (cached): {sheet_name}")
            continue

        print(f"  → {sheet_name}...", end=" ", flush=True)
        pdf_context = build_pdf_context(sheet_name, pdf_data, max_chars=14000)
        result = claude_cross_check(sheet_name, tc, pdf_context, client)
        results[sheet_name] = result

        # Save cache after each sheet
        with open(CACHE_FILE, "w") as f:
            json.dump(results, f, indent=2)
        print("done")

    # Stage 6: Build report
    build_excel_report(ground_truth, results)


if __name__ == "__main__":
    main()
