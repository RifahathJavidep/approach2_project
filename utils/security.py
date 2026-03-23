"""
Keycloak JWT Security — Python equivalent of Java's security stack.

Maps to:
  - Policy.java                    → Policy dataclass
  - TeamRole.java                  → TeamRole dataclass
  - AuthUtils.java                 → extract_team_roles(), is_team_authenticated()
  - TeamPermissionEvaluator.java   → has_permission()
  - JwtAuthConverter.java          → extract_roles()
  - JwtAuthConverterProperties     → config from env vars
  - WebSecurityConfig.java         → get_current_user() dependency
  - TenantInterceptor.java         → get_tenant_user() dependency
  - TenantContext.java             → tenant_id in returned user dict

Usage in routers:
  from utils.security import get_current_user, get_tenant_user, get_team_user, has_permission

  @router.get("/teams/{team_id}/projects/{project_id}/requirements")
  async def endpoint(team_id: str, user = Depends(get_team_user)):
      ...

  # Fine-grained permission check (mirrors @PreAuthorize("hasPermission(#teamId, 'Requirements', 'View')"))
  if not has_permission(team_id, "Requirements", "View", user):
      raise HTTPException(403)
"""
import os
import time
import logging
import threading
from dataclasses import dataclass, field
from typing import List, Optional

import jwt
import requests
from jwt.algorithms import RSAAlgorithm
from fastapi import Depends, Header, HTTPException, Path, Request, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

logger = logging.getLogger("prism.security")

# ── Configuration (mirrors application.yaml) ─────────────────────────────────
KEYCLOAK_SERVER_URL = os.getenv("KEYCLOAK_SERVER_URL", "http://localhost:8080")
KEYCLOAK_REALM = os.getenv("KEYCLOAK_REALM", "miipe")
KEYCLOAK_CLIENT_ID = os.getenv("KEYCLOAK_CLIENT_ID")
KEYCLOAK_CLIENT_SECRET = os.getenv("KEYCLOAK_CLIENT_SECRET")
TENANT_PREFIX = os.getenv("KEYCLOAK_TENANT_PREFIX", "tenant_")

# ── Derived URLs ──────────────────────────────────────────────────────────────
ISSUER_URL = f"{KEYCLOAK_SERVER_URL}/realms/{KEYCLOAK_REALM}"
JWKS_URL = f"{ISSUER_URL}/protocol/openid-connect/certs"
TOKEN_URL = f"{ISSUER_URL}/protocol/openid-connect/token"

# ── Public paths (no auth required) ──────────────────────────────────────────
PUBLIC_PATHS = {"/health", "/docs", "/openapi.json", "/redoc"}

_bearer = HTTPBearer(auto_error=False)


# ═════════════════════════════════════════════════════════════════════════════
# Models — mirrors Policy.java and TeamRole.java
# ═════════════════════════════════════════════════════════════════════════════

@dataclass
class Policy:
    """
    Python equivalent of com.katsu.config.keycloak.models.Policy.

    resource   → resource name, e.g. "Requirements", "Test Cases", "Owner"
    authorized → True = allow, False = deny
    actions    → action names, e.g. ["View", "Create", "Update", "Delete"]
    """
    resource: str = ""
    authorized: bool = False
    actions: List[str] = field(default_factory=list)


@dataclass
class TeamRole:
    """
    Python equivalent of com.katsu.config.keycloak.models.TeamRole.

    id         → team UUID as string
    policyList → list of Policy objects for this team
    """
    id: str = ""
    policyList: List[Policy] = field(default_factory=list)


# ═════════════════════════════════════════════════════════════════════════════
# JWKS Cache
# ═════════════════════════════════════════════════════════════════════════════
_jwks_cache: Optional[dict] = None
_jwks_cache_time: float = 0.0
_jwks_lock = threading.Lock()
JWKS_TTL_SECONDS = 300


def _fetch_jwks() -> Optional[dict]:
    """Fetch JWKS from Keycloak with TTL-based caching."""
    global _jwks_cache, _jwks_cache_time
    now = time.time()

    if _jwks_cache and (now - _jwks_cache_time) < JWKS_TTL_SECONDS:
        return _jwks_cache

    with _jwks_lock:
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
            return _jwks_cache


def _get_rsa_public_key(token: str):
    """Extract the RSA public key from JWKS matching the token's kid header."""
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

    Extracts:
    1. Client-specific roles from resource_access → {CLIENT_ID} → roles
    2. Tenant roles from resource_access → tenant_XXX → roles
       formatted as TENANT_{XXX}_{ROLE}
    3. Adds USER if any tenant roles were found (mirrors Java logic)
    4. Prefixes all roles with ROLE_
    """
    roles: List[str] = []
    resource_access = payload.get("resource_access", {})

    if KEYCLOAK_CLIENT_ID and KEYCLOAK_CLIENT_ID in resource_access:
        client_roles = resource_access[KEYCLOAK_CLIENT_ID].get("roles", [])
        roles.extend(client_roles)

    tenant_roles_found = False
    for key, value in resource_access.items():
        if key.startswith(TENANT_PREFIX):
            tenant_name = key[len(TENANT_PREFIX):].upper()
            tenant_role_list = value.get("roles", [])
            if tenant_role_list:
                tenant_roles_found = True
                for role in tenant_role_list:
                    roles.append(f"TENANT_{tenant_name}_{role}")

    if tenant_roles_found:
        roles.append("USER")

    return [f"ROLE_{r}" if not r.startswith("ROLE_") else r for r in roles]


# ═════════════════════════════════════════════════════════════════════════════
# Team Roles — mirrors AuthUtils.getTeamPolicies()
# ═════════════════════════════════════════════════════════════════════════════

def extract_team_roles(payload: dict) -> List[TeamRole]:
    """
    Python equivalent of AuthUtils.getTeamPolicies().

    Parses the 'team_roles' JWT claim into TeamRole objects.

    JWT claim structure (set by Keycloak mapper):
    [
      {
        "id": "uuid-team-1",
        "policyList": [
          {"resource": "Requirements", "authorized": true,  "actions": ["View", "Create"]},
          {"resource": "Test Cases",   "authorized": true,  "actions": ["View"]},
          {"resource": "Projects",     "authorized": false, "actions": ["Delete"]}
        ]
      }
    ]
    """
    raw = payload.get("team_roles", [])
    if not raw:
        return []

    result = []
    for item in raw:
        policies = [
            Policy(
                resource=p.get("resource", ""),
                authorized=bool(p.get("authorized", False)),
                actions=list(p.get("actions", [])),
            )
            for p in item.get("policyList", [])
        ]
        result.append(TeamRole(id=str(item.get("id", "")), policyList=policies))
    return result


# ═════════════════════════════════════════════════════════════════════════════
# Team Permission Evaluator — mirrors TeamPermissionEvaluator.java
# ═════════════════════════════════════════════════════════════════════════════

def has_permission(team_id: str, resource: str, action: str, user: dict) -> bool:
    """
    Python equivalent of TeamPermissionEvaluator.hasPermission(Serializable, String, Object).

    Called as the Python equivalent of:
        @PreAuthorize("hasPermission(#teamId, 'Requirements', 'View')")

    Evaluation order (mirrors Java exactly):
    1. ROLE_ADMIN or ROLE_INTEGRATION       → always True
    2. ROLE_TENANT_{ID}_ADMIN               → always True
    3. 'Owner' policy on the target team    → True
    4. Deny-first: authorized=False match   → False (short-circuits)
    5. Allow: authorized=True match         → True
    6. ROLE_SHARED fallback                 → True
    """
    roles: List[str] = user.get("roles", [])
    team_roles: List[TeamRole] = user.get("team_roles_parsed", [])

    # 1. Global admin / integration bypass
    if "ROLE_ADMIN" in roles or "ROLE_INTEGRATION" in roles:
        return True

    # 2. Tenant admin bypass
    tenant_id = user.get("tenant_id", "")
    if tenant_id and f"ROLE_TENANT_{tenant_id.upper()}_ADMIN" in roles:
        return True

    # 3. Owner policy on the specific target team
    for tr in team_roles:
        if str(tr.id) == str(team_id):
            for p in (tr.policyList or []):
                if p.resource == "Owner":
                    return True

    # 4 & 5. Policy evaluation for the target team (deny-first)
    authorized = False
    for tr in team_roles:
        if str(tr.id) != str(team_id):
            continue
        for p in (tr.policyList or []):
            if p.resource == resource and action in p.actions:
                if not p.authorized:
                    return False  # explicit deny — short-circuit (mirrors Java)
                authorized = True

    # 6. ROLE_SHARED fallback (mirrors Java atomic authorized.set(true) for ROLE_SHARED)
    if not authorized and "ROLE_SHARED" in roles:
        return True

    return authorized


# ═════════════════════════════════════════════════════════════════════════════
# is_team_authenticated — mirrors AuthUtils.isTeamAuthenticated()
# ═════════════════════════════════════════════════════════════════════════════

def is_team_authenticated(team_id: str, user: dict) -> bool:
    """
    Python equivalent of AuthUtils.isTeamAuthenticated().

    Returns True if:
    - User is ROLE_ADMIN, ROLE_INTEGRATION, or ROLE_SHARED, OR
    - User is tenant admin for the current tenant, OR
    - User's team_roles_parsed list contains an entry matching team_id
    """
    roles: List[str] = user.get("roles", [])

    if any(r in roles for r in ("ROLE_ADMIN", "ROLE_INTEGRATION", "ROLE_SHARED")):
        return True

    tenant_id = user.get("tenant_id", "")
    if tenant_id and f"ROLE_TENANT_{tenant_id.upper()}_ADMIN" in roles:
        return True

    team_roles: List[TeamRole] = user.get("team_roles_parsed", [])
    return any(str(tr.id) == str(team_id) for tr in team_roles)


# ═════════════════════════════════════════════════════════════════════════════
# FastAPI Dependencies
# ═════════════════════════════════════════════════════════════════════════════

async def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Security(_bearer),
) -> dict:
    """
    FastAPI dependency — equivalent to WebSecurityConfig.securityFilterChain().

    Validates the Bearer JWT, extracts roles and team_roles from the token.
    Returns the decoded payload with added 'roles' and 'team_roles_parsed' keys.
    """
    if request.url.path in PUBLIC_PATHS:
        return {"public": True, "roles": [], "team_roles_parsed": []}

    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header missing",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials

    try:
        rsa_key = _get_rsa_public_key(token)
        payload = jwt.decode(
            token,
            rsa_key,
            algorithms=["RS256"],
            issuer=ISSUER_URL,
            options={"verify_aud": False, "verify_exp": True, "verify_iss": True},
        )

        payload["roles"] = extract_roles(payload)
        payload["team_roles_parsed"] = extract_team_roles(payload)

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
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token has expired")
    except jwt.InvalidIssuerError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token issuer")
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
    2. User JWT has matching ROLE_TENANT_{ID}_* or ROLE_ADMIN/INTEGRATION/SHARED

    Returns user dict with 'tenant_id' key added.
    """
    if user.get("public"):
        return user

    if not x_tenant_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing required header: X-TENANT-ID",
        )

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


async def get_team_user(
    team_id: str = Path(...),
    user: dict = Depends(get_tenant_user),
) -> dict:
    """
    FastAPI dependency — equivalent of @PreAuthorize("isTeamAuthenticated(#teamId)").

    Validates that the authenticated user has any role on the requested team
    (or is admin/integration/shared). Mirrors AuthUtils.isTeamAuthenticated().

    Use this on routes that follow the /teams/{team_id}/... URL pattern.
    Returns user dict with 'team_id' key added.
    """
    if user.get("public"):
        return user

    if not is_team_authenticated(team_id, user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"No access to team '{team_id}'",
        )

    user["team_id"] = team_id
    return user


# ═════════════════════════════════════════════════════════════════════════════
# Service-to-Service Token — Client Credentials Grant
# ═════════════════════════════════════════════════════════════════════════════

_service_token: Optional[str] = None
_service_token_expiry: float = 0.0
_token_lock = threading.Lock()


def get_service_token() -> Optional[str]:
    """
    Obtain a service account token via Keycloak Client Credentials Grant.
    Token is cached and auto-refreshed 30 seconds before expiry.
    Used by java_client.py for service-to-service calls to the Java backend.
    """
    global _service_token, _service_token_expiry

    if not KEYCLOAK_CLIENT_ID or not KEYCLOAK_CLIENT_SECRET:
        logger.warning("KEYCLOAK_CLIENT_ID or KEYCLOAK_CLIENT_SECRET not set — skipping service token")
        return None

    now = time.time()
    if _service_token and (now < _service_token_expiry - 30):
        return _service_token

    with _token_lock:
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

            logger.info("Service token obtained (expires in %ds)", data.get("expires_in", 300))
            return _service_token

        except Exception as e:
            logger.error("Failed to obtain service token: %s", e, exc_info=True)
            return _service_token
