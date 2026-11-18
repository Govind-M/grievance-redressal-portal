# Authentication — Phase 2

Implemented backend only. The frontend still has development placeholders. Citizen grievance
APIs were added in Phase 3; CMO/officer lifecycle APIs are implemented in Phase 4. AI and uploads remain deferred.
This remains a recruitment demonstration prototype.

## Setup and secrets

From backend, install requirements-dev.txt, configure backend/.env, run alembic upgrade head,
seed, then start Uvicorn. The existing database uses synchronous Psycopg/SQLAlchemy throughout.

Generate JWT_SECRET_KEY once with:
```powershell
.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(48))"
```

Store that generated value in backend/.env (ignored by Git) or your hosting secret manager.
Do not put it in VITE_* variables. Keep it identical across workers/restarts. The application never
generates a signing secret automatically. Changing it intentionally invalidates existing JWTs.
At least 32 bytes and reasonable character diversity are required; common placeholders are rejected.

Set all three SEED_*_PASSWORD variables (12–128 characters). The seed emails remain the Phase 1
fictional identities: citizen@example.test, cmo@example.test, officer@example.test. No real government
identity is implied. Default seeding preserves existing password hashes. Unknown Phase 1 demo
passwords can be explicitly reset, only in development:
```powershell
.venv\Scripts\python.exe -m scripts.seed --reset-demo-passwords
```
This changes only those three existing demo users, checks their expected active role/department,
revokes their sessions and preserves other application data. It never grants a new role to an
existing conflicting account. Production/test environments reject the reset flag.

Defaults are 15-minute access tokens and 7-day refresh sessions. Production requires
APP_ENV=production, a strong configured key, AUTH_COOKIE_SECURE=true and HTTPS CORS/trusted origins.
Missing keys leave health checks available in development but login/protected auth returns 503.
Keep APP_DEBUG false for deployed environments; API errors never expose stack traces.

## JWT and session lifecycle

Both tokens carry sub (user UUID), sid (session UUID), independent 256-bit random hexadecimal jti,
type (access/refresh), integer iat/nbf/exp NumericDates, configured iss and aud.
HS256 is the only permitted algorithm. Signature, issuer, audience, all required claims,
UUID formats, NumericDate types/order, expiry/not-before and explicit token type are validated.
Role values are never taken from the JWT.

Each successful login creates one user_sessions row. Access is returned in JSON and sent by the
client as Authorization: Bearer. Refresh is delivered only via an HttpOnly cookie.
The server stores the SHA-256 refresh JTI digest, not the JWT or raw identifier.

Every protected request loads the current active database user AND checks the session's ownership,
revocation/expiration and any targeted revoked-token entry. Signature-only authentication is never
used. Invalid/inactive/revoked sessions return 401 with WWW-Authenticate: Bearer. Expired access
rejection does not clear the refresh cookie: the client may still be able to refresh.

Refresh rotates both tokens, records the consumed refresh JTI digest and replaces the current
digest atomically while holding PostgreSQL row locks. It does not extend the original session's
absolute seven-day lifetime. Access lifetime is clipped to remaining session lifetime near expiry.
A previous access JWT remains valid after normal rotation until expiry or session revocation.

A consumed/mismatched valid refresh JWT triggers session revocation with refresh_token_reuse.
That revocation is committed before the 401 is raised. Two simultaneous requests cannot both
rotate the same token: one may succeed, then the stale request revokes the whole session, including
the newly issued token pair. Clients must serialize refresh requests; there is no stale-token grace.

Logout revokes only its authenticated session, clears the cookie and returns 204.
Subsequent use of its access/refresh tokens returns 401 immediately. Repeated logout returns 401.
Other device sessions remain valid; logout-all revokes all sessions of the current user only.
The latter serializes with login through a user row lock.

revoked_tokens records consumed refresh identifiers (and supports optional individual access-token
revocation); ordinary logout uses session revocation instead of blacklisting every access JWT.
Expiry indexes support later cleanup. Phase 2 does not schedule a cleanup worker.

```mermaid
sequenceDiagram
    participant C as Client
    participant A as FastAPI
    participant P as PostgreSQL
    C->>A: Login JSON + trusted Origin
    A->>P: Verify active user / Argon2id, create session
    P-->>A: Commit session and refresh JTI hash
    A-->>C: Access JWT + CSRF token + safe user; HttpOnly refresh cookie
    C->>A: Protected request + access Bearer JWT
    A->>P: Load current user, verify active owned session
    A-->>C: Safe response (or 401/403)
    C->>A: Refresh cookie + trusted Origin + X-CSRF-Token
    A->>P: Lock user/session; inspect current/consumed JTI hashes
    alt Current unused refresh
        A->>P: Record consumed hash, replace hash, commit
        A-->>C: New access JWT + new refresh cookie
    else Consumed/stale refresh
        A->>P: Revoke session and COMMIT
        A-->>C: 401, clear refresh cookie
    end
    C->>A: Logout + access JWT + trusted Origin + CSRF proof
    A->>P: Lock session, revoke and commit
    A-->>C: 204 + delete cookie
```

## Cookies, CORS and CSRF

AUTH_COOKIE_NAME defaults to cmk_refresh_token. HttpOnly is unconditional.
Path defaults to /api/v1/auth. Domain defaults to absent (host-only).
Expiration/max-age follow the absolute session expiry. Deletion uses identical path/domain/flags.
Development may use Secure=false on HTTP localhost; production refuses it.
SameSite=lax is the default for same-site deployments. Truly cross-site deployments can configure
SameSite=none only with Secure=true. Choose the policy for the actual frontend/backend sites.
Use consistent localhost hostnames in development; localhost and 127.0.0.1 are different sites.

Credential-aware CORS uses explicit CORS_ORIGINS; wildcard configuration is rejected.
Future browser requests that need refresh cookies must use credentials/include or Axios withCredentials.
No frontend token persistence or auth interceptors were added in Phase 2.

Every POST auth endpoint requires a present Origin exactly matching AUTH_TRUSTED_ORIGINS.
Missing, null, path-suffixed, spoofed-suffix and untrusted origins fail closed (403).
CLI examples must deliberately supply an Origin. There is no permissive Referer/Host fallback.

Refresh/logout/logout-all additionally require X-CSRF-Token containing the session-bound HMAC
returned as csrf_token at login/refresh. It is derived with a domain-separated signing-key HMAC,
cannot be substituted across sessions, and stays stable during rotation. It is not an authentication
token: logout still requires an access JWT and refresh still requires the signed HttpOnly refresh.
Keeping this proof in client memory is sufficient; there is no JavaScript-readable refresh cookie.
This strategy combines exact trusted-origin checks with a cryptographic CSRF token/custom header,
including SameSite=None deployments. See the
[OWASP CSRF guidance](https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html).

Profile PATCH uses only the explicitly supplied Bearer token, not cookie authentication.
All auth/profile responses use no-store; validation errors omit raw input to avoid password reflection.
Request bodies, JWTs, hashes and signing keys are not logged. Configuration errors hide input values.

Swagger's authorization control supports access Bearer JWTs. To use state-changing Try-it-out from
/docs locally, explicitly include the API's own origin in AUTH_TRUSTED_ORIGINS; otherwise use the
requests below with the configured frontend Origin. Do not loosen origins to a wildcard.

## Roles and future assignment services

get_auth_context/get_current_user/get_current_active_user enforce active DB user/session.
require_roles, require_citizen, require_cmo_admin and require_department_officer check current DB roles.
Unauthenticated requests return 401; insufficient permissions return 403.
Test-only role probe endpoints exist only in tests, not the production router.

Assignment helpers operate on loaded models within a future service's database session:
is_active_department_officer, officer_belongs_to_department, is_designated_officer,
may_view_assignment, may_modify_assignment and require_assignment_permission.
They require active user/department, matching department and an open assignment.
A department-only assignment is modifiable by its active officers. A designated assignment remains
viewable by same-department colleagues, but modifiable only by the designated officer.
Unrelated departments and closed assignments are denied. CMO access is handled with the CMO role
dependency by future services; these officer-specific helpers do not implicitly grant admin bypass.
Future mutations still need transactional ownership/assignment/state-transition checks.

## Exact local API walkthrough (PowerShell)

Start the configured backend first:
```powershell
Set-Location backend
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.venv\Scripts\python.exe -m alembic upgrade head
.venv\Scripts\python.exe -m scripts.seed
.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

In another PowerShell terminal:
```powershell
$api = 'http://localhost:8000/api/v1'
$origin = @{ Origin = 'http://localhost:5173' }
$securePassword = Read-Host 'Choose a local test password (12-128 characters)' -AsSecureString
$password = [System.Net.NetworkCredential]::new('', $securePassword).Password
$email = 'walkthrough-' + [guid]::NewGuid().ToString('N') + '@example.test'

# Register: returns a safe citizen profile, HTTP 201.
$registration = @{
    name = 'Fictional Walkthrough Citizen'; email = $email
    mobile_number = '+919876543210'; password = $password
} | ConvertTo-Json
Invoke-RestMethod "$api/auth/register" -Method Post -Headers $origin -ContentType application/json -Body $registration

# Login: keep token JSON in memory and let the session capture the HttpOnly cookie.
$browserSession = New-Object Microsoft.PowerShell.Commands.WebRequestSession
$credentials = @{ email = $email; password = $password } | ConvertTo-Json
$auth = Invoke-RestMethod "$api/auth/login" -Method Post -Headers $origin -ContentType application/json -Body $credentials -WebSession $browserSession

# Protected profile.
$headers = @{ Authorization = 'Bearer ' + $auth.access_token }
Invoke-RestMethod "$api/auth/me" -Headers $headers
Invoke-RestMethod "$api/users/me" -Method Patch -Headers $headers -ContentType application/json -Body '{"name":"Updated Fictional Citizen"}'

# Refresh rotates the cookie automatically; no refresh JWT is read from JSON.
$refreshHeaders = @{ Origin = $origin.Origin; 'X-CSRF-Token' = $auth.csrf_token }
$auth = Invoke-RestMethod "$api/auth/refresh" -Method Post -Headers $refreshHeaders -WebSession $browserSession

# Logout revokes this session and clears its cookie.
$headers = @{
    Origin = $origin.Origin; Authorization = 'Bearer ' + $auth.access_token
    'X-CSRF-Token' = $auth.csrf_token
}
Invoke-RestMethod "$api/auth/logout" -Method Post -Headers $headers -WebSession $browserSession

# Expected HTTP 401: the access JWT signature is valid, but its session is revoked.
try {
    Invoke-RestMethod "$api/auth/me" -Headers @{ Authorization = 'Bearer ' + $auth.access_token }
} catch {
    Write-Output ('Expected rejection: HTTP ' + [int]$_.Exception.Response.StatusCode)
}
# Expected HTTP 401: logout removed the refresh cookie.
try {
    Invoke-RestMethod "$api/auth/refresh" -Method Post -Headers $refreshHeaders -WebSession $browserSession
} catch {
    Write-Output ('Expected refresh rejection: HTTP ' + [int]$_.Exception.Response.StatusCode)
}
```

Use /auth/logout-all instead of /auth/logout to revoke every session for that user.
Do not print token objects or paste real secrets into issue reports. These requests create a new
fictional citizen in the chosen local development database.

## Verification and boundaries

Run python -m pytest -q with TEST_DATABASE_URL pointing to an empty dedicated *_test database.
The suite covers real migrations, data preservation, registration races, refresh row-lock races,
replay commit behavior, rollback on rotation failure, logout/all-device isolation, strict claims,
roles, safe profiles, CSRF, cookie flags and demo compatibility. No SQLite substitutes are used.

The original migration is unchanged. No frontend UI, CMO/officer mutation endpoints, JWT-in-browser storage,
email verification/reset, AI, file uploads, production deployment or external identity provider
is implemented. Deployment-level abuse throttling and expired-record maintenance remain deployment/
later-phase work. See 06_Setup_and_Testing.md for executed checks and limitations.

