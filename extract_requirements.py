"""
Requirements Extraction - Trained Approach
Run with F5 in VS Code
"""

import dspy
import json
import os
from pathlib import Path
from typing import List, Dict
from datetime import datetime
import openpyxl
from dotenv import load_dotenv
import sys

# Load environment
load_dotenv()

# ============================================================================
# GENERIC TRAINING EXAMPLES
# ============================================================================

# POSITIVE: Things a user can SEE or DO in the application
POSITIVE_EXAMPLES = [
    {"text": "Display dashboard with key metrics and charts", "title": "Dashboard Display", "description": "Show key metrics and charts on main dashboard page", "type": "UI", "is_requirement": True},
    {"text": "Export data to CSV, PDF, Excel formats", "title": "Export Functionality", "description": "Allow users to export data in multiple formats including CSV, PDF, Excel, PNG, JPEG", "type": "Functional", "is_requirement": True},
    {"text": "Filter results by NAG group", "title": "NAG Group Filter", "description": "Implementation of NAG filter within dashboard screen", "type": "Functional", "is_requirement": True},
    {"text": "Click bar chart to view detailed breakdown", "title": "Chart Drilldown", "description": "User can click chart elements to see detailed data breakdown", "type": "Functional", "is_requirement": True},
    {"text": "Display usage summary with tabs for Data, Voice, Text", "title": "Usage Summary Tabs", "description": "Display tabs for Data, Voice, Long Distance, Text Messaging usage", "type": "UI", "is_requirement": True},
    {"text": "User can favorite items for quick access", "title": "Favorite Feature", "description": "Allow users to mark items as favorites for default view", "type": "Functional", "is_requirement": True},
    {"text": "Display 14 months billed and unbilled data usage in bar chart", "title": "Data Usage Bar Chart", "description": "Bar chart showing 14+ months of billed and unbilled data usage", "type": "UI", "is_requirement": True},
    {"text": "Display notification when task completes", "title": "Completion Notification", "description": "Show notification message when background task finishes", "type": "UI", "is_requirement": True},
    {"text": "Back button to navigate to previous screen", "title": "Back Button Navigation", "description": "Back button to return to previous view from detail tables", "type": "UI", "is_requirement": True},
    {"text": "Display latest orders in shopping widget", "title": "Shopping and Orders Widget", "description": "Display latest orders in the shopping and orders widget", "type": "UI", "is_requirement": True},
    {"text": "Show usage threshold donut wheel", "title": "Usage Threshold Donut", "description": "Display usage threshold donut wheel showing plan utilization percentage", "type": "UI", "is_requirement": True},
    {"text": "Display warranty expiry date on subscriber page", "title": "Warranty Display", "description": "Display warranty expiry date information on subscriber information page", "type": "UI", "is_requirement": True},
]

# NEGATIVE: Things that are NOT user-facing requirements
NEGATIVE_EXAMPLES = [
    # Performance / Non-functional
    {"text": "Dashboard must load within 2 seconds", "title": "Dashboard Load Time", "description": "Page render time under 2 seconds", "type": "Performance", "is_requirement": False},
    {"text": "Support 1000 concurrent users", "title": "Concurrent User Capacity", "description": "System handles 1000 simultaneous users", "type": "Performance", "is_requirement": False},
    # Technical / Architecture
    {"text": "Implement REST API for data access", "title": "REST API Implementation", "description": "Build RESTful API endpoints", "type": "Technical", "is_requirement": False},
    {"text": "Use MongoDB for data storage", "title": "Database Technology", "description": "Store data in MongoDB database", "type": "Technical", "is_requirement": False},
    {"text": "Data integration via ETL pipeline", "title": "Data Integration", "description": "ETL process to sync data from source systems", "type": "Technical", "is_requirement": False},
    {"text": "System integrates with backend BBSSC service", "title": "Backend Integration", "description": "Integration with BBSSC backend service layer", "type": "Technical", "is_requirement": False},
    # Design specs / UI details (too granular)
    {"text": "Display dates in YYYY-MM-DD format", "title": "Date Format Specification", "description": "Use ISO format for date display", "type": "UI Detail", "is_requirement": False},
    {"text": "Use blue color (#0066CC) for primary buttons", "title": "Button Color Scheme", "description": "Primary button color specification", "type": "UI Detail", "is_requirement": False},
    # Vague / Generic
    {"text": "Ensure system security", "title": "Security", "description": "Implement security measures", "type": "Technical", "is_requirement": False},
    {"text": "Optimize performance", "title": "Performance Optimization", "description": "Improve system performance", "type": "Technical", "is_requirement": False},
    {"text": "System must be scalable", "title": "Scalability", "description": "Ensure system can scale", "type": "Technical", "is_requirement": False},
    # Process / Document noise
    {"text": "Conduct annual compliance audit", "title": "Compliance Audit", "description": "Yearly audit for regulatory compliance", "type": "Process", "is_requirement": False},
    {"text": "This document provides a detailed solution design", "title": "Document Overview", "description": "Introduction and executive summary of the document", "type": "Document Noise", "is_requirement": False},
    {"text": "The objective is to implement key enhancements", "title": "Project Objective", "description": "High-level project objective statement", "type": "Document Noise", "is_requirement": False},
    {"text": "Bell needs to introduce enhancements to streamline management", "title": "Problem Statement", "description": "Business problem statement from executive summary", "type": "Document Noise", "is_requirement": False},
    {"text": "Phase 1A scope includes dashboard and warranty features", "title": "Scope Summary", "description": "Summary of what is in scope for this phase", "type": "Document Noise", "is_requirement": False},
    {"text": "Impacted systems include BBSSC and eOrdering", "title": "Impacted Systems", "description": "List of systems affected by the project", "type": "Technical", "is_requirement": False},
    {"text": "High level CS flow diagram", "title": "CS Flow Diagram", "description": "Reference to a conceptual solution flow diagram", "type": "Document Noise", "is_requirement": False},
]

# ============================================================================
# DSPY SIGNATURES
# ============================================================================

class RequirementExtraction(dspy.Signature):
    """Extract ALL user-facing functional requirements from the document text.
    
    A requirement is something an end-user can SEE on screen or DO/interact with 
    in the application. Examples: display a chart, click a button, filter data, 
    export a file, navigate to a page, view a table, toggle tabs.
    
    IMPORTANT:
    - Extract EVERY distinct feature, widget, button, chart, table, filter, or navigation element
    - Each feature should be its OWN separate requirement (do NOT merge multiple features into one)
    - Use SHORT specific titles (e.g. 'NAG Filter', 'Export to CSV', 'Usage Bar Chart')
    
    DO NOT extract: technical architecture, API integrations, performance specs,
    document metadata, executive summaries, or implementation details.
    """
    document_text = dspy.InputField()
    requirements_json = dspy.OutputField(desc="JSON array of ALL user-facing requirements found: [{'title': 'Short specific name', 'description': 'What user sees or does', 'type': 'UI' or 'Functional'}]. Extract every distinct feature separately.")

class RequirementClassifier(dspy.Signature):
    """Strictly classify if this is a genuine user-facing requirement.
    
    Answer 'yes' ONLY if ALL of these are true:
    1. A real end-user can SEE this on screen OR physically DO/interact with it
    2. It describes a specific, testable feature (not vague or generic)
    3. It is NOT about: architecture, integration, performance, security, scalability,
       document structure, project scope, objectives, or implementation approach
    
    When in doubt, answer 'no'. Be strict - we want FEWER, higher quality requirements.
    """
    text = dspy.InputField()
    title = dspy.InputField()
    description = dspy.InputField()
    is_requirement = dspy.OutputField(desc="'yes' ONLY if user can directly see/interact with this feature, 'no' otherwise")
    reason = dspy.OutputField(desc="Brief explanation of why this is or isn't user-facing")

class EnrichRequirement(dspy.Signature):
    """Generate detailed requirement enrichment from a requirement title, description, and source text.
    
    Produce a user story, acceptance criteria, test steps, test scenarios,
    assumptions, and ambiguities for the given requirement.
    """
    requirement_title = dspy.InputField(desc="Short title of the requirement")
    requirement_description = dspy.InputField(desc="Description of the requirement")
    source_text = dspy.InputField(desc="Original document text the requirement was extracted from")
    
    user_story = dspy.OutputField(desc="User story in format: As a [user], I want [feature] so that [benefit]")
    acceptance_criteria = dspy.OutputField(desc="JSON array of acceptance criteria strings, e.g. ['criterion 1', 'criterion 2']")
    test_steps = dspy.OutputField(desc='JSON array of test step objects: [{"step_num": 1, "action": "...", "expected_result": "...", "test_data": "..."}]')
    test_scenarios = dspy.OutputField(desc="JSON array of test scenario strings, e.g. ['scenario 1', 'scenario 2']")
    assumptions = dspy.OutputField(desc="JSON array of assumption strings")
    ambiguities = dspy.OutputField(desc="JSON array of ambiguity strings")
    confidence = dspy.OutputField(desc="'high', 'medium', or 'low' based on how clear the requirement is")

# ============================================================================
# EXTRACTOR MODULE
# ============================================================================

class TrainedExtractor(dspy.Module):
    def __init__(self):
        super().__init__()
        self.extractor = dspy.ChainOfThought(RequirementExtraction)
        self.classifier = dspy.ChainOfThought(RequirementClassifier)
        
    def forward(self, document_text: str) -> Dict:
        result = self.extractor(document_text=document_text)
        
        try:
            raw = result.requirements_json
            # Handle markdown-wrapped JSON
            if '```' in raw:
                raw = raw.split('```')[1]
                if raw.startswith('json'):
                    raw = raw[4:]
            candidates = json.loads(raw.strip())
        except:
            candidates = []
        
        valid_requirements = []
        filtered_out = []
        
        for candidate in candidates:
            title = candidate.get('title', '')
            desc = candidate.get('description', '')
            
            # Pre-filter: skip obviously bad candidates (only very clear noise)
            skip_keywords = [
                'executive summary', 'problem statement',
                'impacted system', 'high level flow',
                'this document provides', 'conceptual solution',
                'document overview'
            ]
            combined = f"{title} {desc}".lower()
            if any(kw in combined for kw in skip_keywords):
                filtered_out.append(candidate)
                continue
            
            classification = self.classifier(
                text=f"{title} - {desc}",
                title=title,
                description=desc
            )
            
            if classification.is_requirement.lower().strip() in ['yes', 'true']:
                valid_requirements.append(candidate)
            else:
                filtered_out.append(candidate)
        
        return {
            'requirements': valid_requirements,
            'filtered_out': filtered_out
        }

# ============================================================================
# TRAINING
# ============================================================================

def train_extractor(extractor: TrainedExtractor):
    print("\n🎓 Training extractor...")
    
    train_examples = []
    
    for ex in POSITIVE_EXAMPLES:
        train_examples.append(
            dspy.Example(
                text=ex['text'],
                title=ex['title'],
                description=ex['description'],
                is_requirement='yes',
                reason="User-facing feature that can be seen or interacted with"
            ).with_inputs('text', 'title', 'description')
        )
    
    for ex in NEGATIVE_EXAMPLES:
        train_examples.append(
            dspy.Example(
                text=ex['text'],
                title=ex['title'],
                description=ex['description'],
                is_requirement='no',
                reason="Not a user-facing feature - technical/noise/vague"
            ).with_inputs('text', 'title', 'description')
        )
    
    from dspy.teleprompt import BootstrapFewShot
    
    def metric(example, prediction, trace=None):
        predicted = prediction.is_requirement.lower().strip() in ['yes', 'true']
        expected = example.is_requirement.lower().strip() in ['yes', 'true']
        return 1.0 if predicted == expected else 0.0
    
    optimizer = BootstrapFewShot(
        metric=metric,
        max_bootstrapped_demos=8,
        max_labeled_demos=8
    )
    
    extractor.classifier = optimizer.compile(extractor.classifier, trainset=train_examples)
    print("✓ Training complete")
    return extractor

# ============================================================================
# DOCUMENT PROCESSING
# ============================================================================

def process_pdf(pdf_path: str) -> List[str]:
    """Extract text from PDF as per-page list, with OCR fallback.
    Returns a list of strings, one per page (used as individual chunks).
    """
    pages_text = []
    
    # Try standard text extraction first
    try:
        import pymupdf4llm
        text = pymupdf4llm.to_markdown(pdf_path)
        if text and len(text.strip()) > 100:
            print("  ✓ Text extracted via pymupdf4llm")
            # Split by page markers if present, otherwise return as single chunk
            return [text]
    except Exception as e:
        print(f"  ⚠ pymupdf4llm failed: {e}")
    
    # Fallback: OCR for image-based PDFs with image preprocessing
    print("  ⚠ Standard extraction returned empty — falling back to OCR...")
    try:
        import pymupdf
        import pytesseract
        from PIL import Image, ImageEnhance, ImageFilter
        import io
        
        doc = pymupdf.open(pdf_path)
        
        for page_num in range(len(doc)):
            page = doc[page_num]
            # Render page at 300 DPI for better OCR quality
            pix = page.get_pixmap(dpi=300)
            img = Image.open(io.BytesIO(pix.tobytes('png')))
            
            # Image preprocessing for better OCR
            enhancer = ImageEnhance.Contrast(img)
            img = enhancer.enhance(1.5)
            img = img.filter(ImageFilter.SHARPEN)
            
            # OCR with page segmentation mode 6 (block of text)
            page_text = pytesseract.image_to_string(img, config='--psm 6')
            
            if page_text.strip():
                pages_text.append(page_text)
                print(f"  ✓ Page {page_num + 1}: {len(page_text)} chars via OCR")
            else:
                print(f"  ⚠ Page {page_num + 1}: No text detected")
        
        doc.close()
        
        if pages_text:
            total = sum(len(p) for p in pages_text)
            print(f"  ✓ OCR complete: {total} total chars from {len(pages_text)} pages")
    except Exception as e:
        print(f"  ✗ OCR failed: {e}")
    
    return pages_text

def chunk_document(text: str, max_chars: int = 6000) -> List[str]:
    chunks = []
    current = ""
    for para in text.split('\n\n'):
        if len(current) + len(para) < max_chars:
            current += para + "\n\n"
        else:
            if current:
                chunks.append(current)
            current = para + "\n\n"
    if current:
        chunks.append(current)
    return chunks

def calculate_similarity(text1: str, text2: str) -> float:
    """Word overlap similarity (Jaccard)."""
    words1 = set(text1.lower().split())
    words2 = set(text2.lower().split())
    if not words1 or not words2:
        return 0.0
    intersection = words1.intersection(words2)
    union = words1.union(words2)
    return len(intersection) / len(union)

def deduplicate_requirements(reqs: List[Dict], similarity_threshold: float = 0.45) -> List[Dict]:
    """Remove duplicate requirements using word-overlap similarity."""
    unique = []
    for req in reqs:
        is_dup = False
        req_text = f"{req.get('title', '')} {req.get('description', '')}".lower()
        
        for existing in unique:
            existing_text = f"{existing.get('title', '')} {existing.get('description', '')}".lower()
            sim = calculate_similarity(req_text, existing_text)
            if sim > similarity_threshold:
                is_dup = True
                # Keep the one with the longer description
                if len(req.get('description', '')) > len(existing.get('description', '')):
                    unique.remove(existing)
                    unique.append(req)
                break
        
        if not is_dup:
            unique.append(req)
    
    return unique

# ============================================================================
# ENRICHMENT
# ============================================================================

def parse_json_field(raw: str) -> list:
    """Safely parse a JSON array string from LLM output."""
    try:
        if '```' in raw:
            raw = raw.split('```')[1]
            if raw.startswith('json'):
                raw = raw[4:]
        result = json.loads(raw.strip())
        if isinstance(result, list):
            return result
        return [result]
    except:
        # If JSON parsing fails, return as single-item list
        return [raw.strip()] if raw.strip() else []

def enrich_requirements(requirements: List[Dict], source_text: str, model_name: str, source_file: str) -> List[Dict]:
    """Enrich each extracted requirement with user story, test steps, etc."""
    enricher = dspy.ChainOfThought(EnrichRequirement)
    enriched = []
    
    for i, req in enumerate(requirements, 1):
        title = req.get('title', '')
        desc = req.get('description', '')
        print(f"  Enriching {i}/{len(requirements)}: {title}...", end='')
        
        try:
            result = enricher(
                requirement_title=title,
                requirement_description=desc,
                source_text=source_text[:4000]  # Limit context to avoid token overflow
            )
            
            enriched_req = {
                'is_requirement': True,
                'short_title': title,
                'description': desc,
                'user_story': result.user_story,
                'acceptance_criteria': parse_json_field(result.acceptance_criteria),
                'test_steps': parse_json_field(result.test_steps),
                'test_scenarios': parse_json_field(result.test_scenarios),
                'assumptions': parse_json_field(result.assumptions),
                'ambiguities': parse_json_field(result.ambiguities),
                'confidence': result.confidence.strip().lower(),
                'extraction_model': model_name,
                'extraction_timestamp': datetime.now().isoformat(),
                'validation_confirmed': True,
                'metadata': {
                    'source_file': source_file,
                    'extraction_timestamp': datetime.now().isoformat(),
                    'extraction_model': model_name,
                    'validation_confirmed': True
                }
            }
            enriched.append(enriched_req)
            print(f" ✓")
        except Exception as e:
            print(f" ✗ {e}")
            # Still include basic info on failure
            enriched.append({
                'is_requirement': True,
                'short_title': title,
                'description': desc,
                'user_story': '',
                'acceptance_criteria': [],
                'test_steps': [],
                'test_scenarios': [],
                'assumptions': [],
                'ambiguities': [],
                'confidence': 'low',
                'extraction_model': model_name,
                'extraction_timestamp': datetime.now().isoformat(),
                'validation_confirmed': False,
                'metadata': {
                    'source_file': source_file,
                    'extraction_timestamp': datetime.now().isoformat(),
                    'extraction_model': model_name,
                    'validation_confirmed': False
                }
            })
    
    return enriched



# ============================================================================
# MAIN
# ============================================================================

def extract_requirements(config: Dict = None) -> Dict:
    """Core extraction logic. Returns dict with project name and requirements.
    Can be called standalone or from FastAPI.
    """
    print("="*80)
    print("REQUIREMENTS EXTRACTION - TRAINED APPROACH")
    print("="*80)
    
    # Config
    if config is None:
        config_file = Path("config/config.json")
        if not config_file.exists():
            raise FileNotFoundError(f"Config not found: {config_file}")
        with open(config_file) as f:
            config = json.load(f)
    
    project = config['project_name']
    input_file = Path(config['input_pdf'])
    output_dir = Path(config['output_dir'])
    
    if not input_file.exists():
        raise FileNotFoundError(f"Input file not found: {input_file}")
    
    output_dir.mkdir(exist_ok=True)
    
    # Setup DSPy
    groq_key = os.getenv("GROQ_API_KEY")
    if not groq_key:
        raise ValueError("GROQ_API_KEY not found in .env")
    
    lm = dspy.LM('groq/llama-3.3-70b-versatile', api_key=groq_key)
    dspy.configure(lm=lm)
    print("✓ DSPy configured")
    
    # Train
    extractor = TrainedExtractor()
    extractor = train_extractor(extractor)
    
    # Process PDF into per-page text
    print(f"\n📄 Processing: {input_file}")
    page_texts = process_pdf(str(input_file))
    if not page_texts:
        raise RuntimeError("Failed to extract text from PDF (both standard and OCR failed)")
    
    # Build chunks: each page is its own chunk, plus combined for context
    chunks = []
    for pt in page_texts:
        # Split large pages into sub-chunks if needed
        if len(pt) > 6000:
            chunks.extend(chunk_document(pt))
        else:
            chunks.append(pt)
    print(f"✓ {len(page_texts)} pages → {len(chunks)} chunks")
    
    # Extract
    print(f"\n🔍 Extracting requirements...")
    all_reqs = []
    all_filtered = []
    for i, chunk in enumerate(chunks, 1):
        if len(chunk.strip()) < 50:  # Skip near-empty chunks
            print(f"  Chunk {i}/{len(chunks)}... ⏭ too short, skipping")
            continue
        print(f"  Chunk {i}/{len(chunks)}...", end='')
        try:
            result = extractor(document_text=chunk)
            all_reqs.extend(result['requirements'])
            all_filtered.extend(result['filtered_out'])
            print(f" ✓ {len(result['requirements'])} accepted, {len(result['filtered_out'])} filtered")
        except Exception as e:
            print(f" ✗ {e}")
    
    print(f"\n  Raw: {len(all_reqs)} accepted, {len(all_filtered)} filtered out")
    
    # Deduplicate using similarity
    unique = deduplicate_requirements(all_reqs)
    print(f"  After dedup: {len(all_reqs)} → {len(unique)} unique")
    
    # Add IDs
    for i, req in enumerate(unique, 1):
        req['requirement_id'] = f"{project.upper()}-{i:03d}"
    
    # Enrich requirements with user stories, test steps, etc.
    source_file = config.get('input_pdf', '')
    model_name = 'llama-3.3-70b-versatile'
    full_source_text = '\n\n'.join(page_texts)
    
    print(f"\n🔧 Enriching {len(unique)} requirements...")
    enriched = enrich_requirements(unique, full_source_text, model_name, source_file)
    print(f"✓ Enriched {len(enriched)} requirements")
    
    # Build result (both formats: simple for eval, enriched for backend)
    result_data = {'project': project, 'requirements': unique}
    enriched_data = {'project': project, 'requirements': enriched}
    
    # Save simple format (for evaluation)
    output_file = output_dir / f"{project}_requirements.json"
    with open(output_file, 'w') as f:
        json.dump(result_data, f, indent=2)
    print(f"✓ Saved simple: {output_file}")
    
    # Save enriched format
    enriched_file = output_dir / f"{project}_requirements_enriched.json"
    with open(enriched_file, 'w') as f:
        json.dump(enriched_data, f, indent=2)
    print(f"✓ Saved enriched: {enriched_file}")
    
    print(f"\n✅ Done! {len(unique)} requirements extracted and enriched")
    
    return result_data

def main():
    try:
        extract_requirements()
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
