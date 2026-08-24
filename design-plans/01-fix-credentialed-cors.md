# Restore Default Frontend-to-API Connectivity

Written against: `02932a6981347cf60d722f6cb47743ddc1c92f0f`

## Evidence chain

- Surface: the static workbench in `ui/index.html` calling the FastAPI service through the configured `API_BASE`.
- Problem: every request made by `apiRequest()` uses `credentials: "include"`, while the backend development default uses `THESIS_CORS_ORIGINS="*"` and disables credentialed CORS for that value. Browsers reject the wildcard `Access-Control-Allow-Origin` response when credentials mode is enabled, so the initial task list appears empty even though the API returns tasks.
- Design evidence: `DESIGN.md` defines the product as a usable paper-writing workbench whose task, conversation, and knowledge-base context must load together. A default local launch that cannot load any API data violates that contract before the user reaches the workflow.
- Owner: backend CORS policy in `backend/application/main.py`; request consumer in `ui/index.html`; environment documentation in `backend/.env.example` and `README.md`.
- Scope and affected surfaces: local static UI development, cookie-capable authentication, preflight responses, documented deployment configuration, and security tests. Do not broaden this into a general authentication redesign.
- Uncertainty: production origins vary by deployment and must remain explicitly configurable. If the production UI is always reverse-proxied under the API origin, the development allowlist is still needed for the documented standalone static server workflow.

## Design decision

Use an explicit local-origin allowlist as the backend's unauthenticated development default instead of `*`. Include both `http://127.0.0.1:8787` and `http://localhost:8787`, and enable credentials for parsed explicit origins. Preserve `THESIS_CORS_ORIGINS` as the production override and preserve the existing fail-fast rule that rejects wildcard CORS when authentication is enabled.

Do not remove `credentials: "include"` from frontend requests: the same request path must support authenticated cookie sessions, and conditionally changing credentials would create divergent anonymous and authenticated behavior.

## Reuse

- Reuse the existing comma-separated `THESIS_CORS_ORIGINS` parser in `backend/application/main.py`.
- Reuse the existing application factory and security-test fixtures rather than creating a parallel CORS configuration layer.
- Reuse the documented local UI port `8787`; do not introduce a new development server or proxy.

## Changes

1. In `backend/application/main.py`, replace the wildcard development default with the two explicit local UI origins. Keep trimming and filtering comma-separated values. Set `allow_credentials` for explicit origins and keep the authenticated wildcard validation intact.
2. In `backend/.env.example`, document the local default and show that deployed environments must list their real frontend origins explicitly.
3. Add focused tests under `tests/` that create the app with the default local policy and verify:
   - a preflight from `http://127.0.0.1:8787` receives that exact allow-origin value;
   - credential support is present;
   - an unlisted origin is not granted CORS access;
   - authenticated mode still refuses a wildcard origin.
4. After the behavior is accepted, update `README.md` with the corrected local-start expectation and the production-origin configuration rule.

## Scope

- In: backend CORS defaults, related environment documentation, focused automated tests, and the README stage record.
- Out: changing cookie attributes, replacing the authentication model, adding a reverse proxy, or supporting arbitrary origins with credentials.

## Validation

- Start the API with its default development environment and serve `ui/` at `http://127.0.0.1:8787`; confirm the session list loads without a browser CORS error.
- Repeat from `http://localhost:8787`.
- Inspect an OPTIONS response and confirm the exact requesting local origin and credential header are returned.
- Run the focused security/CORS tests, then the full Python test suite.
- Run the repository's frontend syntax/static checks to confirm no unrelated UI regression.

## Stop conditions

- Stop and revisit the decision if the supported local UI port is not `8787` in the project's launch contract.
- Stop if authentication is changed from cookie-capable requests to a deliberately credential-free transport; that would change the correct CORS design.
- Do not accept a fix that combines wildcard allow-origin with credentials.

## Design documentation

No `DESIGN.md` change is expected: this restores the existing workbench contract rather than changing the visual language or interaction model. Record only the operational configuration in `README.md` and `backend/.env.example` after acceptance.
