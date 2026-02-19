"""
Utility Functions — Chunking and Text Helpers

Shared utility functions used across the extraction pipeline.

Moved from: extract_requirements.py lines 458–494
"""

from typing import List


def chunk_document(text: str, max_chars: int = 6000, overlap: float = 0.20) -> List[str]:
    """Split document into overlapping chunks to avoid cutting requirements.

    Args:
        text: Full document text
        max_chars: Maximum characters per chunk
        overlap: Overlap fraction (0.0–1.0) to prevent losing context at boundaries

    Returns:
        List of text chunks
    """
    chunks = []
    paras = text.split('\n\n')
    current_chunk = []
    current_len = 0

    overlap_chars = int(max_chars * overlap)

    for para in paras:
        para_len = len(para)
        if current_len + para_len > max_chars:
            # Save current chunk (if not empty)
            if current_chunk:
                chunks.append("\n\n".join(current_chunk))
                current_chunk = []
                current_len = 0

            # If the current paragraph itself is too large, split it
            if para_len > max_chars:
                words = para.split(' ')
                temp_para = []
                temp_len = 0
                for word in words:
                    # Plus 1 for the space
                    if temp_len + len(word) + 1 > max_chars and temp_para:
                        chunks.append(" ".join(temp_para))
                        temp_para = [word]
                        temp_len = len(word)
                    else:
                        temp_para.append(word)
                        temp_len += len(word) + 1
                
                if temp_para:
                    current_chunk = [" ".join(temp_para)]
                    current_len = temp_len
            else:
                current_chunk = [para]
                current_len = para_len
        else:
            current_chunk.append(para)
            current_len += para_len + 2  # +2 for \n\n separator length

    if current_chunk:
        chunks.append("\n\n".join(current_chunk))

    return chunks
