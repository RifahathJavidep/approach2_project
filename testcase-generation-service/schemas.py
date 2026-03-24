"""
Request and response schemas for the PRISM API.
All Pydantic models live here — imported by routers, never by services or tasks.
"""
from typing import List, Optional, Union

from pydantic import BaseModel


class ExtractionRequest(BaseModel):
    project_id: Union[str, int]
    project_name: Optional[str] = None
    file_urls: List[str]


class ManualExtractionRequest(BaseModel):
    project_id: Union[str, int]
    document_url: str
    description: str
    page_no: int


class TestCaseRequest(BaseModel):
    project_id: Union[str, int]
    project_name: Optional[str] = None
    requirements_s3_key: Optional[str] = None
    requirements: Optional[list] = None
    document_urls: Optional[List[str]] = []


class UploadUrlRequest(BaseModel):
    project_id: str
    filename: str
