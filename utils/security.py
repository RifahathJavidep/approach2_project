"""
Keycloak JWT Security — Python equivalent of Java's security stack.

Maps to:
  - JwtAuthConverter.java        → extract_roles()
  - JwtAuthConverterProperties   → config from env vars
  - WebSecurityConfig.java       → get_current_user() dependency
  - TenantInterceptor.java       → get_tenant_user() dependency
  - TenantContext.java           → tenant_id in returned user dict
  - MethodSecurityConfig.java    → role-checking helpers

Usage in routers:
  from utils.security import get_current_user, get_tenant_user

  @router.get("/api/something")
  async def endpoint(user = Depends(get_current_user)):        # no tenant needed
      ...

  @router.post("/api/project/{id}")
  async def endpoint(user = Depends(get_tenant_user)):         # tenant required
      ...
"""
import os
import time
import logging
import threading
from typing import List, Optional

import jwt
import requests
from jwt.algorithms import RSAAlgorithm
from fastapi import Depends, Header, HTTPException, Request, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

logger = logging.getLogger("prism.security")

# ── Configuration (mirrors application.yaml) ─────────────────────────────────
KEYCLOAK_SERVER_URL = os.getenv("KEYCLOAK_SERVER_URL", "http://localhost:8080")
KEYCLOAK_REALM = os.getenv("KEYCLOAK_REALM", "miipe")
KEYCLOAK_CLIENT_ID = os.getenv("KEYCLOAK_CLIENT_ID")          # per-service
KEYCLOAK_CLIENT_SECRET = os.getenv("KEYCLOAK_CLIENT_SECRET")   # per-service
TENANT_PREFIX = os.getenv("KEYCLOAK_TENANT_PREFIX", "tenant_")

# ── Derived URLs (mirrors application.yaml issuer-uri / jwk-set-uri) ─────────
ISSUER_URL = f"{KEYCLOAK_SERVER_URL}/realms/{KEYCLOAK_REALM}"
JWKS_URL = f"{ISSUER_URL}/protocol/openid-connect/certs"
TOKEN_URL = f"{ISSUER_URL}/protocol/openid-connect/token"

# ── Paths that bypass authentication (like Java's permitAll) ──────────────────
PUBLIC_PATHS = {"/health", "/docs", "/openapi.json", "/redoc"}

# ── FastAPI security scheme ───────────────────────────────────────────────────
_bearer = HTTPBearer(auto_error=False)  # auto_error=False so we can handle public paths


# ═════════════════════════════════════════════════════════════════════════════
# JWKS Cache — time-based (fixes stale-key issue from @lru_cache)
# ═════════════════════════════════════════════════════════════════════════════
_jwks_cache: Optional[dict] = None
_jwks_cache_time: float = 0.0
_jwks_lock = threading.Lock()
JWKS_TTL_SECONDS = 300  # refresh every 5 minutes


def _fetch_jwks() -> Optional[dict]:
    """Fetches the JWKS from Keycloak with TTL-based caching."""
    global _jwks_cache, _jwks_cache_time
    now = time.time()

    if _jwks_cache and (now - _jwks_cache_time) < JWKS_TTL_SECONDS:
        return _jwks_cache

    with _jwks_lock:
        # Double-check after acquiring lock
        if _jwks_cache and (now - _jwks_cache_time) < JWKS_TTL_SECONDS:
            return _jwks_cache
        try:
            logger.info("Fetching JWKS from %s", JWKS_URL)
            resp = requests.get(JWKS_URL, timeout=10)
            resp.raise_for_status()
            _jwks_cache = resp.json()
            _jwks_cache_time = time.time()
            return _jwks_cache
        except Exception as e:
            logger.error("Failed to fetch JWKS: %s", e)
            # Return stale cache if available, otherwise None
            return _jwks_cache


def _get_rsa_public_key(token: str):
    """
    Extracts the RSA public key from the JWKS that matches the token's kid.
    Uses jwt.algorithms.RSAAlgorithm.from_jwk() for proper key construction.
    """
    jwks = _fetch_jwks()
    if not jwks:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Keycloak JWKS unavailable",
        )

    unverified_header = jwt.get_unverified_header(token)
    kid = unverified_header.get("kid")

    for key_data in jwks.get("keys", []):
        if key_data.get("kid") == kid:
            # Proper RSA key construction (fixes the raw-dict bug)
            return RSAAlgorithm.from_jwk(key_data)

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=f"No matching key found for kid={kid}",
    )


# ═════════════════════════════════════════════════════════════════════════════
# Role Extraction — mirrors JwtAuthConverter.java
# ═════════════════════════════════════════════════════════════════════════════

def extract_roles(payload: dict) -> List[str]:
    """
    Python equivalent of JwtAuthConverter.extractResourceRoles().

    1. Extracts roles under resource_access → {CLIENT_ID} → roles
    2. Extracts tenant roles under resource_access → tenant_XXX → roles
       and maps them to TENANT_{XXX}_{ROLE}
    3. If any tenant roles exist, adds USER (matching Java logic)
    4. Prefixes everything with ROLE_ (matching Spring Security authorities)
    """
    roles: List[str] = []
    resource_access = payload.get("resource_access", {})

    # ── 1. Client-specific roles ──────────────────────────────────────────────
    if KEYCLOAK_CLIENT_ID and KEYCLOAK_CLIENT_ID in resource_access:
        client_roles = resource_access[KEYCLOAK_CLIENT_ID].get("roles", [])
        roles.extend(client_roles)

    # ── 2. Tenant roles (Java: tenantPrefix matching) ─────────────────────────
    tenant_roles_found = False
    for key, value in resource_access.items():
        if key.startswith(TENANT_PREFIX):
            tenant_name = key[len(TENANT_PREFIX):].upper()
            tenant_role_list = value.get("roles", [])
            if tenant_role_list:
                tenant_roles_found = True
                for role in tenant_role_list:
                    # Java: String.format("TENANT_%s_%s", tenantName, role)
                    roles.append(f"TENANT_{tenant_name}_{role}")

    # ── 3. Auto-add USER if tenant roles exist (Java logic) ───────────────────
    if tenant_roles_found:
        roles.append("USER")

    # ── 4. Prefix with ROLE_ (Spring Security convention) ─────────────────────
    return [f"ROLE_{r}" if not r.startswith("ROLE_") else r for r in roles]


# ═════════════════════════════════════════════════════════════════════════════
# FastAPI Dependencies — mirrors WebSecurityConfig + TenantInterceptor
# ═════════════════════════════════════════════════════════════════════════════

async def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Security(_bearer),
) -> dict:
    """
    FastAPI dependency — equivalent to WebSecurityConfig.securityFilterChain().

    - Public paths (/health, /docs, etc.) are permitted without auth.
    - All other paths require a valid JWT with USER, ADMIN, or SHARED role.

    Returns the decoded JWT payload with an added 'roles' key.
    """
    # ── Permit public paths (Java: .requestMatchers(...).permitAll()) ─────────
    if request.url.path in PUBLIC_PATHS:
        return {"public": True, "roles": []}

    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header missing",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials

    try:
        # ── 1. Get the correct RSA public key ─────────────────────────────────
        rsa_key = _get_rsa_public_key(token)

        # ── 2. Decode and verify (signature + expiry + issuer) ────────────────
        payload = jwt.decode(
            token,
            rsa_key,
            algorithms=["RS256"],
            issuer=ISSUER_URL,
            options={
                "verify_aud": False,   # Keycloak audience varies per client
                "verify_exp": True,
                "verify_iss": True,
            },
        )

        # ── 3. Extract roles (mirrors JwtAuthConverter) ───────────────────────
        payload["roles"] = extract_roles(payload)

        # ── 4. Enforce base roles (Java: hasAnyRole("USER","ADMIN","SHARED")) ─
        required = {"ROLE_USER", "ROLE_ADMIN", "ROLE_SHARED", "ROLE_INTEGRATION"}
        if not required.intersection(payload["roles"]):
            logger.warning(
                "User %s lacks required roles. Has: %s",
                payload.get("preferred_username"),
                payload["roles"],
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions",
            )

        return payload

    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
        )
    except jwt.InvalidIssuerError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token issuer",
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("JWT verification failed: %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Authentication failed: {e}",
        )


async def get_tenant_user(
    request: Request,
    x_tenant_id: Optional[str] = Header(None, alias="X-TENANT-ID"),
    user: dict = Depends(get_current_user),
) -> dict:
    """
    FastAPI dependency — equivalent of TenantInterceptor.preHandle().

    Validates:
      1. X-TENANT-ID header is present
      2. User JWT has matching ROLE_TENANT_{ID}_* OR ROLE_ADMIN/INTEGRATION/SHARED

    Returns the user dict with added 'tenant_id' key.
    """
    # Skip for public paths
    if user.get("public"):
        return user

    if not x_tenant_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing required header: X-TENANT-ID",
        )

    # ── Java: tenantMatcherString = "ROLE_TENANT_{ID}" ────────────────────────
    tenant_matcher = f"ROLE_TENANT_{x_tenant_id.upper()}"
    bypass_roles = {"ROLE_ADMIN", "ROLE_INTEGRATION", "ROLE_SHARED"}

    has_tenant_access = any(
        role.startswith(tenant_matcher) or role in bypass_roles
        for role in user.get("roles", [])
    )

    if not has_tenant_access:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"No access to tenant '{x_tenant_id}'",
        )

    user["tenant_id"] = x_tenant_id
    return user


# ═════════════════════════════════════════════════════════════════════════════
# Service-to-Service Token — Client Credentials Grant
# Used by java_client.py to authenticate with the Java backend
# ═════════════════════════════════════════════════════════════════════════════

_service_token: Optional[str] = None
_service_token_expiry: float = 0.0
_token_lock = threading.Lock()


def get_service_token() -> Optional[str]:
    """
    Obtain a service account token via Keycloak Client Credentials Grant.
    Matches how Java services authenticate service-to-service.

    The token is cached and auto-refreshed 30 seconds before expiry.
    """
    global _service_token, _service_token_expiry

    if not KEYCLOAK_CLIENT_ID or not KEYCLOAK_CLIENT_SECRET:
        logger.warning("KEYCLOAK_CLIENT_ID or KEYCLOAK_CLIENT_SECRET not set — skipping service token")
        return None

    now = time.time()
    if _service_token and (now < _service_token_expiry - 30):
        return _service_token

    with _token_lock:
        # Double-check after lock
        if _service_token and (now < _service_token_expiry - 30):
            return _service_token

        try:
            resp = requests.post(
                TOKEN_URL,
                data={
                    "grant_type": "client_credentials",
                    "client_id": KEYCLOAK_CLIENT_ID,
                    "client_secret": KEYCLOAK_CLIENT_SECRET,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()

            _service_token = data["access_token"]
            _service_token_expiry = now + data.get("expires_in", 300)

            logger.info(
                "Service token obtained (expires in %ds)",
                data.get("expires_in", 300),
            )
            return _service_token

        except Exception as e:
            logger.error("Failed to obtain service token: %s", e, exc_info=True)
            return _service_token  # return stale token if available
