import logging
import re
from pathlib import Path
from typing import List, Dict, Any, Optional

logger = logging.getLogger("prism.testgen.context")

# Context budget constants
TOTAL_BUDGET = 12000

def _fuzzy_match_filename(source_file: str, documents: Dict[str, Any]) -> Optional[str]:
    """Helper to find the correct document key even if paths or extensions differ slightly."""
    if source_file in documents:
        return source_file
    
    source_stem = Path(source_file).stem.lower()
    for key in documents:
        key_stem = Path(key).stem.lower()
        if key_stem == source_stem or source_stem in key_stem or key_stem in source_stem:
            return key
    return None

def _get_precise_source_text(req: Dict[str, Any], documents: Dict[str, Any], max_chars: int = 6000) -> str:
    """Extract precise text from the source document based on line/page hints."""
    source_file = req.get('source_file', '')
    line_start = req.get('line_start', 0)
    line_end = req.get('line_end', 0)
    page_start = req.get('page_start', 0)
    page_end = req.get('page_end', 0)

    matched_key = _fuzzy_match_filename(source_file, documents)
    if not matched_key:
        return ""

    # Check if documents[matched_key] has full_text or pages
    doc = documents[matched_key]
    
    # In approach2_project, we might have raw text or structured objects
    # Assuming documents is Dict[filename, str] or Dict[filename, Object with full_text]
    full_text = getattr(doc, 'full_text', str(doc))
    
    # If we have line numbers, try to extract that specific range
    if line_start > 0 and line_end > 0:
        all_lines = full_text.split('\n')
        # Add some padding
        start = max(0, line_start - 20)
        end = min(len(all_lines), line_end + 20)
        return "\n".join(all_lines[start:end])[:max_chars]

    # If we only have page numbers
    if page_start > 0:
        # If the document object has a list of pages
        if hasattr(doc, 'pages'):
            text = ""
            for page in doc.pages:
                if page_start <= page.page_num <= (page_end or page_start):
                    text += f"\n[Page {page.page_num}]\n{page.text}\n"
            return text[:max_chars]
        
    # Fallback: simple keyword search in full_text if coordinates aren't precise enough
    # or if we only have the full_text string
    return full_text[:max_chars]

def _match_supporting_to_feature(feature_name: str, feature_desc: str, supp_docs: Dict[str, str]) -> List[tuple]:
    """Score paragraphs in supporting documents against a feature to find the most relevant snippets."""
    feature_text = f"{feature_name} {feature_desc}".lower()
    stop_words = {
        'the','a','an','is','are','for','and','or','to','in','of','on','at','by','with','from','as',
        'be','this','that','it','not','but','if','can','will','has','have','do','does','feature',
        'verify','display','show','page','user','customer','based','should','must','able','when',
        'each','provide','key','information','new','self','serve'
    }
    feature_kws = {w for w in feature_text.split() if len(w) > 2} - stop_words
    domain_kws = {
        'dashboard','usage','warranty','widget','export','nag','metric','tiles','permission',
        'shopping','orders','bar','chart','donut','threshold','subscriber','inventory','drill',
        'breakdown','shared','individual','plan','billing','overage','unbilled','billed',
        'voice','data','sms','messaging','distance'
    }
    
    scored_snippets = []
    
    # Check paragraphs across all supporting docs
    for fname, text in supp_docs.items():
        # Split text into manageable paragraphs (e.g., by double newline)
        paragraphs = [p.strip() for p in re.split(r'\n\s*\n', text) if len(p.strip()) > 50]
        
        for para in paragraphs:
            para_lower = para.lower()
            overlap = sum(1 for kw in feature_kws if kw in para_lower)
            domain_overlap = sum(2 for kw in (feature_kws & domain_kws) if kw in para_lower)
            score = overlap + domain_overlap
            
            # Additional score if the exact feature name is in the paragraph
            if feature_name.lower() in para_lower:
                score += 5
                
            if score > 0:
                scored_snippets.append((fname, para, score))
    
    # Sort snippets by score
    scored_snippets.sort(key=lambda x: x[2], reverse=True)
    
    # Deduplicate similar overlapping snippets loosely based on text content
    unique_snippets = []
    seen_texts = set()
    for fname, para, score in scored_snippets:
        snippet_sig = para[:100].lower() # simple signature
        if snippet_sig not in seen_texts:
            unique_snippets.append((fname, para, score))
            seen_texts.add(snippet_sig)
            
    return unique_snippets

def get_feature_context(req: Dict[str, Any], documents: Dict[str, Any], max_chars: int = TOTAL_BUDGET) -> str:
    """
    Build a rich, multi-source context string for a requirement.
    Includes precise source text, supporting contexts, and matched JIRA content.
    """
    source_file = req.get('source_file', '')
    context_parts = []
    chars_used = 0

    # 1. Precise Source Text
    source_text = _get_precise_source_text(req, documents, max_chars=6000)
    if source_text:
        header = f"[SOURCE: {Path(source_file).stem} lines {req.get('line_start','?')}-{req.get('line_end','?')}]\n"
        context_parts.append(header + source_text)
        chars_used += len(header) + len(source_text)

    # 2. Supporting Contexts (already extracted in BR phase)
    supp_contexts = req.get('supporting_context', [])
    if supp_contexts:
        for sc in supp_contexts:
            doc_name = sc.get('doc', '')
            text = sc.get('text', '')
            if not text:
                continue
            
            header = f"\n[SUPPORTING: {Path(doc_name).stem}]\n"
            remaining = max_chars - chars_used
            if remaining <= 300:
                break
            
            piece = header + text[:max(0, remaining - len(header))]
            context_parts.append(piece)
            chars_used += len(piece)

    # 3. Dynamic JIRA/Solution/RTM matching if no supporting context was pre-populated
    else:
        # Include all documents that are NOT the primary source file
        supp_docs = {}
        matched_key = _fuzzy_match_filename(source_file, documents)
        for fname, doc in documents.items():
            if fname != matched_key:
                supp_docs[fname] = getattr(doc, 'full_text', str(doc))
        
        if supp_docs:
            supp_budget = min(4000, max_chars - chars_used)
            matches = _match_supporting_to_feature(req.get('feature_name', ''), req.get('description', ''), supp_docs)
            for fname, text, score in matches[:3]: # Let's pull from top 3
                if supp_budget <= 300:
                    break
                header = f"\n[SUPPORTING DOC: {Path(fname).stem} (relevance score={score})]\n"
                piece = header + text[:max(0, supp_budget - len(header))]
                context_parts.append(piece)
                chars_used += len(piece)
                supp_budget -= len(piece)

    total = "\n".join(context_parts)[:max_chars]
    logger.info("Built multi-source context: %d chars", len(total))
    return total
