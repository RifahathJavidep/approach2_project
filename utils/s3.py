"""
AWS S3 Utilities — upload, download, list, and generate presigned URLs.
"""
import json
import logging
import os
from pathlib import Path
from urllib.parse import urlparse

import boto3
from botocore.config import Config

from utils.config import settings
from utils.secrets import get_secret

logger = logging.getLogger("prism.s3")


def get_client():
    """Create an S3 client, falling back to default credentials if secrets are missing."""
    # Using None as default prevents RuntimeError if keys are not in secrets/env.
    # If they are None, Boto3 will automatically check IAM Roles, ENV, etc.
    access_key = get_secret("AWS_ACCESS_KEY_ID", None)
    secret_key = get_secret("AWS_SECRET_ACCESS_KEY", None)
    session_token = get_secret("AWS_SESSION_TOKEN", None)
    region = get_secret("AWS_REGION", settings.AWS_REGION)

    return boto3.client(
        "s3",
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        aws_session_token=session_token,
        region_name=region,
        config=Config(signature_version="s3v4"),
    )


def get_bucket() -> str:
    """Return the configured S3 bucket name."""
    return get_secret("S3_BUCKET_NAME", settings.S3_BUCKET_NAME)


def parse_url(s3_url: str) -> tuple:
    """
    Parse an S3 URL into (bucket, key).

    Accepts:
      s3://bucket/key
      https://bucket.s3.amazonaws.com/key
      plain/key  (uses default bucket)
    """
    if s3_url.startswith("s3://"):
        parsed = urlparse(s3_url)
        return parsed.netloc, parsed.path.lstrip("/")

    if "s3.amazonaws.com" in s3_url:
        parsed = urlparse(s3_url)
        return parsed.netloc.split(".s3")[0], parsed.path.lstrip("/")

    return get_bucket(), s3_url


def download(s3_url: str, local_dir: str) -> str:
    """Download a file from S3 into local_dir. Returns the local file path."""
    client = get_client()
    bucket, key = parse_url(s3_url)
    filename = Path(key).name
    local_path = os.path.join(local_dir, filename)

    os.makedirs(local_dir, exist_ok=True)
    logger.info("Downloading s3://%s/%s", bucket, key)
    client.download_file(bucket, key, local_path)
    logger.info("Downloaded %s (%d bytes)", filename, os.path.getsize(local_path))
    return local_path


def upload(local_path: str, s3_key: str, content_type: str = None) -> str:
    """Upload a local file to S3. Returns the S3 URL."""
    client = get_client()
    bucket = get_bucket()
    extra = {"ContentType": content_type} if content_type else {}

    logger.info("Uploading %s → s3://%s/%s", local_path, bucket, s3_key)
    client.upload_file(local_path, bucket, s3_key, ExtraArgs=extra)
    url = f"s3://{bucket}/{s3_key}"
    logger.info("Uploaded: %s", url)
    return url


def upload_json(data: dict, s3_key: str) -> str:
    """Serialize a dict to JSON and upload directly to S3."""
    client = get_client()
    bucket = get_bucket()
    client.put_object(
        Bucket=bucket,
        Key=s3_key,
        Body=json.dumps(data, indent=2),
        ContentType="application/json",
    )
    url = f"s3://{bucket}/{s3_key}"
    logger.info("Uploaded JSON: %s", url)
    return url


def download_json(s3_key: str) -> dict:
    """Download and parse a JSON file from S3."""
    client = get_client()
    bucket = get_bucket()
    response = client.get_object(Bucket=bucket, Key=s3_key)
    return json.loads(response["Body"].read().decode("utf-8"))


def presign_upload(s3_key: str, expiration: int = 3600) -> dict:
    """Generate a pre-signed POST URL for direct browser uploads."""
    client = get_client()
    bucket = get_bucket()
    logger.info("Generating pre-signed URL for s3://%s/%s", bucket, s3_key)
    return client.generate_presigned_post(Bucket=bucket, Key=s3_key, ExpiresIn=expiration)


def exists(s3_key: str) -> bool:
    """Check if a key exists in S3."""
    client = get_client()
    bucket = get_bucket()
    try:
        client.head_object(Bucket=bucket, Key=s3_key)
        return True
    except Exception:
        return False


def list_files(prefix: str) -> list:
    """List all files under a given S3 prefix."""
    client = get_client()
    bucket = get_bucket()
    response = client.list_objects_v2(Bucket=bucket, Prefix=prefix)
    return [
        {
            "key": obj["Key"],
            "filename": Path(obj["Key"]).name,
            "size": obj["Size"],
            "last_modified": obj["LastModified"].isoformat(),
            "url": f"s3://{bucket}/{obj['Key']}",
        }
        for obj in response.get("Contents", [])
        if not obj["Key"].endswith("/")
    ]
