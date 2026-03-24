"""
AWS Secret Manager — loads API keys and credentials at startup.

Requirement: API keys must NOT live in .env files for cloud deployments.
All secrets are fetched from AWS Secret Manager once at process start.

Local development: falls back to environment variables if Secret Manager is unreachable,
so the dev workflow (using .env) is unchanged.

Usage:
    from common.secrets import get_secret
    api_key = get_secret("GROQ_API_KEY")
"""
import json
import logging
import os

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger("prism.secrets")

_cache: dict = {}
_MISSING = object()

# Secret names in AWS Secret Manager
SECRET_NAME = os.getenv("AWS_SECRET_ID", "miipe/production")
REGION_NAME = os.getenv("AWS_DEFAULT_REGION", "us-east-1")

# Set this to True in your deployment environment (e.g., Docker, ECS, Lambda)
# to ensure the system prioritizes AWS Secrets Manager and warns if it's missing.
IS_DEPLOYED = os.getenv("IS_DEPLOYED", "false").lower() == "true"


def get_secret(key: str, default=_MISSING) -> str:
    """
    Return a secret value by key.
    
    WITH DEPLOYMENT:
    - Automatically fetches all secrets from AWS Secret Manager (miipe/production) at startup.
    - These values are cached in memory for the duration of the process.
    
    WITHOUT DEPLOYMENT (Local Dev):
    - Falls back to local environment variables (from .env) if not found in AWS.
    - Allows developers to work offline without needing AWS credentials.
    """
    
    # 1. Check AWS Cache first (Primary for Deployment)
    if not _cache:
        _load_from_aws()

    if key in _cache:
        return _cache[key]

    # 2. Local Fallback (Primary for Local Development / Secondary for Deployment)
    # This allows .env files to still work locally.
    value = os.getenv(key)
    if value:
        if IS_DEPLOYED:
            logger.warning("Secret '%s' NOT found in AWS; using environment variable instead.", key)
        else:
            logger.debug("Secret '%s' loaded from environment variable (local dev)", key)
        return value

    # 3. Last Resort: Default or Error
    if default is not _MISSING:
        return default

    raise RuntimeError(
        f"Secret '{key}' not found in AWS Secret Manager (id={SECRET_NAME}) or environment variables. "
        f"Deployment Mode: {'Active' if IS_DEPLOYED else 'Inactive'}"
    )


def _load_from_aws() -> None:
    """Fetch all secrets from AWS Secret Manager and populate the cache."""
    global _cache
    if _cache:
        return

    logger.info("Fetching secrets from AWS Secret Manager (id=%s)...", SECRET_NAME)
    
    # Create a Secrets Manager client
    session = boto3.session.Session()
    client = session.client(
        service_name='secretsmanager',
        region_name=REGION_NAME
    )

    try:
        get_secret_value_response = client.get_secret_value(
            SecretId=SECRET_NAME
        )
        
        secret_string = get_secret_value_response['SecretString']
        
        # Parse JSON if it looks like JSON, otherwise store the whole thing
        try:
            secrets = json.loads(secret_string)
            if isinstance(secrets, dict):
                _cache.update(secrets)
                logger.info("Loaded %d secrets from AWS Secret Manager", len(secrets))
            else:
                _cache["__RAW_SECRET__"] = secret_string
        except json.JSONDecodeError:
            _cache["__RAW_SECRET__"] = secret_string
            logger.warning("SecretString is not JSON; stored as raw secret.")

    except ClientError as e:
        logger.warning("AWS Secret Manager unavailable (%s) — falling back to environment variables", e)
    except Exception as e:
        logger.warning("Unexpected error loading secrets: %s", e)
