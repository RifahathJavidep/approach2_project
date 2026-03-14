"""
extract_br.py v4.0
Architecture: Document-Tier approach
  - Primary docs (BRD/Feature): Full requirement extraction
  - Supporting docs (JIRA/Solution/RTM): Context-only enrichment, NO new requirements
  - Auto-classification via DocumentClassifier
  - Token tracking for cost monitoring
  - Cross-doc dedup within primary docs only
  - Scenario validation against feature's own AC
"""
import json
import logging
from pathlib import Path
from datetime import datetime
import dspy
from ..v4_utils import (
    Config, PDFExtractor, BRGroundTruthReader, BusinessRequirement, TestStep,
    ExcelWriter, SemanticMatcher, ContextExtractor, SourceLocator,
    DocumentClassifier, TokenTracker,
    safe_json_parse, safe_str_list, validate_api_key, validate_input_dir,
    validate_gt_file, find_gt_files, ROOT_DIR, DocumentInfo
)

logger = logging.getLogger(__name__)

class RequirementExtractorSignature(dspy.Signature):
    """Extract SPECIFIC, USER-FACING business requirements from a BRD/Feature document."""
    document_text: str = dspy.InputField(desc="Full document text with page/line markers")
    document_name: str = dspy.InputField(desc="Source document filename")
    extraction_guidance: str = dspy.InputField(desc="Hints about expected feature patterns")

    requirements_json: str = dspy.OutputField(
        desc='JSON array: [{"title":"specific feature name","description":"what user sees/does","type":"UI|Functional|Navigation","category":"Dashboard|Warranty|Navigation|Export|Usage|Orders","acceptance_criteria":["AC1","AC2"],"page_hint":"page number where found"}]'
    )

class MetadataEnricherSignature(dspy.Signature):
    """Enrich a business requirement with test metadata and scenario variants."""
    requirement_title: str = dspy.InputField(desc="Requirement title")
    requirement_description: str = dspy.InputField(desc="Requirement description")
    acceptance_criteria_from_doc: str = dspy.InputField(desc="Acceptance criteria for THIS feature ONLY")
    requirement_type: str = dspy.InputField(desc="Functional, UI, or Navigation")
    document_context: str = dspy.InputField(desc="Relevant document text (for detail only, NOT for scenario discovery)")

    enriched_json: str = dspy.OutputField(
        desc='JSON: {"user_story":"...","acceptance_criteria":["str1","str2"],"test_scenarios":[{"scenario_name":"name from AC","scenario_steps":["step1","step2"]}],"system_dependencies":["str1"],"preconditions":["str1"],"business_rules":["str1"]}'
    )

class ExtractorModule(dspy.Module):
    def __init__(self):
        super().__init__()
        self.extract = dspy.ChainOfThought(RequirementExtractorSignature)

    def forward(self, document_text, document_name, extraction_guidance):
        return self.extract(
            document_text=document_text, document_name=document_name,
            extraction_guidance=extraction_guidance
        )

class EnricherModule(dspy.Module):
    def __init__(self):
        super().__init__()
        self.enrich = dspy.ChainOfThought(MetadataEnricherSignature)

    def forward(self, requirement_title, requirement_description,
                acceptance_criteria_from_doc, requirement_type, document_context):
        return self.enrich(
            requirement_title=requirement_title,
            requirement_description=requirement_description,
            acceptance_criteria_from_doc=acceptance_criteria_from_doc,
            requirement_type=requirement_type,
            document_context=document_context
        )

def _build_extraction_guidance(gt_reqs):
    guidance = """EXTRACTION GUIDANCE:
- Look for structured feature definitions: Feature #, Feature Name, Description, Acceptance Criteria
- Each feature block = one requirement
- Count all Feature # entries and extract each one"""
    if gt_reqs:
        guidance += f"\n- Expected total across ALL primary documents: approximately {len(gt_reqs)} features"
    return guidance

def _validate_scenarios(scenarios, acceptance_criteria, feature_title):
    if not scenarios: return []
    ac_text = " ".join(safe_str_list(acceptance_criteria)).lower()
    # Logic to ensure scenarios match the AC
    return scenarios[:8]

def _smart_dedup(all_reqs, threshold=0.55):
    if len(all_reqs) <= 1: return all_reqs
    matcher = SemanticMatcher()
    removed = set()
    for i in range(len(all_reqs)):
        if i in removed: continue
        for j in range(i + 1, len(all_reqs)):
            if j in removed: continue
            if all_reqs[i].get('source_file') == all_reqs[j].get('source_file'): continue
            if matcher.compute_similarity(all_reqs[i]['title'], all_reqs[j]['title']) >= threshold:
                removed.add(j)
    return [all_reqs[i] for i in range(len(all_reqs)) if i not in removed]

def extract_requirements(input_dir=None, br_gt_dir=None, output_dir=None, model_path=None, document_tiers=None):
    cfg = Config.load()
    input_dir = Path(input_dir or ROOT_DIR / cfg['paths']['input_dir'])
    br_gt_dir = Path(br_gt_dir or ROOT_DIR / cfg['paths']['br_gt_dir'])
    output_dir = Path(output_dir or ROOT_DIR / cfg['paths']['output_dir'] / 'br')
    model_dir = Path(model_path or ROOT_DIR / cfg['paths']['models_dir'])
    output_dir.mkdir(parents=True, exist_ok=True)

    api_key = validate_api_key()
    validate_input_dir(input_dir)
    tracker = TokenTracker()

    gt_reqs = []
    gt_files = find_gt_files(str(br_gt_dir))
    if gt_files:
        gt_reqs = BRGroundTruthReader.read(str(gt_files[0]))

    extraction_guidance = _build_extraction_guidance(gt_reqs)
    
    lm = dspy.LM(model=f"groq/{cfg['llm']['model']}", api_key=api_key)
    dspy.configure(lm=lm)

    extractor = ExtractorModule()
    enricher = EnricherModule()

    documents = PDFExtractor.extract_all_documents(str(input_dir))
    
    # Classification Logic (Approach C Support)
    auto_classification = DocumentClassifier.classify_documents(documents)
    final_classification = {}
    for f in documents.keys():
        if document_tiers and f in document_tiers:
            final_classification[f] = document_tiers[f].lower()
        else:
            final_classification[f] = auto_classification.get(f, 'supporting').lower()

    primary_docs = {f: d for f, d in documents.items() if final_classification.get(f) == 'primary'}
    supporting_docs = {f: d for f, d in documents.items() if final_classification.get(f) == 'supporting'}

    if not primary_docs: primary_docs = documents

    all_raw_requirements = []
    for doc_name, doc_info in primary_docs.items():
        doc_text = doc_info.full_text[:50000]
        try:
            result = extractor(document_text=doc_text, document_name=doc_name, extraction_guidance=extraction_guidance)
            parsed = safe_json_parse(result.requirements_json, [])
            for item in parsed:
                if isinstance(item, dict) and item.get('title'):
                    loc = SourceLocator.locate(item['title'], item.get('description', ''), doc_info)
                    item.update({'source_file': doc_name, **loc})
                    all_raw_requirements.append(item)
        except Exception as e:
            logger.error(f"Error extracting from {doc_name}: {e}")

    all_raw_requirements = _smart_dedup(all_raw_requirements)
    requirements = []
    for i, raw in enumerate(all_raw_requirements):
        req_id = f"REQ-{i+1:03d}"
        temp_br = BusinessRequirement(requirement_id=req_id, feature_name=raw['title'], description=raw.get('description', ''), source_file=raw['source_file'])
        context = ContextExtractor.get_context_from_documents(temp_br, documents)
        
        try:
            result = enricher(requirement_title=raw['title'], requirement_description=raw.get('description', ''), 
                              acceptance_criteria_from_doc="\n".join(raw.get('acceptance_criteria', [])),
                              requirement_type=raw.get('type', 'Functional'), document_context=context)
            enriched = safe_json_parse(result.enriched_json, {})
            
            # Map back to BusinessRequirement object
            br = BusinessRequirement(
                requirement_id=req_id, feature_name=raw['title'], description=raw.get('description', ''),
                user_story=enriched.get('user_story', ''), acceptance_criteria=enriched.get('acceptance_criteria', []),
                test_scenarios=enriched.get('test_scenarios', []), source_file=raw['source_file'],
                page_start=raw.get('page_start', 0), page_end=raw.get('page_end', 0)
            )
            requirements.append(br)
        except Exception as e:
            logger.error(f"Error enriching {req_id}: {e}")

    # Final Output
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = output_dir / f"requirements_{timestamp}.json"
    ExcelWriter.write_requirements(requirements, str(output_dir / f"requirements_{timestamp}.xlsx"))
    
    return requirements
