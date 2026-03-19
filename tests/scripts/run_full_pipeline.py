import os
import json
import logging
import tempfile
import shutil
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

# Import our updated project modules
from extraction.generators.v4_br_extractor import extract_requirements
from testgen.pipeline import TestGenPipeline
from extraction.v4_utils import Config

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger("prism.full_pipeline")

# Load environment variables
load_dotenv()

def run_full_pipeline():
    project_name = "ptw_complete_v4"
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_base = Path(f"/Users/javid/Documents/prism/approach2_project/output/{project_name}_{timestamp}")
    output_base.mkdir(parents=True, exist_ok=True)

    # 1. Define Input Files and Tiers
    input_files = [
        "data/inputs/BBMBT-3917.pdf",
        "data/inputs/BBMBT-3920.pdf",
        "data/inputs/BBMOMNI-4424.pdf",
        "data/inputs/BBMOMNI-5101.pdf",
        "data/inputs/BBMOMNI-5111.pdf",
        "data/inputs/BBMOMNI-5113.pdf",
        "data/inputs/BBMOMNI-5114.pdf",
        "data/inputs/BBMSA-13025.pdf",
        "data/inputs/Play to Win SS Ph1 - Dashboard_Features.pdf",
        "data/inputs/Play to Win SS Ph1 - Warranty_Feature.pdf",
        "data/inputs/PTW Self Serve Phase 1 Solution.pdf",
        "data/inputs/Requirements Traceability Matrix.pdf",
        "data/inputs/Test Strategy_PTW SS Ph1_V0.1.pptx"
    ]
    
    document_tiers = {
        "Play to Win SS Ph1 - Dashboard_Features.pdf": "primary",
        "Play to Win SS Ph1 - Warranty_Feature.pdf": "primary",
    }
    # All others default to 'supporting' as per New_code logic

    # 2. Phase 1: Business Requirement Extraction
    logger.info("="*60)
    logger.info("PHASE 1: EXTRACTING REQUIREMENTS (New_code v4.0 Logic)")
    logger.info("="*60)
    
    # We need to copy these specific files to a temp directory for the extractor
    with tempfile.TemporaryDirectory() as tmp_input_dir:
        for f in input_files:
            shutil.copy2(f, tmp_input_dir)
        
        # Run extraction
        requirements = extract_requirements(
            input_dir=tmp_input_dir,
            output_dir=str(output_base / "br"),
            document_tiers=document_tiers
        )
    
    logger.info(f"Done! {len(requirements)} requirements extracted.")

    # 3. Phase 2: Test Case Generation
    logger.info("\n" + "="*60)
    logger.info("PHASE 2: GENERATING TEST CASES (Scenario-Based Logic)")
    logger.info("="*60)
    
    # Prepare requirements for pipeline (convert BusinessRequirement objects to dicts)
    req_dicts = []
    for r in requirements:
        req_dicts.append({
            "requirement_id": r.requirement_id,
            "feature_name": r.feature_name,
            "title": r.feature_name,
            "description": r.description,
            "acceptance_criteria": r.acceptance_criteria,
            "test_scenarios": r.test_scenarios,
            "source_file": r.source_file,
            "page_start": r.page_start,
            "page_end": r.page_end
        })

    # Initialize and run TC pipeline
    tc_pipeline = TestGenPipeline(mode='hybrid')
    
    # We provide the full input files list for context building
    tc_result = tc_pipeline.run(
        requirements=req_dicts,
        project_name=project_name,
        output_dir=str(output_base / "tc"),
        document_paths=input_files
    )

    # 4. Final Report
    logger.info("\n" + "="*80)
    logger.info("PIPELINE EXECUTION COMPLETE")
    logger.info("="*80)
    logger.info(f"Project Name:    {project_name}")
    logger.info(f"Requirements:    {len(requirements)}")
    logger.info(f"Test Cases:     {tc_result.get('total_test_cases', 0)}")
    logger.info(f"BR Output Dir:   {output_base / 'br'}")
    logger.info(f"TC JSON Output:  {tc_result.get('json_path')}")
    logger.info(f"TC Excel Output: {tc_result.get('excel_path')}")
    logger.info("="*80)

if __name__ == "__main__":
    run_full_pipeline()
