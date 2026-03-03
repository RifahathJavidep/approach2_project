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
    """Extract SPECIFIC, USER-FACING business requirements from a BRD/Feature document.

    A requirement is a SPECIFIC UI feature or user interaction.

    GOOD examples (specific UI features):
    - "Export Feature" (export to CSV/PDF/Excel)
    - "NAG Filter Dropdown" (dropdown filter on dashboard)
    - "Data Usage Bar Chart" (14-month billed/unbilled chart)
    - "Warranty Expiry Display" (warranty date on subscriber page)
    - "Shareplans Detail Table" (detailed shareplan information table)

    BAD examples (DO NOT extract):
    - "Dashboard" (too broad)
    - "Real-Time Data Integration" (implementation detail)
    - "API Integration" (technical)

    Rules:
    1. Each requirement = ONE specific UI widget, button, table, chart, screen element, or user action
    2. If a dashboard has 5 widgets, extract 5 separate requirements
    3. Navigation elements are separate requirements
    4. Do NOT extract system integrations, APIs, data flows, or architecture
    5. Look for Feature #, Feature Name, Description, Acceptance Criteria patterns
    6. Extract ALL features found - do not skip any
    """
    document_text: str = dspy.InputField(desc="Full document text with page/line markers")
    document_name: str = dspy.InputField(desc="Source document filename")
    extraction_guidance: str = dspy.InputField(desc="Hints about expected feature patterns")

    requirements_json: str = dspy.OutputField(
        desc='JSON array: [{"title":"specific feature name","description":"what user sees/does","type":"UI|Functional|Navigation","category":"Dashboard|Warranty|Navigation|Export|Usage|Orders","acceptance_criteria":["AC1","AC2"],"page_hint":"page number where found"}]'
    )


class MetadataEnricherSignature(dspy.Signature):
    """Enrich a business requirement with test metadata and scenario variants.

    CRITICAL RULES FOR SCENARIOS:
    1. ONLY generate scenarios DIRECTLY mentioned in acceptance_criteria_from_doc.
    2. Do NOT infer scenarios from document_context that belong to OTHER features.
    3. If AC mentions "Data, Voice, Long Distance, SMS" -> 4 tab scenarios.
    4. If AC mentions "Billing Accounts, Active, Suspended, Cancelled" -> 4 tile scenarios.
    5. If AC mentions "CSV, PDF, Excel, PNG, JPEG" -> 5 export scenarios.
    6. If AC does NOT mention any variants -> just 1-2 general scenarios.
    7. Back buttons: AT MOST 2 scenarios. Static text: AT MOST 1-2 scenarios.

    Each scenario_name must correspond to a phrase found in acceptance_criteria_from_doc.
    All arrays must contain STRINGS only, not objects.
    """
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
- Extract the feature name exactly as written in the document
- Include acceptance criteria verbatim from the document
- Dashboard features: widgets, tiles, charts, tables, buttons, links, filters
- Warranty features: display fields, page locations, date formats
- Navigation: back buttons, drilldowns, redirects
- Export: file formats, download buttons
- Count all Feature # entries and extract each one"""
    if gt_reqs:
        guidance += f"\n- Expected total across ALL primary documents: approximately {len(gt_reqs)} features"
    return guidance


def _validate_scenarios(scenarios, acceptance_criteria, feature_title):
    if not scenarios:
        return []
    if not acceptance_criteria:
        return scenarios[:2]

    ac_text = " ".join(safe_str_list(acceptance_criteria)).lower()

    has_usage_tabs = any(t in ac_text for t in ['data, voice', 'voice, long distance',
                                                  'data tab', 'voice tab', 'toggle between'])
    has_tiles = any(t in ac_text for t in ['billing account', 'active subscriber',
                                             'suspended subscriber', 'cancelled subscriber',
                                             'number of active', 'number of suspended'])
    has_export = any(t in ac_text for t in ['csv', 'pdf', 'excel', 'png', 'jpeg', 'export'])
    has_thresholds = any(t in ac_text for t in ['75%', '85%', '100%', 'threshold', 'donut'])

    validated = []
    for sc in scenarios:
        sc_name = sc if isinstance(sc, str) else sc.get('scenario_name', '')
        sc_lower = sc_name.lower()

        if any(tab in sc_lower for tab in ['data tab', 'voice tab', 'long distance tab',
                                             'sms tab', 'text messaging tab',
                                             'data usage', 'voice usage', 'long distance usage',
                                             'text messaging usage']):
            if has_usage_tabs:
                validated.append(sc)
            continue

        if any(tile in sc_lower for tile in ['billing account', 'active subscriber',
                                               'suspended subscriber', 'cancelled subscriber']):
            if has_tiles:
                validated.append(sc)
            continue

        if any(fmt in sc_lower for fmt in ['export', 'csv', 'pdf', 'excel', 'png', 'jpeg']):
            if has_export:
                validated.append(sc)
            continue

        if any(t in sc_lower for t in ['threshold', '75%', '85%', '100%']):
            if has_thresholds:
                validated.append(sc)
            continue

        validated.append(sc)

    return validated[:8]


def _smart_dedup(all_reqs, threshold=0.55):
    """Cross-document dedup within primary docs. Same-doc features are never deduped."""
    if len(all_reqs) <= 1:
        return all_reqs
    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.metrics.pairwise import cosine_similarity as cos_sim
        texts = [r['title'] + " " + r['description'] for r in all_reqs]
        vec = TfidfVectorizer(stop_words='english', ngram_range=(1, 2), max_features=5000, sublinear_tf=True)
        tfidf = vec.fit_transform([t.lower() for t in texts])
        sim = cos_sim(tfidf)
    except:
        return all_reqs

    removed = set()
    for i in range(len(all_reqs)):
        if i in removed:
            continue
        for j in range(i + 1, len(all_reqs)):
            if j in removed:
                continue
            # Never dedup features from the same document
            if all_reqs[i].get('source_file', '') == all_reqs[j].get('source_file', ''):
                continue
            if sim[i][j] >= threshold:
                removed.add(j)
                logger.info(f"  Dedup: drop '{all_reqs[j]['title']}' [{all_reqs[j]['source_file'][:25]}] "
                            f"(dup of '{all_reqs[i]['title']}', sim={sim[i][j]:.2f})")

    result = [all_reqs[i] for i in range(len(all_reqs)) if i not in removed]
    if len(result) < len(all_reqs):
        logger.info(f"  Dedup: {len(all_reqs)} -> {len(result)} (removed {len(removed)})")
    return result


def extract_requirements(input_dir=None, br_gt_dir=None, output_dir=None, model_path=None):
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
        sheet_name = cfg.get('br_gt', {}).get('sheet_name', 'Requirements Summary')
        validate_gt_file(gt_files[0], sheet_name)
        gt_reqs = BRGroundTruthReader.read(str(gt_files[0]))
        logger.info(f"BR GT: {len(gt_reqs)} requirements (count only, names NOT fed to LLM)")

    extraction_guidance = _build_extraction_guidance(gt_reqs)
    dedup_threshold = cfg.get('extraction', {}).get('dedup_threshold', 0.55)

    lm = dspy.LM(
        model=f"groq/{cfg['llm']['model']}", api_key=api_key,
        max_tokens=cfg['llm']['max_tokens'], temperature=cfg['llm']['temperature']
    )
    dspy.configure(lm=lm)

    extractor = ExtractorModule()
    trained_model = model_dir / "br_extractor_optimized.json"
    if trained_model.exists():
        try:
            extractor.load(str(trained_model))
            logger.info(f"Loaded trained BR model")
        except Exception as e:
            logger.warning(f"Could not load trained model: {e}")

    enricher = EnricherModule()

    # Extract ALL documents
    documents = PDFExtractor.extract_all_documents(str(input_dir))
    if not documents:
        raise FileNotFoundError("No documents found in input directory!")

    # Classify documents into Primary vs Supporting
    classification = DocumentClassifier.classify_documents(documents)
    primary_docs = {f: d for f, d in documents.items() if classification.get(f) == 'primary'}
    supporting_docs = {f: d for f, d in documents.items() if classification.get(f) == 'supporting'}

    if not primary_docs:
        logger.warning("No Primary documents detected! Falling back to ALL documents as Primary.")
        primary_docs = documents
        supporting_docs = {}

    # === PASS 1: Extract ONLY from Primary documents ===
    logger.info("=" * 60)
    logger.info(f"PASS 1: Extracting from {len(primary_docs)} PRIMARY documents")
    logger.info(f"        ({len(supporting_docs)} Supporting docs used for context only)")
    logger.info("=" * 60)

    all_raw_requirements = []
    max_doc_chars = cfg.get('extraction', {}).get('max_doc_chars', 50000)

    for doc_name, doc_info in primary_docs.items():
        logger.info(f"\n--- [PRIMARY] {doc_name} ({doc_info.total_pages} pages, {doc_info.total_lines} lines) ---")

        doc_text = doc_info.full_text
        if len(doc_text) > max_doc_chars:
            logger.warning(f"  Document exceeds {max_doc_chars} chars, using first {max_doc_chars}")
            doc_text = doc_text[:max_doc_chars]

        try:
            result = extractor(
                document_text=doc_text, document_name=doc_name,
                extraction_guidance=extraction_guidance
            )
            tracker.estimate_from_text("extract_" + doc_name[:20], doc_text, result.requirements_json)

            parsed = safe_json_parse(result.requirements_json, [])
            if isinstance(parsed, list):
                doc_reqs = []
                for item in parsed:
                    if isinstance(item, dict) and item.get('title'):
                        title = item['title']
                        desc = item.get('description', '')
                        loc = SourceLocator.locate(title, desc, doc_info)
                        doc_reqs.append({
                            'title': title, 'description': desc,
                            'type': item.get('type', 'Functional'),
                            'category': item.get('category', ''),
                            'acceptance_criteria': item.get('acceptance_criteria', []),
                            'source_file': doc_name,
                            'page_start': loc['page_start'], 'page_end': loc['page_end'],
                            'line_start': loc['line_start'], 'line_end': loc['line_end'],
                        })
                logger.info(f"  -> {len(doc_reqs)} requirements from {doc_name}")
                all_raw_requirements.extend(doc_reqs)
        except Exception as e:
            logger.error(f"  -> Error extracting from {doc_name}: {e}")

    logger.info(f"\nTotal from Primary docs: {len(all_raw_requirements)}")

    # Cross-document dedup within primary docs
    all_raw_requirements = _smart_dedup(all_raw_requirements, threshold=dedup_threshold)

    # === PASS 2: Enrich using ALL documents (Primary + Supporting as context) ===
    logger.info("=" * 60)
    logger.info(f"PASS 2: Enriching {len(all_raw_requirements)} requirements (all docs as context)")
    logger.info("=" * 60)

    requirements = []
    for i, raw in enumerate(all_raw_requirements):
        req_id = f"REQ-{i+1:03d}"
        logger.info(f"  [{i+1}/{len(all_raw_requirements)}] {req_id}: {raw['title']} (from {raw['source_file']})")

        temp_br = BusinessRequirement(
            requirement_id=req_id, feature_name=raw['title'],
            description=raw['description'], requirements_text=raw['description'],
            source_file=raw['source_file']
        )
        # Use ALL documents (including supporting) for context enrichment
        context = ContextExtractor.get_context_from_documents(temp_br, documents, max_chars=6000)

        ac_from_doc = raw.get('acceptance_criteria', [])
        ac_str = "\n".join(safe_str_list(ac_from_doc)) if ac_from_doc else "See document context"

        try:
            result = enricher(
                requirement_title=raw['title'],
                requirement_description=raw['description'],
                acceptance_criteria_from_doc=ac_str,
                requirement_type=raw['type'],
                document_context=context
            )
            tracker.estimate_from_text("enrich_" + req_id, ac_str + context, result.enriched_json)
            enriched = safe_json_parse(result.enriched_json, {})
            if not isinstance(enriched, dict):
                enriched = {}
        except Exception as e:
            logger.error(f"  Error enriching {req_id}: {e}")
            enriched = {}

        raw_scenarios = enriched.get('test_scenarios', [])
        test_scenarios_raw = []
        test_steps = []

        if isinstance(raw_scenarios, list):
            step_num = 1
            for sc in raw_scenarios:
                if isinstance(sc, dict):
                    sc_name = sc.get('scenario_name', '')
                    sc_steps = sc.get('scenario_steps', [])
                    if sc_name:
                        test_scenarios_raw.append(sc_name)
                    for s in safe_str_list(sc_steps):
                        test_steps.append(TestStep(step_num=step_num, action=s,
                            expected_result="", test_data=f"Scenario: {sc_name}"))
                        step_num += 1
                elif isinstance(sc, str):
                    test_scenarios_raw.append(sc)

        validated_scenarios = _validate_scenarios(test_scenarios_raw, ac_from_doc, raw['title'])

        removed_count = len(test_scenarios_raw) - len(validated_scenarios)
        if removed_count > 0:
            logger.info(f"    Scenarios: {len(test_scenarios_raw)} -> {len(validated_scenarios)} "
                        f"(removed {removed_count} cross-feature scenarios)")

        validated_names = {s.lower() if isinstance(s, str) else s for s in validated_scenarios}
        if validated_names and test_steps:
            filtered_steps = []
            for step in test_steps:
                sc_tag = step.test_data.replace('Scenario: ', '').lower()
                if not sc_tag or sc_tag in validated_names or 'scenario' not in step.test_data.lower():
                    filtered_steps.append(step)
            for idx, step in enumerate(filtered_steps, 1):
                step.step_num = idx
            test_steps = filtered_steps

        if not test_steps:
            for s in (enriched.get('test_steps', []) or []):
                if isinstance(s, dict):
                    test_steps.append(TestStep(
                        step_num=s.get('step_num', len(test_steps)+1),
                        action=str(s.get('action', '')),
                        expected_result=str(s.get('expected_result', '')),
                        test_data=str(s.get('test_data', ''))
                    ))

        enriched_ac = safe_str_list(enriched.get('acceptance_criteria', []))
        all_ac = safe_str_list(ac_from_doc) + enriched_ac
        seen_ac, unique_ac = set(), []
        for ac in all_ac:
            ac_lower = ac.lower().strip()
            if ac_lower and ac_lower not in seen_ac:
                seen_ac.add(ac_lower)
                unique_ac.append(ac)

        sys_deps = enriched.get('system_dependencies', [])
        system_str = ", ".join(safe_str_list(sys_deps)) if isinstance(sys_deps, list) else str(sys_deps or '')

        br = BusinessRequirement(
            requirement_id=req_id, feature_name=raw['title'], description=raw['description'],
            system=system_str, requirements_text=raw['description'],
            user_story=str(enriched.get('user_story', '')),
            acceptance_criteria=unique_ac, test_steps=test_steps,
            test_scenarios=validated_scenarios,
            category=raw['category'], source_file=raw['source_file'],
            page_start=raw['page_start'], page_end=raw['page_end'],
            line_start=raw['line_start'], line_end=raw['line_end'],
            confidence=0.8
        )
        requirements.append(br)
        logger.info(f"    -> {len(validated_scenarios)} scenarios, {len(test_steps)} steps, {len(unique_ac)} ACs")

    # Output
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    token_summary = tracker.summary()
    json_path = output_dir / f"requirements_{timestamp}.json"
    output_data = {
        "project_name": "Extracted Requirements", "extraction_date": timestamp,
        "total_count": len(requirements), "gt_count": len(gt_reqs),
        "document_classification": {
            "primary": list(primary_docs.keys()),
            "supporting": list(supporting_docs.keys())
        },
        "token_usage": token_summary,
        "requirements": []
    }
    for req in requirements:
        output_data["requirements"].append({
            "requirement_id": req.requirement_id, "feature_name": req.feature_name,
            "description": req.description, "system": req.system,
            "requirements_text": req.requirements_text, "user_story": req.user_story,
            "acceptance_criteria": req.acceptance_criteria,
            "test_steps": [{"step_num": s.step_num, "action": s.action,
                            "expected_result": s.expected_result, "test_data": s.test_data}
                           for s in req.test_steps],
            "test_scenarios": req.test_scenarios, "category": req.category,
            "source_file": req.source_file, "page_start": req.page_start,
            "page_end": req.page_end, "line_start": req.line_start,
            "line_end": req.line_end, "confidence": req.confidence
        })
    with open(json_path, 'w') as f:
        json.dump(output_data, f, indent=2)

    xlsx_path = output_dir / f"requirements_{timestamp}.xlsx"
    ExcelWriter.write_requirements(requirements, str(xlsx_path))

    doc_counts = {}
    for req in requirements:
        doc_counts[req.source_file] = doc_counts.get(req.source_file, 0) + 1
    total_scenarios = sum(len(r.test_scenarios) for r in requirements)

    tracker.log_summary("[BR EXTRACTION]")
    logger.info(f"\n{'='*60}")
    logger.info(f"DONE: {len(requirements)} requirements (GT: {len(gt_reqs)})")
    logger.info(f"Total scenarios: {total_scenarios} (avg {total_scenarios/max(len(requirements),1):.1f} per req)")
    for fname, count in doc_counts.items():
        logger.info(f"  {fname}: {count} requirements")
    logger.info(f"JSON: {json_path}")
    logger.info(f"Excel: {xlsx_path}")
    logger.info(f"{'='*60}")
    return requirements


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
    extract_requirements()
