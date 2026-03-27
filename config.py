"""
Global Configuration — The single source of truth for all PRISM settings.

This module centralizes all environment variables, secrets, and tuning constants.
It uses 'common.secrets.get_secret' to fetch values from either AWS Secrets Manager
(in production) or local .env files (during development).
"""
import logging
from typing import List, Optional

from common.secrets import get_secret

logger = logging.getLogger("prism.config")

class Settings:
    # ── Infrastructure & URLs (from Secrets/Env) ──────────────────────────────
    
    # JAVA Backend (Katsu)
    JAVA_BACKEND_URL: str = get_secret("JAVA_BACKEND_URL", "http://localhost:8081")
    
    # TestGen Service
    TESTGEN_SERVICE_URL: str = get_secret("TESTGEN_SERVICE_URL", "http://localhost:8002")
    
    # AWS & Storage
    S3_BUCKET_NAME: str = get_secret("S3_BUCKET_NAME", "katsu-ai-requirement-documents")
    AWS_REGION: str = get_secret("AWS_REGION", "us-east-1")
    
    # Keycloak Auth
    KEYCLOAK_SERVER_URL: str = get_secret("KEYCLOAK_SERVER_URL", "http://localhost:8080")
    KEYCLOAK_REALM: str = get_secret("KEYCLOAK_REALM", "miipe")
    KEYCLOAK_TENANT_PREFIX: str = get_secret("KEYCLOAK_TENANT_PREFIX", "tenant_")
    
    # ── Concurrency & Performance ─────────────────────────────────────────────
    
    # Number of parallel workers for S3 downloads
    MAX_DOWNLOAD_WORKERS: int = 5
    
    # Global request timeout (seconds)
    DEFAULT_TIMEOUT: int = 30
    
    # Short timeout for health checks or small triggers
    SHORT_TIMEOUT: int = 10
    
    # ── AI & Business Logic Tuning ───────────────────────────────────────────
    
    # Deduplication Similarity Threshold (Cosine Similarity)
    # 1.0 = Perfect match, 0.0 = No match
    DEDUP_THRESHOLD: float = 0.85
    
    # Fallback threshold if not specified
    DEFAULT_DEDUP_THRESHOLD: float = 0.80
    
    # TF-IDF Vectorizer Max Features
    TFIDF_MAX_FEATURES: int = 5000
    
    # S3 Paths
    UPLOAD_PATH_PREFIX: str = "uploads"
    GENERAL_DOCS_PREFIX: str = "uploads/general/"
    
    # ── Security Defaults ─────────────────────────────────────────────────────
    
    # Keycloak JWKS Cache TTL (seconds)
    JWKS_TTL_SECONDS: int = 300
    
    # Buffer time (seconds) to refresh the Service Token before it expires
    TOKEN_REFRESH_BUFFER: int = 30
    
    # Public paths that bypass authentication
    PUBLIC_PATHS: List[str] = ["/health", "/docs", "/openapi.json", "/redoc"]

# Create a singleton instance
settings = Settings()
