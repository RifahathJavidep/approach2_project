"""
Requirements Extraction - Trained Approach
Run with F5 in VS Code
"""

import dspy
import json
import os
from pathlib import Path
from typing import List, Dict
import openpyxl
from dotenv import load_dotenv
import sys

# Load environment
load_dotenv()

# ============================================================================
# GENERIC TRAINING EXAMPLES
# ============================================================================

POSITIVE_EXAMPLES = [
    {"text": "Display dashboard with key metrics and charts", "title": "Dashboard Display", "description": "Show key metrics and charts on main dashboard page", "type": "UI", "is_requirement": True},
    {"text": "Export data to CSV, PDF, Excel formats", "title": "Export Functionality", "description": "Allow users to export data in multiple formats", "type": "Functional", "is_requirement": True},
    {"text": "Filter results by date range", "title": "Date Range Filter", "description": "User can filter displayed data by selecting date range", "type": "Functional", "is_requirement": True},
    {"text": "Click bar chart to view detailed breakdown", "title": "Chart Drilldown", "description": "User can click chart elements to see detailed data", "type": "Functional", "is_requirement": True},
    {"text": "Search by keyword or ID", "title": "Search Functionality", "description": "Users can search records using keywords or IDs", "type": "Functional", "is_requirement": True},
    {"text": "User can favorite items for quick access", "title": "Favorite Feature", "description": "Allow users to mark items as favorites", "type": "Functional", "is_requirement": True},
    {"text": "Dropdown menu to select category", "title": "Category Selector", "description": "Dropdown to choose from available categories", "type": "UI", "is_requirement": True},
    {"text": "Display notification when task completes", "title": "Completion Notification", "description": "Show notification message when background task finishes", "type": "UI", "is_requirement": True}
]

NEGATIVE_EXAMPLES = [
    {"text": "Dashboard must load within 2 seconds", "title": "Dashboard Load Time", "description": "Page render time under 2 seconds", "type": "Performance", "is_requirement": False},
    {"text": "Support 1000 concurrent users", "title": "Concurrent User Capacity", "description": "System handles 1000 simultaneous users", "type": "Performance", "is_requirement": False},
    {"text": "Implement REST API for data access", "title": "REST API Implementation", "description": "Build RESTful API endpoints", "type": "Technical", "is_requirement": False},
    {"text": "Use MongoDB for data storage", "title": "Database Technology", "description": "Store data in MongoDB database", "type": "Technical", "is_requirement": False},
    {"text": "Data integration via ETL pipeline", "title": "Data Integration", "description": "ETL process to sync data from source systems", "type": "Technical", "is_requirement": False},
    {"text": "Display dates in YYYY-MM-DD format", "title": "Date Format Specification", "description": "Use ISO format for date display", "type": "UI", "is_requirement": False},
    {"text": "Use blue color (#0066CC) for primary buttons", "title": "Button Color Scheme", "description": "Primary button color specification", "type": "UI", "is_requirement": False},
    {"text": "Ensure system security", "title": "Security", "description": "Implement security measures", "type": "Technical", "is_requirement": False},
    {"text": "Optimize performance", "title": "Performance Optimization", "description": "Improve system performance", "type": "Technical", "is_requirement": False},
    {"text": "System must be scalable", "title": "Scalability", "description": "Ensure system can scale", "type": "Technical", "is_requirement": False},
    {"text": "Conduct annual compliance audit", "title": "Compliance Audit", "description": "Yearly audit for regulatory compliance", "type": "Process", "is_requirement": False}
]

# ============================================================================
# DSPY SIGNATURES
# ============================================================================

class RequirementExtraction(dspy.Signature):
    """Extract user-facing requirements from text."""
    document_text = dspy.InputField()
    requirements_json = dspy.OutputField(desc="JSON array: [{'title': '...', 'description': '...', 'type': 'UI/Functional'}]")

class RequirementClassifier(dspy.Signature):
    """Classify if text is a user-facing requirement."""
    text = dspy.InputField()
    title = dspy.InputField()
    description = dspy.InputField()
    is_requirement = dspy.OutputField(desc="'yes' if user can see/do this, 'no' otherwise")
    reason = dspy.OutputField(desc="Brief explanation")

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
            candidates = json.loads(result.requirements_json)
        except:
            candidates = []
        
        valid_requirements = []
        filtered_out = []
        
        for candidate in candidates:
            classification = self.classifier(
                text=f"{candidate.get('title', '')} - {candidate.get('description', '')}",
                title=candidate.get('title', ''),
                description=candidate.get('description', '')
            )
            
            if classification.is_requirement.lower() in ['yes', 'true']:
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
                reason="User-facing feature"
            ).with_inputs('text', 'title', 'description')
        )
    
    for ex in NEGATIVE_EXAMPLES:
        train_examples.append(
            dspy.Example(
                text=ex['text'],
                title=ex['title'],
                description=ex['description'],
                is_requirement='no',
                reason="Not user-facing"
            ).with_inputs('text', 'title', 'description')
        )
    
    from dspy.teleprompt import BootstrapFewShot
    
    def metric(example, prediction, trace=None):
        predicted = prediction.is_requirement.lower() in ['yes', 'true']
        expected = example.is_requirement.lower() in ['yes', 'true']
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

def process_pdf(pdf_path: str) -> str:
    try:
        import pymupdf4llm
        return pymupdf4llm.to_markdown(pdf_path)
    except Exception as e:
        print(f"Error: {e}")
        return ""

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

# ============================================================================
# MAIN
# ============================================================================

def main():
    print("="*80)
    print("REQUIREMENTS EXTRACTION - TRAINED APPROACH")
    print("="*80)
    
    # Config
    config_file = Path("config/config.json")
    if not config_file.exists():
        print(f"ERROR: {config_file} not found")
        return
    
    with open(config_file) as f:
        config = json.load(f)
    
    project = config['project_name']
    input_file = Path(config['input_pdf'])
    output_dir = Path(config['output_dir'])
    
    if not input_file.exists():
        print(f"ERROR: Input file not found: {input_file}")
        return
    
    output_dir.mkdir(exist_ok=True)
    
    # Setup DSPy
    groq_key = os.getenv("GROQ_API_KEY")
    if not groq_key:
        print("ERROR: GROQ_API_KEY not found in .env")
        return
    
    lm = dspy.LM('groq/llama-3.3-70b-versatile', api_key=groq_key)
    dspy.configure(lm=lm)
    print("✓ DSPy configured")
    
    # Train
    extractor = TrainedExtractor()
    extractor = train_extractor(extractor)
    
    # Process
    print(f"\n📄 Processing: {input_file}")
    doc_text = process_pdf(str(input_file))
    if not doc_text:
        print("ERROR: Failed to extract text")
        return
    
    chunks = chunk_document(doc_text)
    print(f"✓ Split into {len(chunks)} chunks")
    
    # Extract
    print(f"\n🔍 Extracting...")
    all_reqs = []
    for i, chunk in enumerate(chunks, 1):
        print(f"  Chunk {i}/{len(chunks)}...", end='')
        try:
            result = extractor(document_text=chunk)
            all_reqs.extend(result['requirements'])
            print(f" ✓ {len(result['requirements'])}")
        except Exception as e:
            print(f" ✗ {e}")
    
    # Deduplicate
    unique = []
    seen = set()
    for req in all_reqs:
        key = req['title'].lower()
        if key not in seen:
            unique.append(req)
            seen.add(key)
    
    print(f"\n✓ Extracted {len(all_reqs)} → {len(unique)} unique")
    
    # Add IDs
    for i, req in enumerate(unique, 1):
        req['requirement_id'] = f"{project.upper()}-{i:03d}"
    
    # Save
    output_file = output_dir / f"{project}_requirements.json"
    with open(output_file, 'w') as f:
        json.dump({'project': project, 'requirements': unique}, f, indent=2)
    
    print(f"✓ Saved to: {output_file}")
    print("\n✅ Done!")

if __name__ == "__main__":
    main()
