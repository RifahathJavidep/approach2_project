import json
import openpyxl
import os
import dspy
from pathlib import Path
from typing import List, Dict
from dotenv import load_dotenv

# Load environment
load_dotenv()

class RequirementMatcher(dspy.Signature):
    """Determine if a generated requirement matches a ground truth requirement.
    
    Match if they describe the SAME BUSINESS FUNCTION, even if wording differs.
    Ignore technical implementation details (e.g., if one mentions 'API' and the other doesn't).
    """
    extracted_title = dspy.InputField()
    extracted_desc = dspy.InputField()
    gt_title = dspy.InputField()
    gt_desc = dspy.InputField()
    
    matches = dspy.OutputField(desc="yes/no")
    reason = dspy.OutputField(desc="brief explanation")

def _get_lm():
    groq_key = os.getenv("GROQ_API_KEY")
    if not groq_key:
        raise ValueError("GROQ_API_KEY not found in .env")
    return dspy.LM('groq/llama-3.3-70b-versatile', api_key=groq_key)

def load_ground_truth(excel_path: str, sheet_name: str = "Requirements") -> List[Dict]:
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
    """Word overlap similarity."""
    words1 = set(text1.lower().split())
    words2 = set(text2.lower().split())
    
    if not words1 or not words2:
        return 0.0
    
    intersection = words1.intersection(words2)
    union = words1.union(words2)
    
    return len(intersection) / len(union)

def evaluate(extracted: List[Dict], ground_truth: List[Dict], threshold: float = 0.3) -> Dict:
    """Evaluate extracted vs ground truth using exclusive matching to ensure accurate metrics."""
    
    unique_matched_gt = set()      # Unique GT IDs that were found
    correct_extractions = []       # List of extractions that successfully found a NEW GT
    redundant_extractions = []     # List of extractions that matched an already-found GT
    over_created_extractions = []  # List of extractions with no match at all
    
    lm = _get_lm()
    matcher = dspy.Predict(RequirementMatcher)
    
    print(f"  Analysing {len(extracted)} extracted requirements against {len(ground_truth)} ground truth items...")

    # For each extracted requirement, find the best matching ground truth item
    with dspy.context(lm=lm):
        for i, ext in enumerate(extracted):
            best_match = None
            semantic_match_found = False
            
            print(f"    [{i+1}/{len(extracted)}] Matching: {ext['title'][:40]}...", end='\r')
            
            # Step 1: Find if this extraction matches ANY Ground Truth item
            for gt in ground_truth:
                # Quick word similarity check
                title_sim = calculate_similarity(ext['title'], gt['name'])
                desc_sim = calculate_similarity(ext['description'], gt['description'])
                word_score = max(title_sim, desc_sim)
                
                # Semantic check for potential matches
                if word_score > 0.05:
                    result = matcher(
                        extracted_title=ext['title'],
                        extracted_desc=ext['description'],
                        gt_title=gt['name'],
                        gt_desc=gt['description']
                    )
                    if result.matches.lower().strip() == 'yes':
                        best_match = gt
                        semantic_match_found = True
                        break # Found a match

            # Step 2: Categorize the extraction result
            if best_match:
                match_data = {
                    'extracted_id': ext['requirement_id'],
                    'extracted_title': ext['title'],
                    'gt_id': best_match['id'],
                    'gt_name': best_match['name'],
                    'semantic_match': semantic_match_found
                }
                
                if best_match['id'] not in unique_matched_gt:
                    # TRUE POSITIVE: This is a new ground truth item we found
                    correct_extractions.append(match_data)
                    unique_matched_gt.add(best_match['id'])
                else:
                    # REDUNDANT: This matches a GT that was already found (False Positive for precision)
                    redundant_extractions.append(match_data)
            else:
                # JUNK: Does not match any ground truth (False Positive for precision)
                over_created_extractions.append({
                    'extracted_id': ext['requirement_id'],
                    'title': ext['title'],
                    'type': ext.get('type', 'Unknown')
                })
    
    print("\n  Matching complete.")
    
    # Step 3: Identify missed requirements (False Negatives)
    missed = []
    for gt in ground_truth:
        if gt['id'] not in unique_matched_gt:
            missed.append({
                'gt_id': gt['id'],
                'gt_name': gt['name'],
                'description': gt['description']
            })
    
    # Step 4: Calculate Standard Metrics
    # TP = Unique GTs found
    # FP = Junk extractions + Redundant extractions
    # FN = GTs missed
    tp = len(unique_matched_gt)
    fp = len(over_created_extractions) + len(redundant_extractions)
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
            'false_positives': fp,
            'redundant': len(redundant_extractions)
        },
        'matched': correct_extractions,
        'missed': missed,
        'over_created': over_created_extractions,
        'redundant_items': redundant_extractions
    }

def main():
    print("=" * 80)
    print("EVALUATION")
    print("=" * 80)

    # Load config
    config_file = Path("config/config.json")
    with open(config_file) as f:
        config = json.load(f)

    # Read current project from multi-project config
    current_project = config.get('current_project')
    if not current_project:
        print("ERROR: 'current_project' not set in config.json")
        return

    projects = config.get('projects', {})
    if current_project not in projects:
        print(f"ERROR: Project '{current_project}' not found in config.projects")
        return

    project_config = projects[current_project]
    output_dir = Path(config.get('output_dir', 'output'))

    # Check ground truth
    gt_path = project_config.get('ground_truth')
    if not gt_path:
        print(f"No ground truth file configured for project '{current_project}'.")
        print("Add a 'ground_truth' path in config.json to enable evaluation.")
        return

    gt_file = Path(gt_path)
    req_file = output_dir / f"{current_project}_requirements.json"

    if not gt_file.exists():
        print(f"ERROR: Ground truth not found: {gt_file}")
        return

    if not req_file.exists():
        print(f"ERROR: Requirements not found: {req_file}")
        print("Run extract_requirements.py first.")
        return

    # Load
    print(f"\nProject: {current_project}")
    print(f"\nLoading ground truth: {gt_file}")
    ground_truth = load_ground_truth(str(gt_file))
    print(f"Loaded {len(ground_truth)} requirements")

    print(f"\nLoading extracted requirements: {req_file}")
    with open(req_file) as f:
        data = json.load(f)
        extracted = data['requirements']
    print(f"Loaded {len(extracted)} requirements")

    # Evaluate
    print(f"\nEvaluating...")
    evaluation = evaluate(extracted, ground_truth)

    # Print results
    print(f"\n{'=' * 80}")
    print("RESULTS:")
    print(f"{'=' * 80}")
    print(f"Precision:  {evaluation['metrics']['precision']:.2%}")
    print(f"Recall:     {evaluation['metrics']['recall']:.2%}")
    print(f"F1 Score:   {evaluation['metrics']['f1_score']:.2%}")
    print(f"")
    print(f"Ground Truth:      {evaluation['counts']['gt']}")
    print(f"Extracted:         {evaluation['counts']['extracted']}")
    print(f"True Positives:    {evaluation['counts']['true_positives']}")
    print(f"False Negatives:   {evaluation['counts']['false_negatives']} (missed)")
    print(f"False Positives:   {evaluation['counts']['false_positives']} (over-extracted)")
    print(f"{'=' * 80}")

    # Save
    eval_file = output_dir / f"{current_project}_evaluation.json"
    with open(eval_file, 'w') as f:
        json.dump(evaluation, f, indent=2)

    print(f"\nSaved to: {eval_file}")
    print("Done!")

if __name__ == "__main__":
    main()
