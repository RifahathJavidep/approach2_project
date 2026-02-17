"""
S3 Utility Functions
Download files from S3, upload results and models back to S3.
"""

import boto3
import json
import os
import tempfile
from pathlib import Path
from urllib.parse import urlparse
from dotenv import load_dotenv

load_dotenv()


from botocore.config import Config

def get_s3_client():
    """Create and return an S3 client using env credentials with SigV4 support."""
    region = os.getenv("AWS_REGION", "us-east-1")
    return boto3.client(
        "s3",
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
        region_name=region,
        config=Config(signature_version='s3v4')
    )


def get_bucket_name():
    """Get the S3 bucket name from environment."""
    return os.getenv("S3_BUCKET_NAME", "katsuai-tcgen")


def parse_s3_url(s3_url: str) -> tuple:
    """
    Parse an S3 URL into (bucket, key).
    Supports formats:
      - s3://bucket-name/path/to/file.pdf
      - https://bucket-name.s3.amazonaws.com/path/to/file.pdf
      - path/to/file.pdf  (assumes default bucket)
    """
    if s3_url.startswith("s3://"):
        # s3://bucket/key
        parsed = urlparse(s3_url)
        bucket = parsed.netloc
        key = parsed.path.lstrip("/")
        return bucket, key

    elif "s3.amazonaws.com" in s3_url:
        # https://bucket.s3.amazonaws.com/key
        parsed = urlparse(s3_url)
        bucket = parsed.netloc.split(".s3")[0]
        key = parsed.path.lstrip("/")
        return bucket, key

    else:
        # Assume it's just the key, use default bucket
        return get_bucket_name(), s3_url


def download_from_s3(s3_url: str, local_dir: str) -> str:
    """
    Download a file from S3 to a local directory.
    Returns the local file path.
    """
    s3 = get_s3_client()
    bucket, key = parse_s3_url(s3_url)

    # Get filename from key
    filename = Path(key).name
    local_path = os.path.join(local_dir, filename)

    # Ensure local directory exists
    os.makedirs(local_dir, exist_ok=True)

    print(f"  Downloading: s3://{bucket}/{key} -> {local_path}")
    s3.download_file(bucket, key, local_path)
    print(f"  Downloaded: {filename} ({os.path.getsize(local_path)} bytes)")

    return local_path


def upload_to_s3(local_path: str, s3_key: str, content_type: str = None) -> str:
    """
    Upload a local file to S3.
    Returns the S3 URL.
    """
    s3 = get_s3_client()
    bucket = get_bucket_name()

    extra_args = {}
    if content_type:
        extra_args["ContentType"] = content_type

    print(f"  Uploading: {local_path} -> s3://{bucket}/{s3_key}")
    s3.upload_file(local_path, bucket, s3_key, ExtraArgs=extra_args)

    s3_url = f"s3://{bucket}/{s3_key}"
    print(f"  Uploaded: {s3_url}")
    return s3_url


def upload_json_to_s3(data: dict, s3_key: str) -> str:
    """
    Upload a dict as JSON directly to S3.
    Returns the S3 URL.
    """
    s3 = get_s3_client()
    bucket = get_bucket_name()

    print(f"  Uploading JSON -> s3://{bucket}/{s3_key}")
    s3.put_object(
        Bucket=bucket,
        Key=s3_key,
        Body=json.dumps(data, indent=2),
        ContentType="application/json",
    )

    s3_url = f"s3://{bucket}/{s3_key}"
    print(f"  Uploaded: {s3_url}")
    return s3_url


def download_json_from_s3(s3_key: str) -> dict:
    """
    Download and parse a JSON file from S3.
    Returns the parsed dict.
    """
    s3 = get_s3_client()
    bucket = get_bucket_name()

    response = s3.get_object(Bucket=bucket, Key=s3_key)
    content = response["Body"].read().decode("utf-8")
    return json.loads(content)


def generate_presigned_upload_url(s3_key: str, expiration: int = 3600) -> dict:
    """
    Generate a pre-signed POST URL to upload a file directly to S3 from a frontend.
    Returns a dict with 'url' and 'fields'.
    """
    s3 = get_s3_client()
    bucket = get_bucket_name()

    print(f"  Generating pre-signed POST URL for: s3://{bucket}/{s3_key}")
    
    # Generate the pre-signed POST data
    # Note: Conditions can be added here (e.g., content-length-range)
    response = s3.generate_presigned_post(
        Bucket=bucket,
        Key=s3_key,
        ExpiresIn=expiration
    )
    
    return response


def file_exists_in_s3(s3_key: str) -> bool:
    """Check if a file exists in S3."""
    s3 = get_s3_client()
    bucket = get_bucket_name()
    try:
        s3.head_object(Bucket=bucket, Key=s3_key)
        return True
    except s3.exceptions.ClientError:
        return False


# ============================================================================
# SELF-TEST
# ============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("S3 Utils - Connection Test")
    print("=" * 60)

    # Test connection
    try:
        s3 = get_s3_client()
        bucket = get_bucket_name()
        response = s3.list_objects_v2(Bucket=bucket, MaxKeys=5)
        print(f"Connected to S3 bucket: {bucket}")
        print(f"Objects found: {response.get('KeyCount', 0)}")
        for obj in response.get("Contents", []):
            print(f"  - {obj['Key']} ({obj['Size']} bytes)")
        print("S3 connection test PASSED")
    except Exception as e:
        print(f"S3 connection test FAILED: {e}")

    # Test URL parsing
    print("\nURL Parsing Tests:")
    tests = [
        "s3://katsuai-tcgen/projects/test/input/file.pdf",
        "https://katsuai-tcgen.s3.amazonaws.com/projects/test/input/file.pdf",
        "projects/test/input/file.pdf",
    ]
    for url in tests:
        bucket, key = parse_s3_url(url)
        print(f"  {url}")
        print(f"    -> bucket={bucket}, key={key}")
