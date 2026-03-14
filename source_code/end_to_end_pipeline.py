import os
import sys
import json
import argparse
from pathlib import Path
from dotenv import load_dotenv

# Add current directory to path for imports
BASE_DIR = Path(__file__).parent.absolute()
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

load_dotenv()

# PRISM Modules
from s3_utils import upload_to_s3, download_from_s3
from extraction.pipeline import extract_from_files
from testgen.pipeline import TestGenPipeline
from duplication_service import filter_unique_requirements

def process_documents_e2e(project_id: str, local_file_paths: list):
    """
    End-to-End Execution for Multiple Files:
    1. Upload All Documents to S3
    2. Extract Requirements from all files
    3. Filter Duplicates
    4. Generate Consolidated Test Cases
    """
    print(f"\n--- [Phase 1: Uploading {len(local_file_paths)} Documents] ---")
    s3_urls = []
    local_download_paths = []
    
    temp_dir = Path(f"output/{project_id}/temp")
    temp_dir.mkdir(parents=True, exist_ok=True)

    for path in local_file_paths:
        file_name = Path(path).name
        s3_key = f"projects/{project_id}/input/{file_name}"
        s3_url = upload_to_s3(path, s3_key)
        s3_urls.append(s3_url)
        
        # Download simulation
        local_path = download_from_s3(s3_url, str(temp_dir))
        local_download_paths.append(local_path)

    print(f"\n--- [Phase 2: Requirement Extraction] ---")
    # Call the requirement extraction for ALL files at once
    result = extract_from_files(
        project_name=project_id,
        file_paths=local_download_paths,
        output_dir=f"output/{project_id}/requirements"
    )
    requirements = result.get("requirements", [])
    print(f"✓ Extracted {len(requirements)} requirements from {len(local_download_paths)} files.")

    if not requirements:
        print("⚠ No requirements found. Stopping.")
        return

    # Phase 3: Semantic Deduplication
    print(f"\n--- [Phase 3: Deduplication Check] ---")
    unique_requirements = filter_unique_requirements(
        project_id=project_id,
        new_requirements=requirements,
        threshold=0.85
    )
    print(f"✓ After filtering: {len(unique_requirements)} unique requirements.")

    if not unique_requirements:
        print("ℹ All requirements are duplicates. No new test cases needed.")
        return

    print(f"\n--- [Phase 4: Test Case Generation] ---")
    testgen = TestGenPipeline()
    tc_result = testgen.run(
        requirements=unique_requirements,
        project_name=project_id,
        output_dir=f"output/{project_id}/testcases",
        document_paths=local_download_paths  # Consolidated context from all files
    )

    print(f"\n--- [Execution Summary] ---")
    print(f"Project ID: {project_id}")
    print(f"Files Processed: {len(local_file_paths)}")
    print(f"Unique Requirements: {len(unique_requirements)}")
    print(f"Generated Test Cases: {tc_result.get('total_test_cases', 0)}")
    print(f"Output Saved To: output/{project_id}/")
    print(f"\n End-to-End Multi-File Process Complete!")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="PRISM Multi-File End-to-End Extraction & Test Generation")
    parser.add_argument("--project", required=True, help="Project name/ID")
    parser.add_argument("--files", nargs="+", required=True, help="Paths to one or more local document files")
    
    args = parser.parse_args()
    
    valid_files = []
    for f in args.files:
        if os.path.exists(f):
            valid_files.append(f)
        else:
            print(f"⚠ Warning: File not found at {f}, skipping.")
            
    if not valid_files:
        print("Error: No valid files provided.")
        sys.exit(1)
        
    process_documents_e2e(args.project, valid_files)
