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
    """Evaluate extracted vs ground truth using both similarity and semantic matching."""
    
    matched = []
    missed = []
    over_created = []
    gt_matched = set()
    
    lm = _get_lm()
    matcher = dspy.Predict(RequirementMatcher)
    
    print(f"  Analysing {len(extracted)} extracted requirements against {len(ground_truth)} ground truth items...")

    # Find matches
    with dspy.context(lm=lm):
        for i, ext in enumerate(extracted):
            best_match = None
            best_score = 0.0
            semantic_match_found = False
            
            print(f"    [{i+1}/{len(extracted)}] Matching: {ext['title'][:40]}...", end='\r')
            
            for gt in ground_truth:
                # 1. Check quick word similarity
                title_title = calculate_similarity(ext['title'], gt['name'])
                desc_sim = calculate_similarity(ext['description'], gt['description'])
                word_score = max(title_title, desc_sim)
                
                # 2. Use the semantic matcher for anything that isn't a total mismatch.
                # This ensures we capture requirements that are phrased very differently.
                if word_score > 0.05:
                    result = matcher(
                        extracted_title=ext['title'],
                        extracted_desc=ext['description'],
                        gt_title=gt['name'],
                        gt_desc=gt['description']
                    )
                    if result.matches.lower().strip() == 'yes':
                        best_score = max(word_score, 0.85) # High score for semantic match
                        best_match = gt
                        semantic_match_found = True
                        break

            if best_match:
                matched.append({
                    'extracted_id': ext['requirement_id'],
                    'extracted_title': ext['title'],
                    'gt_id': best_match['id'],
                    'gt_name': best_match['name'],
                    'similarity': best_score,
                    'semantic_match': semantic_match_found
                })
                gt_matched.add(best_match['id'])
            else:
                over_created.append({
                    'extracted_id': ext['requirement_id'],
                    'title': ext['title'],
                    'type': ext.get('type', 'Unknown')
                })
    
    print("\n  Matching complete.")
    
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
