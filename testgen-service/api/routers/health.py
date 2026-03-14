import os
from datetime import datetime

from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
async def health_check():
    """Check that the service is running and credentials are configured."""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "config": {
            "groq_api_key_set": bool(os.getenv("GROQ_API_KEY")),
            "aws_credentials_set": bool(os.getenv("AWS_ACCESS_KEY_ID")),
            "s3_bucket": os.getenv("S3_BUCKET_NAME", "katsu-ai-requirement-documents"),
        },
    }
