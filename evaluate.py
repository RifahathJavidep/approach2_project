"""
Evaluate Extracted Requirements Against Ground Truth
Run with F5 in VS Code

Uses hybrid matching: fast Jaccard similarity + LLM semantic matching for borderline cases.
"""

import json
import os
import openpyxl
from pathlib import Path
from typing import List, Dict
from dotenv import load_dotenv

load_dotenv()

def load_ground_truth(excel_path: str, sheet_name: str = "Requirements Summary") -> List[Dict]:
    """Load ground truth from Excel."""
    wb = openpyxl.load_workbook(excel_path)
    ws = wb[sheet_name]
    
    requirements = []
    for row in range(3, ws.max_row + 1):
        req_id = ws.cell(row, 1).value
        req_name = ws.cell(row, 2).value
        req_desc = ws.cell(row, 3).value
        
        if req_id and req_name:
            requirements.append({
                'id': str(req_id),
                'name': str(req_name),
                'description': str(req_desc) if req_desc else ""
            })
    
    return requirements

def calculate_similarity(text1: str, text2: str) -> float:
    """Word overlap similarity (Jaccard)."""
    words1 = set(text1.lower().split())
    words2 = set(text2.lower().split())
    
    if not words1 or not words2:
        return 0.0
    
    intersection = words1.intersection(words2)
    union = words1.union(words2)
    
    return len(intersection) / len(union)

def llm_match(ext_title: str, ext_desc: str, gt_name: str, gt_desc: str) -> bool:
    """Use LLM to judge if two requirements describe the same or overlapping feature."""
    try:
        import dspy
        groq_key = os.getenv("GROQ_API_KEY")
        if not groq_key:
            return False
        
        lm = dspy.LM('groq/llama-3.3-70b-versatile', api_key=groq_key)
        
        prompt = f"""Do these two requirements describe the SAME user-facing feature, or is one a part/subset of the other?

Requirement A: {ext_title} - {ext_desc}
Requirement B: {gt_name} - {gt_desc}

Answer 'yes' if they describe the same feature, one contains the other, or they significantly overlap in functionality.
Answer 'no' only if they are clearly about different features.

Answer (yes/no):"""
        
        response = lm(prompt)
        answer = response[0].strip().lower() if response else ""
        return answer.startswith('yes')
    except Exception:
        return False

# Cache LLM results to avoid redundant API calls
_llm_cache = {}

def cached_llm_match(ext_title, ext_desc, gt_name, gt_desc) -> bool:
    """LLM match with caching."""
    key = (ext_title, gt_name)
    if key not in _llm_cache:
        _llm_cache[key] = llm_match(ext_title, ext_desc, gt_name, gt_desc)
    return _llm_cache[key]

def evaluate(extracted: List[Dict], ground_truth: List[Dict], threshold: float = 0.30, llm_threshold: float = 0.10) -> Dict:
    """Evaluate extracted vs ground truth using hybrid matching.
    
    Matching strategy:
    - Jaccard >= threshold (0.30): auto-match (high word overlap)
    - llm_threshold <= Jaccard < threshold: borderline → ask LLM
    - Jaccard < llm_threshold (0.10): auto-reject (too different)
    """
    
    matched = []
    missed = []
    over_created = []
    gt_matched = set()
    
    print("  Using hybrid matching (Jaccard + LLM for borderline cases)...")
    
    # Find matches using cross-comparison of titles and descriptions
    for ext in extracted:
        best_match = None
        best_score = 0.0
        
        for gt in ground_truth:
            if gt['id'] in gt_matched:
                continue  # Already matched, skip
            
            # Cross-compare all text fields for best possible match
            title_title = calculate_similarity(ext['title'], gt['name'])
            title_desc = calculate_similarity(ext['title'], gt['description'])
            desc_title = calculate_similarity(ext['description'], gt['name'])
            desc_sim = calculate_similarity(ext['description'], gt['description'])
            ext_full = f"{ext['title']} {ext['description']}"
            gt_full = f"{gt['name']} {gt['description']}"
            full_sim = calculate_similarity(ext_full, gt_full)
            score = max(title_title, title_desc, desc_title, desc_sim, full_sim)
            
            if score > best_score:
                best_score = score
                best_match = gt
        
        is_match = False
        match_method = ""
        final_match = None
        
        if best_score >= threshold:
            # High word overlap — auto-match
            is_match = True
            match_method = "jaccard"
            final_match = best_match
        elif best_score >= llm_threshold:
            # Borderline — try LLM against ALL unmatched GT items
            for gt in ground_truth:
                if gt['id'] in gt_matched:
                    continue
                llm_result = cached_llm_match(
                    ext['title'], ext.get('description', ''),
                    gt['name'], gt.get('description', '')
                )
                if llm_result:
                    is_match = True
                    match_method = "llm"
                    final_match = gt
                    break
        
        if is_match and final_match:
            matched.append({
                'extracted_id': ext['requirement_id'],
                'extracted_title': ext['title'],
                'gt_id': final_match['id'],
                'gt_name': final_match['name'],
                'similarity': best_score,
                'match_method': match_method
            })
            gt_matched.add(final_match['id'])
        else:
            over_created.append({
                'extracted_id': ext['requirement_id'],
                'title': ext['title'],
                'type': ext.get('type', 'Unknown'),
                'description': ext.get('description', '')
            })
    
    # Find missed
    for gt in ground_truth:
        if gt['id'] not in gt_matched:
            missed.append({
                'gt_id': gt['id'],
                'gt_name': gt['name'],
                'description': gt['description']
            })
    
    # Metrics
    tp = len(matched)
    fp = len(over_created)
    fn = len(missed)
    
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0
    
    return {
        'metrics': {
            'precision': precision,
            'recall': recall,
            'f1_score': f1
        },
        'counts': {
            'gt': len(ground_truth),
            'extracted': len(extracted),
            'true_positives': tp,
            'false_negatives': fn,
            'false_positives': fp
        },
        'matched': matched,
        'missed': missed,
        'over_created': over_created
    }

def main():
    print("="*80)
    print("EVALUATION")
    print("="*80)
    
    # Config
    config_file = Path("config/config.json")
    with open(config_file) as f:
        config = json.load(f)
    
    project = config['project_name']
    gt_file = Path(config['ground_truth_excel'])
    req_file = Path(config['output_dir']) / f"{project}_requirements.json"
    output_dir = Path(config['output_dir'])
    
    if not gt_file.exists():
        print(f"ERROR: Ground truth not found: {gt_file}")
        return
    
    if not req_file.exists():
        print(f"ERROR: Requirements not found: {req_file}")
        return
    
    # Load
    print(f"\n📊 Loading ground truth...")
    ground_truth = load_ground_truth(str(gt_file))
    print(f"✓ Loaded {len(ground_truth)} requirements")
    
    print(f"\n📄 Loading extracted requirements...")
    with open(req_file) as f:
        data = json.load(f)
        extracted = data['requirements']
    print(f"✓ Loaded {len(extracted)} requirements")
    
    # Evaluate
    print(f"\n📈 Evaluating...")
    evaluation = evaluate(extracted, ground_truth)
    
    # Print results
    print(f"\n{'='*80}")
    print("RESULTS:")
    print(f"{'='*80}")
    print(f"Precision:  {evaluation['metrics']['precision']:.2%}")
    print(f"Recall:     {evaluation['metrics']['recall']:.2%}")
    print(f"F1 Score:   {evaluation['metrics']['f1_score']:.2%}")
    print(f"")
    print(f"Ground Truth:      {evaluation['counts']['gt']}")
    print(f"Extracted:         {evaluation['counts']['extracted']}")
    print(f"True Positives:    {evaluation['counts']['true_positives']}")
    print(f"False Negatives:   {evaluation['counts']['false_negatives']} (missed)")
    print(f"False Positives:   {evaluation['counts']['false_positives']} (over-extracted)")
    print(f"{'='*80}")
    
    # Save
    eval_file = output_dir / f"{project}_evaluation.json"
    with open(eval_file, 'w') as f:
        json.dump(evaluation, f, indent=2)
    
    print(f"\n✓ Saved to: {eval_file}")
    print("✅ Done!")

if __name__ == "__main__":
    main()
