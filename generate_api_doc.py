from fpdf import FPDF

class PRISMDoc(FPDF):
    def header(self):
        self.set_font('helvetica', 'B', 16)
        self.cell(0, 10, 'PRISM API & Integration Documentation', ln=True, align='C')
        self.ln(5)

    def footer(self):
        self.set_y(-15)
        self.set_font('helvetica', 'I', 8)
        self.cell(0, 10, f'Page {self.page_no()}', align='C')

def generate_pdf():
    pdf = PRISMDoc()
    pdf.add_page()
    
    # Section 1
    pdf.set_font("helvetica", 'B', 14)
    pdf.cell(0, 10, "1. Requirements Extraction Service (Python API)", ln=True)
    pdf.ln(2)
    
    pdf.set_font("helvetica", 'B', 12)
    pdf.cell(0, 8, "A. Async Extraction (Main Flow)", ln=True)
    pdf.set_font("helvetica", size=10)
    pdf.multi_cell(0, 5, "Initializes the extraction process in the background. Returns a task_id.\nEndpoint: POST /extract-async")
    pdf.ln(2)
    pdf.set_font("courier", size=9)
    payload = """Payload:
{
  "project_id": "healthcare_portal_101",
  "file_urls": [
    "s3://my-bucket/docs/policy.pdf",
    "s3://my-bucket/docs/ui_specs.pptx"
  ]
}"""
    pdf.multi_cell(0, 5, payload)
    pdf.ln(5)

    pdf.set_font("helvetica", 'B', 12)
    pdf.cell(0, 8, "B. Status Polling", ln=True)
    pdf.set_font("helvetica", size=10)
    pdf.multi_cell(0, 5, "Used to check the status of the Celery task.\nEndpoint: GET /status/{task_id}")
    pdf.ln(2)
    pdf.set_font("courier", size=9)
    resp = """Response Example:
{
  "task_id": "8b9cad0e-...",
  "status": "PROGRESS",
  "result": { "total_requirements": 38 }
}"""
    pdf.multi_cell(0, 5, resp)
    pdf.ln(10)

    # Section 2
    pdf.set_font("helvetica", 'B', 14)
    pdf.cell(0, 10, "2. Status Updates (Calls to Java Backend)", ln=True)
    pdf.set_font("helvetica", size=10)
    pdf.multi_cell(0, 5, "Base URL: POST http://localhost:8080/api/document-statuses/projects/{project_id}")
    pdf.ln(3)
    
    status_text = """Updates sent by the Python service:
- PENDING (Batch): Initial list of files.
- IN_PROGRESS: Sent when a specific file starts processing.
- COMPLETED: Sent when a file is successfully extracted.
- FAILED: Sent if an error occurs for a file."""
    pdf.multi_cell(0, 5, status_text)
    pdf.ln(5)
    
    pdf.set_font("courier", size=9)
    sample = """Example Payload (IN_PROGRESS):
[
  { "documentUrl": "s3://file_A.pdf", "status": "IN_PROGRESS" }
]"""
    pdf.multi_cell(0, 5, sample)
    pdf.ln(10)

    # Section 3
    pdf.set_font("helvetica", 'B', 14)
    pdf.cell(0, 10, "3. Final Storage (Sync to Postgres)", ln=True)
    pdf.set_font("helvetica", size=10)
    pdf.multi_cell(0, 5, "Endpoint: POST /api/requirements/project/{project_id}")
    pdf.ln(2)
    pdf.set_font("courier", size=9)
    final_p = """Payload:
[
  {
    "requirement_id": "HC-001",
    "title": "Dual-Factor Authentication",
    "description": "System must require MFA...",
    "type": "Technical",
    "priority": "High"
  }
]"""
    pdf.multi_cell(0, 5, final_p)
    pdf.ln(10)

    # Section 4
    pdf.set_font("helvetica", 'B', 14)
    pdf.cell(0, 10, "4. AWS Integration Details", ln=True)
    pdf.set_font("helvetica", size=10)
    aws_text = """The service requires the following .env variables:
1. AWS_ACCESS_KEY_ID: Standard access key.
2. AWS_SECRET_ACCESS_KEY: Standard secret key.
3. AWS_SESSION_TOKEN: Optional (required for SSO/Temp tokens).
4. S3_BUCKET_NAME: The target bucket for all operations."""
    pdf.multi_cell(0, 5, aws_text)

    output_path = "PRISM_API_Documentation.pdf"
    pdf.output(output_path)
    return output_path

if __name__ == "__main__":
    path = generate_pdf()
    print(f"PDF Generated successfully at: {path}")
