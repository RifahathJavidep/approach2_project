import json
import pandas as pd
import numpy as np
import re
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

class NpEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, np.integer):
            return int(obj)
        if isinstance(obj, np.floating):
            return float(obj)
        if isinstance(obj, np.bool_):
            return bool(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        return super(NpEncoder, self).default(obj)

def normalize_text(text):
    if not isinstance(text, str):
        return ""
    # Remove numbering like "Step 1:", "1.", etc.
    text = re.sub(r'^(Step\s*\d+:|\d+[\.\)]\s*)', '', text, flags=re.IGNORECASE)
    # lowercase and trim
    return text.lower().strip()

def split_steps(steps_text):
    if not isinstance(steps_text, str):
        return []
    # Split by newline or standard patterns
    steps = re.split(r'\n+|\s*Step\s*\d+:\s*|\s*\d+[\.\)]\s*', steps_text)
    return [s.strip() for s in steps if s.strip()]

def get_similarity(text1, text2):
    if not text1 or not text2:
        return 0.0
    try:
        vectorizer = TfidfVectorizer(stop_words='english')
        tfidf = vectorizer.fit_transform([text1, text2])
        return cosine_similarity(tfidf[0:1], tfidf[1:2])[0][0]
    except:
        return 0.0

def run_comparison(json_path, excel_path, output_json_path=None):
    print(f"--- Loading Generated Test Plan: {json_path} ---")
    with open(json_path, 'r') as f:
        generated_data = json.load(f)
    
    print(f"--- Loading Ground Truth: {excel_path} ---")
    gt_df = pd.read_excel(excel_path)
    # Ensure mandatory columns exist
    required_cols = ['Test Case Description', 'Test Steps', 'Test Case Title']
    for col in required_cols:
        if col not in gt_df.columns:
            raise ValueError(f"Ground Truth Excel is missing required column: {col}")

    all_gen_tcs = []
    for plan in generated_data.get('test_plans', []):
        for tc in plan.get('test_cases', []):
            tc['requirement_id'] = plan.get('requirement_id')
            all_gen_tcs.append(tc)

    print(f"Found {len(all_gen_tcs)} generated test cases.")
    print(f"Found {len(gt_df)} ground truth test cases.")

    # Prepare GT search space
    gt_texts = (gt_df['Test Case Title'].fillna('') + " " + gt_df['Test Case Description'].fillna('')).tolist()
    
    results = []
    json_output = {"generated_file": json_path, "ground_truth_file": excel_path, "comparisons": [], "summary": {}}

    print("\n--- Starting Semantic Comparison ---\n")
    
    match_count = 0
    total_gen_steps = 0
    total_matched_steps = 0

    print(f"{'Gen TC ID':<12} | {'Similarity':<10} | {'Steps (Match/GT)':<15} | {'GT Match Title'}")
    print("-" * 110)

    for gen_tc in all_gen_tcs:
        gen_title = gen_tc.get("title", "")
        gen_desc = gen_tc.get("description", "")
        gen_text = f"{gen_title} {gen_desc}"
        
        # Find best match in GT
        best_score = 0
        best_idx = -1
        
        for i, gt_text in enumerate(gt_texts):
            score = get_similarity(gen_text, gt_text)
            if score > best_score:
                best_score = score
                best_idx = i
        
        gen_steps = gen_tc.get("test_steps", [])
        n_gen_steps = len(gen_steps)
        
        tc_id = gen_tc.get('test_case_id', 'N/A')
        entry = {
            "test_case_id": tc_id,
            "generated_title": gen_title,
            "generated_description": gen_desc,
            "n_generated_steps": n_gen_steps,
            "matched": False,
            "similarity_score": round(float(best_score), 4),
            "gt_match_title": None,
            "n_gt_steps": None,
            "step_matches": None,
            "step_accuracy_pct": None,
            "matched_step_details": []
        }

        if best_idx != -1 and best_score > 0.25: # Lowered threshold for "closest" match
            gt_row = gt_df.iloc[best_idx]
            gt_title = str(gt_row["Test Case Title"])
            gt_steps = split_steps(gt_row["Test Steps"])
            n_gt_steps = len(gt_steps)
            
            # Step-level comparison
            step_matches = 0
            step_details = []
            for g_step in gen_steps:
                g_step_norm = normalize_text(g_step)
                best_step_score = 0
                best_gt_step = None
                for gt_step in gt_steps:
                    gt_step_norm = normalize_text(gt_step)
                    sim = float(get_similarity(g_step_norm, gt_step_norm))
                    if sim > best_step_score:
                        best_step_score = sim
                        best_gt_step = gt_step
                matched_step = bool(best_step_score > 0.45)
                if matched_step:
                    step_matches += 1
                step_details.append({
                    "generated_step": g_step,
                    "best_gt_step": best_gt_step,
                    "similarity": round(best_step_score, 4),
                    "is_match": matched_step
                })
            
            match_count += 1
            total_gen_steps += n_gen_steps
            total_matched_steps += step_matches

            step_acc = round((step_matches / n_gen_steps) * 100, 2) if n_gen_steps > 0 else 0.0
            entry.update({
                "matched": True,
                "gt_match_title": gt_title,
                "n_gt_steps": n_gt_steps,
                "step_matches": step_matches,
                "step_accuracy_pct": step_acc,
                "matched_step_details": step_details
            })
            
            print(f"{tc_id:<12} | {best_score:<10.2f} | {step_matches}/{n_gt_steps:<11} | {gt_title[:60]}")
        else:
            print(f"{tc_id:<12} | {'< 0.25':<10} | {'-/-':<15} | No significant semantic match")

        json_output["comparisons"].append(entry)

    overall_step_acc = round((total_matched_steps / total_gen_steps) * 100, 2) if total_gen_steps > 0 else 0.0
    json_output["summary"] = {
        "total_generated_test_cases": len(all_gen_tcs),
        "matched_test_cases": match_count,
        "unmatched_test_cases": len(all_gen_tcs) - match_count,
        "match_threshold": 0.25,
        "step_similarity_threshold": 0.45,
        "total_generated_steps": total_gen_steps,
        "total_matched_steps": total_matched_steps,
        "overall_step_accuracy_pct": overall_step_acc
    }

    # Determine output path
    if output_json_path is None:
        import os
        base = os.path.splitext(json_path)[0]
        output_json_path = f"{base}_comparison_results.json"

    with open(output_json_path, 'w') as f:
        json.dump(json_output, f, indent=2, cls=NpEncoder)
    print(f"\n✅ Results saved to: {output_json_path}")

    print("\n" + "="*50)
    print("DETAILED ACCURACY REPORT")
    print("="*50)
    print(f"Total Generated Test Cases: {len(all_gen_tcs)}")
    print(f"Test Cases with >25% Sim:   {match_count}")
    if total_gen_steps > 0:
        print(f"Overall Step Accuracy:      {overall_step_acc:.2f}%")
    print("="*50)

if __name__ == "__main__":
    run_comparison(
        "output/inuts/testcases/inuts_test_plan.json",
        "groundtruth/Untitled spreadsheet (6).xlsx"
    )
