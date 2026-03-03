"""
Quick test for v4.0 Enrichment-Pass BR Extraction.

Run from the project root:
    python test_v4_extraction.py

Make sure USE_V4_BR_EXTRACTION=true is set in .env before running.
"""
import sys
import logging
from pathlib import Path

# Add project root to path
BASE_DIR = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR))

from dotenv import load_dotenv
load_dotenv()

from logging_config import setup_logging
setup_logging("INFO")   # change to "DEBUG" for full detail
logger = logging.getLogger(__name__)

from extraction.pipeline import extract_from_files

# Use these two Feature documents as test input (Primary docs)
TEST_FILES = [
    "inputs/Play to Win SS Ph1 - Dashboard_Features.pdf",
    "inputs/Play to Win SS Ph1 - Warranty_Feature.pdf",
]

# Filter to only files that exist
file_paths = [str(BASE_DIR / f) for f in TEST_FILES if (BASE_DIR / f).exists()]

if not file_paths:
    logger.error("No test files found in inputs/")
    sys.exit(1)

logger.info(f"Testing with {len(file_paths)} file(s):")
for f in file_paths:
    logger.info(f"  - {Path(f).name}")

result = extract_from_files(
    project_name="test_v4",
    file_paths=file_paths,
    output_dir="output/test_v4",
)

requirements = result.get("requirements", [])
logger.info("=" * 60)
logger.info(f"RESULT: {len(requirements)} requirements extracted")
logger.info("=" * 60)
for i, req in enumerate(requirements, 1):
    logger.info(f"[{i}] {req.get('title', 'N/A')}")
    logger.info(f"     Type      : {req.get('type', '')}")
    logger.info(f"     Scenarios : {len(req.get('test_scenarios', []))}")
    logger.info(f"     ACs       : {len(req.get('acceptance_criteria', []))}")
    for sc in req.get("test_scenarios", []):
        logger.info(f"       - {sc}")

logger.info(f"Full output saved to: output/test_v4/")
logger.info(f"Log file saved to   : logs/prism.log")
