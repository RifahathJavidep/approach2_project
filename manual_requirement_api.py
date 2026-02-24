"""
manual_requirement_api.py
==========================
FastAPI service for manual requirement entry when DSPy auto-extraction fails.

Input  (POST /extract-requirement):
    - document_url  : S3, FTP, or HTTPS URL to the PDF
    - description   : Brief description of the requirement
    - page_no       : Page number where requirement appears (mandatory, 1-indexed)

Output : Full structured requirement JSON

Config : config.json  (groq_api_key, S3/FTP credentials)

Run:
    uvicorn manual_requirement_api:app --reload --port 8000

Swagger UI:
    http://localhost:8000/docs
"""

import io
import json
import re
import ftplib
import tempfile
import urllib.request
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import fitz  # PyMuPDF
from fastapi import FastAPI, HTTPException
from groq import Groq
from pydantic import BaseModel, Field

# OCR
try:
    import pytesseract
    from PIL import Image
    OCR_AVAILABLE = True
except ImportError:
    OCR_AVAILABLE = False

# AWS S3
try:
    import boto3
    from botocore.exceptions import BotoCoreError, ClientError
    S3_AVAILABLE = True
except ImportError:
    S3_AVAILABLE = False


# ─────────────────────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────────────────────

BASE_DIR    = Path(__file__).parent
CONFIG_FILE = BASE_DIR / "config.json"
GROQ_MODEL  = "llama-3.3-70b-versatile"

# Fixed internal context window — ±1 page around the target page
CONTEXT_WINDOW = 1


def load_config() -> dict:
    """Load and validate config.json."""
    if not CONFIG_FILE.exists():
        raise RuntimeError(
            f"config.json not found at {CONFIG_FILE}\n"
            "Create it with the template below and add your credentials:\n"
            + json.dumps({
                "groq_api_key":      "gsk_xxxx",
                "groq_model":        "llama-3.3-70b-versatile",
                "aws_access_key_id": "",
                "aws_secret_key":    "",
                "aws_region":        "us-east-1",
                "ftp_username":      "",
                "ftp_password":      ""
            }, indent=2)
        )
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    if not cfg.get("groq_api_key"):
        raise RuntimeError("groq_api_key is missing or empty in config.json")

    global GROQ_MODEL
    GROQ_MODEL = cfg.get("groq_model", GROQ_MODEL)
    return cfg


try:
    CONFIG = load_config()
except RuntimeError as e:
    CONFIG = {}
    print(f"⚠  Config warning: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# PYDANTIC MODELS
# ─────────────────────────────────────────────────────────────────────────────

class ExtractionRequest(BaseModel):
    document_url: str = Field(
        ...,
        description="Full URL to the PDF — supports s3://, ftp://, or https://",
        example="s3://my-bucket/documents/PTW_Self_Serve_Phase_1_Solution.pdf"
    )
    description: str = Field(
        ...,
        min_length=10,
        description="Brief description of the requirement in your own words",
        example="Dashboard should display total active, suspended and cancelled subscribers"
    )
    page_no: int = Field(
        ...,
        ge=1,
        description="Page number where the requirement appears (1-indexed, mandatory)"
    )


class ExtractionResponse(BaseModel):
    requirement_id:            str
    title:                     str
    description:               str
    requirement_type:          str
    category:                  str
    priority:                  str
    user_roles:                list[str]
    user_story:                str
    acceptance_criteria:       list[str]
    test_steps:                list[dict]
    business_rules:            list[str]
    dependencies:              list[str]
    assumptions:               list[str]
    source_document:           str
    source_url:                str
    source_page:               int
    context_pages_used:        list[int]
    extraction_method:         str
    extracted_at:              str
    user_provided_description: str
    validation_warnings:       list[str]


# ─────────────────────────────────────────────────────────────────────────────
# DOCUMENT DOWNLOAD
# ─────────────────────────────────────────────────────────────────────────────

def download_from_s3(url: str, dest_path: Path) -> None:
    """
    Download PDF from S3.
    Supports both:
      s3://bucket-name/path/to/file.pdf
      https://bucket.s3.amazonaws.com/path/to/file.pdf
    """
    if not S3_AVAILABLE:
        raise HTTPException(
            status_code=500,
            detail="boto3 is not installed. Run: pip install boto3"
        )

    parsed     = urlparse(url)
    bucket     = parsed.netloc
    key        = parsed.path.lstrip("/")
    aws_key    = CONFIG.get("aws_access_key_id",  "")
    aws_secret = CONFIG.get("aws_secret_key",      "")
    region     = CONFIG.get("aws_region",          "us-east-1")

    try:
        if aws_key and aws_secret:
            s3 = boto3.client(
                "s3",
                aws_access_key_id     = aws_key,
                aws_secret_access_key = aws_secret,
                region_name           = region,
            )
        else:
            # Use IAM role / environment credentials
            s3 = boto3.client("s3", region_name=region)

        s3.download_file(bucket, key, str(dest_path))

    except ClientError as e:
        code = e.response["Error"]["Code"]
        raise HTTPException(
            status_code = 404 if code == "404" else 502,
            detail      = f"S3 error ({code}): {e.response['Error']['Message']}"
        )
    except BotoCoreError as e:
        raise HTTPException(status_code=502, detail=f"S3 connection error: {str(e)}")


def download_from_ftp(url: str, dest_path: Path) -> None:
    """
    Download PDF from FTP.
    URL format: ftp://hostname/path/to/file.pdf
    Credentials read from config.json (ftp_username / ftp_password).
    """
    parsed   = urlparse(url)
    host     = parsed.netloc
    path     = parsed.path
    username = CONFIG.get("ftp_username", "anonymous")
    password = CONFIG.get("ftp_password", "anonymous@")

    try:
        ftp = ftplib.FTP(host)
        ftp.login(user=username, passwd=password)
        with open(dest_path, "wb") as f:
            ftp.retrbinary(f"RETR {path}", f.write)
        ftp.quit()
    except ftplib.all_errors as e:
        raise HTTPException(status_code=502, detail=f"FTP error: {str(e)}")


def download_from_https(url: str, dest_path: Path) -> None:
    """Download PDF from a public HTTPS URL."""
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            dest_path.write_bytes(response.read())
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"HTTPS download error: {str(e)}")


def download_pdf(document_url: str) -> tuple[Path, str]:
    """
    Detect URL scheme and download the PDF to a temp file.
    Returns (local_pdf_path, filename).
    """
    parsed   = urlparse(document_url)
    scheme   = parsed.scheme.lower()
    filename = Path(parsed.path).name or "document.pdf"

    # Create temp directory that persists for this request lifecycle
    tmp_dir  = Path(tempfile.mkdtemp())
    tmp_file = tmp_dir / filename

    if scheme == "s3":
        download_from_s3(document_url, tmp_file)

    elif scheme == "ftp":
        download_from_ftp(document_url, tmp_file)

    elif scheme in ("http", "https"):
        download_from_https(document_url, tmp_file)

    else:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported URL scheme '{scheme}'. Supported: s3://, ftp://, https://"
        )

    if not tmp_file.exists() or tmp_file.stat().st_size == 0:
        raise HTTPException(
            status_code=502,
            detail=f"Downloaded file is empty or missing: {document_url}"
        )

    return tmp_file, filename


# ─────────────────────────────────────────────────────────────────────────────
# PDF + OCR HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def get_pdf_page_count(pdf_path: Path) -> int:
    doc   = fitz.open(str(pdf_path))
    count = len(doc)
    doc.close()
    return count


def validate_page_no(pdf_path: Path, page_no: int, filename: str) -> None:
    """Raise 400 if page_no is out of range."""
    total = get_pdf_page_count(pdf_path)
    if page_no < 1 or page_no > total:
        raise HTTPException(
            status_code=400,
            detail={
                "error":       "Page number out of range",
                "page_no":     page_no,
                "total_pages": total,
                "valid_range": f"1 – {total}",
                "document":    filename,
            }
        )


def ocr_page(pdf_path: Path, page_no: int) -> str:
    """Render page at 2× zoom via fitz then OCR with pytesseract."""
    if not OCR_AVAILABLE:
        return "[OCR unavailable — install Pillow and pytesseract]"
    doc = fitz.open(str(pdf_path))
    pix = doc[page_no - 1].get_pixmap(matrix=fitz.Matrix(2.0, 2.0))
    doc.close()
    img = Image.open(io.BytesIO(pix.tobytes("png")))
    return pytesseract.image_to_string(img).strip()


def extract_page_text(pdf_path: Path, page_no: int) -> str:
    """
    Extract text from a single page (1-indexed).
    Auto-falls back to OCR if page has no selectable text.
    """
    doc  = fitz.open(str(pdf_path))
    text = doc[page_no - 1].get_text().strip()
    doc.close()

    if not text:
        text = ocr_page(pdf_path, page_no)

    return text


def build_context_text(pdf_path: Path, page_no: int) -> tuple[str, list[int]]:
    """
    Combine text from page_no ± CONTEXT_WINDOW (fixed at 1).
    Clips automatically at document boundaries (handles first/last page safely).
    Returns (combined_text, pages_used).
    """
    total = get_pdf_page_count(pdf_path)
    start = max(1, page_no - CONTEXT_WINDOW)
    end   = min(total, page_no + CONTEXT_WINDOW)
    pages = list(range(start, end + 1))

    parts = []
    for p in pages:
        label = f"=== PAGE {p} ===" + (" ← TARGET" if p == page_no else "")
        parts.append(label + "\n" + extract_page_text(pdf_path, p))

    return "\n\n".join(parts), pages


# ─────────────────────────────────────────────────────────────────────────────
# GROQ LLM CALL
# ─────────────────────────────────────────────────────────────────────────────

EXTRACTION_PROMPT = """You are a senior business analyst. A user identified a requirement \
in a business document and gave you a brief description.

Use the description as a SEMANTIC ANCHOR to locate the correct section in the page content, \
then extract ALL fields accurately — do NOT invent content not present in the text.

─────────────────────────────────────────────────
USER DESCRIPTION:
{description}

DOCUMENT : {doc_name}
PAGE     : {page_no}
─────────────────────────────────────────────────
PAGE CONTENT:
{page_text}
─────────────────────────────────────────────────

Return ONLY a valid JSON object with the exact keys below. No markdown, no backticks, no extra text.

{{
  "title":                "Short title 5–8 words",
  "description":          "Full 1–3 sentence description of what the system must do",
  "requirement_type":     "Functional or Non-Functional",
  "category":             "Feature area e.g. Dashboard, Warranty, Security, API, etc.",
  "priority":             "High or Medium or Low",
  "user_roles":           ["role1", "role2"],
  "user_story":           "As a <role>, I want <action> so that <benefit>",
  "acceptance_criteria":  ["Testable criterion 1", "Testable criterion 2"],
  "test_steps": [
    {{"step_num": 1, "action": "...", "expected_result": "...", "test_data": "..."}},
    {{"step_num": 2, "action": "...", "expected_result": "...", "test_data": "..."}}
  ],
  "business_rules":  ["Business rule 1", "Business rule 2"],
  "dependencies":    ["System or requirement this depends on"],
  "assumptions":     ["Assumption made during extraction"]
}}

Rules:
- Ground every field in actual page content.
- acceptance_criteria must be specific and testable.
- test_steps must include at least one positive and one negative scenario.
- If a field cannot be determined from context, use [] or "Unknown".
"""


def call_groq(description: str, doc_name: str, page_no: int, page_text: str) -> dict:
    """Call Groq directly (no DSPy). Returns parsed requirement dict."""
    api_key = CONFIG.get("groq_api_key")
    if not api_key:
        raise HTTPException(
            status_code=500,
            detail="groq_api_key not set in config.json"
        )

    client = Groq(api_key=api_key)
    prompt = EXTRACTION_PROMPT.format(
        description = description,
        doc_name    = doc_name,
        page_no     = page_no,
        page_text   = page_text[:6000],   # stay within token limit
    )

    try:
        response = client.chat.completions.create(
            model       = GROQ_MODEL,
            messages    = [{"role": "user", "content": prompt}],
            temperature = 0.1,
            max_tokens  = 2048,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Groq API error: {str(e)}")

    raw = response.choices[0].message.content.strip()

    # Strip accidental markdown fences
    raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.MULTILINE)
    raw = re.sub(r"\s*```$",          "", raw, flags=re.MULTILINE)

    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise HTTPException(
            status_code=502,
            detail=f"Groq returned invalid JSON: {e}. Raw: {raw[:300]}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# ID GENERATION + VALIDATION
# ─────────────────────────────────────────────────────────────────────────────

def generate_requirement_id() -> str:
    """Generate BBSSC-MANUAL-XXX based on timestamp to ensure uniqueness."""
    ts = datetime.now().strftime("%Y%m%d%H%M%S")
    return f"BBSSC-MANUAL-{ts}"


def validate_extracted(req: dict) -> list[str]:
    """Return list of warnings for missing or non-standard fields."""
    warnings = []
    if not req.get("title"):
        warnings.append("title is empty")
    if not req.get("acceptance_criteria"):
        warnings.append("acceptance_criteria is empty")
    if not req.get("test_steps"):
        warnings.append("test_steps is empty")
    if req.get("requirement_type") not in ("Functional", "Non-Functional"):
        warnings.append(f"requirement_type '{req.get('requirement_type')}' is non-standard")
    if req.get("priority") not in ("High", "Medium", "Low"):
        warnings.append(f"priority '{req.get('priority')}' is non-standard")
    return warnings


# ─────────────────────────────────────────────────────────────────────────────
# FAST API APP
# ─────────────────────────────────────────────────────────────────────────────

app = FastAPI(
    title       = "Manual Requirement Entry API",
    description = (
        "Fallback service for manual requirement entry when DSPy auto-extraction fails.\n\n"
        "Provide a **document_url** (S3 / FTP / HTTPS), **description**, and **page_no**.\n"
        "The API downloads the PDF, OCR-reads the page, calls Groq, and returns "
        "the fully structured requirement JSON."
    ),
    version = "2.0.0",
)


# ── GET /health ───────────────────────────────────────────────────────────────
@app.get("/health", tags=["System"])
def health_check():
    """Check API health, config, and available integrations."""
    return {
        "status":           "ok",
        "groq_api_key_set": bool(CONFIG.get("groq_api_key")),
        "groq_model":       GROQ_MODEL,
        "ocr_available":    OCR_AVAILABLE,
        "s3_available":     S3_AVAILABLE,
        "context_window":   CONTEXT_WINDOW,
        "supported_schemes": ["s3://", "ftp://", "https://", "http://"],
    }


# ── POST /extract-requirement ─────────────────────────────────────────────────
@app.post(
    "/extract-requirement",
    response_model = ExtractionResponse,
    tags           = ["Extraction"],
    summary        = "Extract requirement from a document URL",
    description    = (
        "**Input:** document_url + description + page_no\n\n"
        "**Steps:**\n"
        "1. Download PDF from S3 / FTP / HTTPS\n"
        "2. Validate page number against document\n"
        "3. Extract page text (auto OCR for image-based PDFs)\n"
        "4. Build context from target page ± 1 surrounding pages\n"
        "5. Call Groq LLM to extract all requirement fields\n"
        "6. Return complete structured requirement JSON"
    )
)
def extract_requirement(request: ExtractionRequest):

    # ── Step 1: Download PDF ───────────────────────────────────────────────
    pdf_path, filename = download_pdf(request.document_url)

    try:
        # ── Step 2: Validate page number ──────────────────────────────────
        validate_page_no(pdf_path, request.page_no, filename)

        # ── Step 3 & 4: Extract text with context window ──────────────────
        page_text, pages_used = build_context_text(pdf_path, request.page_no)

        if len(page_text.strip()) < 30:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Could not extract meaningful text from page {request.page_no} "
                    f"of '{filename}' (only {len(page_text)} chars extracted). "
                    "The page may be blank or the PDF may be corrupted."
                )
            )

        # ── Step 5: Call Groq LLM ─────────────────────────────────────────
        extracted = call_groq(
            description = request.description,
            doc_name    = filename,
            page_no     = request.page_no,
            page_text   = page_text,
        )

        # ── Step 6: Build response ────────────────────────────────────────
        return ExtractionResponse(
            requirement_id            = generate_requirement_id(),
            title                     = extracted.get("title", ""),
            description               = extracted.get("description", request.description),
            requirement_type          = extracted.get("requirement_type", "Functional"),
            category                  = extracted.get("category", "General"),
            priority                  = extracted.get("priority", "Medium"),
            user_roles                = extracted.get("user_roles", []),
            user_story                = extracted.get("user_story", ""),
            acceptance_criteria       = extracted.get("acceptance_criteria", []),
            test_steps                = extracted.get("test_steps", []),
            business_rules            = extracted.get("business_rules", []),
            dependencies              = extracted.get("dependencies", []),
            assumptions               = extracted.get("assumptions", []),
            source_document           = filename,
            source_url                = request.document_url,
            source_page               = request.page_no,
            context_pages_used        = pages_used,
            extraction_method         = "manual",
            extracted_at              = datetime.now().isoformat(),
            user_provided_description = request.description,
            validation_warnings       = validate_extracted(extracted),
        )

    finally:
        # Always clean up the temp PDF regardless of success or failure
        try:
            pdf_path.unlink(missing_ok=True)
            pdf_path.parent.rmdir()
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("manual_requirement_api:app", host="0.0.0.0", port=8000, reload=True)
