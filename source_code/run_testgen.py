"""
Test Case Generation CLI

Usage:
    # Requirements only (basic mode)
    python run_testgen.py <project_name>

    # Requirements + Document context (rich mode — recommended!)
    python run_testgen.py <project_name> --doc <path_to_document>

Examples:
    python run_testgen.py ptw
    python run_testgen.py ptw --doc input/ptw/PTW_Self_Serve_Solution.pdf
    python run_testgen.py bbmsa --doc input/bbmsa/doc1.pdf --doc input/bbmsa/doc2.docx
"""

import sys
import os
import argparse
from dotenv import load_dotenv

load_dotenv()


def main():
    parser = argparse.ArgumentParser(
        description="Phase 2: Generate test cases from extracted requirements",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python run_testgen.py sample
  python run_testgen.py ptw --doc input/ptw/PTW_Self_Serve.pdf
  python run_testgen.py bbmsa --doc doc1.pdf --doc doc2.docx
        """,
    )
    parser.add_argument(
        "project_name",
        help="Project name (looks for output/<project>_requirements.json)",
    )
    parser.add_argument(
        "--doc",
        action="append",
        dest="documents",
        default=[],
        help="Path to a source document (PDF/DOCX/PPTX/TXT). "
             "Can be specified multiple times. Provides richer context for test cases.",
    )
    parser.add_argument(
        "--output", "-o",
        default="output",
        help="Output directory (default: output)",
    )

    args = parser.parse_args()
    project_name = args.project_name

    # Find the requirements file
    req_file = f"output/{project_name}_requirements.json"
    if not os.path.exists(req_file):
        # Try alternate locations
        alt_paths = [
            f"outputs/output-{project_name}-new/{project_name}_requirements.json",
            f"output/{project_name}_reqs.json",
        ]
        for alt in alt_paths:
            if os.path.exists(alt):
                req_file = alt
                break
        else:
            print(f"❌ Requirements file not found: {req_file}")
            print(f"   Run Phase 1 first, or place your requirements JSON at: {req_file}")
            sys.exit(1)

    # Validate document paths
    doc_paths = []
    for doc in args.documents:
        if os.path.exists(doc):
            doc_paths.append(doc)
        else:
            print(f"⚠ Document not found (skipping): {doc}")

    print(f"\n{'='*60}")
    print(f"PHASE 2: TEST CASE GENERATION")
    print(f"{'='*60}")
    print(f"  Project:      {project_name}")
    print(f"  Requirements: {req_file}")
    if doc_paths:
        print(f"  Documents:    {len(doc_paths)} source document(s)")
        for d in doc_paths:
            print(f"                  → {d}")
    else:
        print(f"  Documents:    None (requirements-only mode)")
    print(f"{'='*60}")

    from testgen import TestGenPipeline

    pipeline = TestGenPipeline()
    result = pipeline.run_from_json(
        json_path=req_file,
        project_name=project_name,
        output_dir=args.output,
        document_paths=doc_paths if doc_paths else None,
    )

    print(f"\n{'='*60}")
    print(f"PHASE 2 COMPLETE")
    print(f"{'='*60}")
    print(f"  Requirements: {result['total_requirements']}")
    print(f"  Test Cases:   {result['total_test_cases']}")
    print(f"  JSON:         {result['json_path']}")
    print(f"  Excel:        {result['excel_path']}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
