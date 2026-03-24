"""Request and response schemas for the PRISM Manual Service."""
from typing import Union

from pydantic import BaseModel


class ManualExtractionRequest(BaseModel):
    project_id: Union[str, int]
    document_url: str
    description: str
    page_no: int
