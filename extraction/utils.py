"""
Utility Functions — Chunking and Text Helpers

Shared utility functions used across the extraction pipeline.

Moved from: extract_requirements.py lines 458–494
"""

import re
from typing import List


def _get_section_number(header_line: str) -> str:
    """Extract the section number (e.g., '2', '2.1', '7') from a header line."""
    # Try numbered patterns: **2.1, ### 2.1, **7., ### **5.
    match = re.search(r'(\d+(?:\.\d+)*)', header_line.split('\n')[0])
    return match.group(1) if match else ''


def _split_by_sections(text: str) -> List[str]:
    """Split text into sections based on markdown headers and numbered sections.

    Detects patterns like:
    - ### 2.1 Section Title
    - **2.1 Section Title**
    - ##### 3.1 Subsection
    - ### **5. Section**

    CONTEXT PRESERVATION: When a parent section (e.g., Section 7) has intro text
    followed by subsections (7.1, 7.2), the intro text is prepended to each
    subsection chunk so the LLM always sees the context.
    """
    # Pattern: markdown headers OR bold numbered sections at line start
    section_pattern = re.compile(
        r'^(?=#{1,5}\s|\*{2}\d+\.)',
        re.MULTILINE
    )

    positions = [m.start() for m in section_pattern.finditer(text)]

    if not positions:
        # No section headers found — return as single section
        return [text] if text.strip() else []

    # Build raw sections
    raw_sections = []
    for i, pos in enumerate(positions):
        end = positions[i + 1] if i + 1 < len(positions) else len(text)
        section = text[pos:end].strip()
        if section:
            sec_num = _get_section_number(section)
            raw_sections.append((sec_num, section))

    # Include any content BEFORE the first section header (e.g., title, preamble)
    if positions[0] > 0:
        preamble = text[:positions[0]].strip()
        if preamble:
            raw_sections.insert(0, ('', preamble))

    # Context preservation: identify parent sections with subsections
    # A parent is e.g., section "7" that has children "7.1", "7.2"
    result_sections = []
    parent_context = {}  # Maps parent number -> intro text (first few lines)

    for sec_num, section_text in raw_sections:
        if sec_num and '.' not in sec_num:
            # This is a top-level section (e.g., "7", "2", "3")
            # Check if it has subsections after it
            has_children = any(
                child_num.startswith(sec_num + '.')
                for child_num, _ in raw_sections
                if child_num
            )
            if has_children:
                # Store the parent's intro text for prepending to children
                # Extract just the header and first paragraph as context
                lines = section_text.split('\n')
                context_lines = []
                for line in lines:
                    context_lines.append(line)
                    # Stop after we've captured the intro paragraph
                    if len(context_lines) > 1 and line.strip() == '':
                        break
                    if len('\n'.join(context_lines)) > 500:
                        break
                parent_context[sec_num] = '\n'.join(context_lines).strip()

        # Check if this section needs parent context prepended
        if sec_num and '.' in sec_num:
            parent_num = sec_num.split('.')[0]
            if parent_num in parent_context:
                # Prepend parent context to this subsection
                context = parent_context[parent_num]
                section_text = f"{context}\n\n{section_text}"

        result_sections.append(section_text)

    return result_sections


def _split_by_paragraphs(text: str, max_chars: int) -> List[str]:
    """Fallback: split a large section by paragraphs into chunks."""
    chunks = []
    paras = text.split('\n\n')
    current_chunk = []
    current_len = 0

    for para in paras:
        para_len = len(para)
        if current_len + para_len > max_chars and current_chunk:
            chunks.append("\n\n".join(current_chunk))
            current_chunk = []
            current_len = 0

        if para_len > max_chars:
            # Paragraph itself too large — split by words
            words = para.split(' ')
            temp = []
            temp_len = 0
            for word in words:
                if temp_len + len(word) + 1 > max_chars and temp:
                    chunks.append(" ".join(temp))
                    temp = [word]
                    temp_len = len(word)
                else:
                    temp.append(word)
                    temp_len += len(word) + 1
            if temp:
                current_chunk = [" ".join(temp)]
                current_len = temp_len
        else:
            current_chunk.append(para)
            current_len += para_len + 2

    if current_chunk:
        chunks.append("\n\n".join(current_chunk))

    return chunks


def chunk_document(text: str, max_chars: int = 6000, overlap: float = 0.20) -> List[str]:
    """Split document into overlapping chunks, preferring section boundaries.

    Strategy:
    1. First split on section headers (###, **X.Y**, numbered sections)
    2. Group sections into chunks respecting max_chars
    3. If chunks are too large, split by paragraphs
    4. Provide overlap between chunks to ensure context continuity

    Args:
        text: Full document text
        max_chars: Maximum characters per chunk
        overlap: Overlap fraction (percentage of max_chars)

    Returns:
        List of text chunks
    """
    if not text or not text.strip():
        return []

    # Step 1: Split into sections
    sections = _split_by_sections(text)

    if not sections:
        sections = [text]

    overlap_chars = int(max_chars * overlap)
    chunks = []
    
    current_chunk_text = ""
    
    for section in sections:
        # If this section alone is bigger than max_chars, split it by paragraphs
        if len(section) > max_chars:
            sub_sections = _split_by_paragraphs(section, max_chars)
            for sub in sub_sections:
                if len(current_chunk_text) + len(sub) > max_chars:
                    if current_chunk_text:
                        chunks.append(current_chunk_text.strip())
                        # Keep end of previous chunk as overlap for next chunk
                        current_chunk_text = current_chunk_text[-overlap_chars:] + "\n\n" + sub
                    else:
                        chunks.append(sub.strip())
                else:
                    if current_chunk_text:
                        current_chunk_text += "\n\n" + sub
                    else:
                        current_chunk_text = sub
        else:
            # If adding this section exceeds max_chars
            if len(current_chunk_text) + len(section) > max_chars:
                if current_chunk_text:
                    chunks.append(current_chunk_text.strip())
                    # Keep end of previous chunk as overlap
                    current_chunk_text = current_chunk_text[-overlap_chars:] + "\n\n" + section
                else:
                    current_chunk_text = section
            else:
                if current_chunk_text:
                    current_chunk_text += "\n\n" + section
                else:
                    current_chunk_text = section

    if current_chunk_text:
        chunks.append(current_chunk_text.strip())

    return chunks if chunks else [text]

