"""
Manual Requirement Extraction CLI — Simplified Wrapper

This script provides a command-line interface for human-guided 
requirement extraction from a specific page of a document.
"""

import sys
from pathlib import Path
from dotenv import load_dotenv
from extraction.manual import ManualExtractor

load_dotenv()

def main():
    if len(sys.argv) < 4:
        print("Usage: python manual_extract.py <file_path> <page_no> <description>")
        print("Example: python manual_extract.py input/ptw/doc.pdf 4 \"Dashboard charts\"")
        sys.exit(1)

    file_path = sys.argv[1]
    try:
        page_no = int(sys.argv[2])
    except ValueError:
        print("Error: page_no must be an integer.")
        sys.exit(1)
        
    description = " ".join(sys.argv[3:])

    print(f"--- Manual Extraction ---")
    print(f"File: {file_path}")
    print(f"Page: {page_no}")
    print(f"Goal: {description}")
    print(f"Processing...")

    extractor = ManualExtractor()
    result = extractor.extract_from_page(file_path, description, page_no)

    if result["status"] == "success":
        print("\n✅ Requirement Found:")
        import json
        print(json.dumps(result["requirement"], indent=2))
    elif result["status"] == "no_requirements":
        print(f"\nℹ️ No requirement found: {result['message']}")
    else:
        print(f"\n❌ Error: {result.get('message', 'Unknown error')}")

if __name__ == "__main__":
    main()
