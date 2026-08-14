## 1. Canonical documentation metadata

- [x] 1.1 Define the canonical Chinese glossary for reusable identifiers, headers, pagination fields, authentication contexts, and common schema properties.
- [x] 1.2 Define complete Chinese descriptions for all 80 public runtime operations, including authorization and mutation semantics.
- [x] 1.3 Enrich every public request and response schema property with the canonical Chinese descriptions.

## 2. Runtime and published contract integration

- [x] 2.1 Apply documentation metadata to the runtime OpenAPI schema used by Swagger without changing endpoint behavior.
- [x] 2.2 Materialize the same descriptions into `contracts/openapi.yaml` and maintain deterministic contract output.
- [x] 2.3 Add Chinese Swagger/contract guidance for cookies, CSRF, account-session versus tenant-session selection, API keys, and error envelopes.

## 3. Documentation quality gates

- [x] 3.1 Extend contract validation to require Chinese descriptions for all public operations, parameters, request properties, and response properties.
- [x] 3.2 Add regression tests proving same-name concepts retain identical descriptions across endpoints and runtime equals the checked-in contract.
- [ ] 3.3 Run format, type, contract, full test, and live Swagger endpoint verification; document the frontend handoff version.

## 4. CSRF security-domain reconciliation

- [ ] 4.1 Select the CSRF cookie by account-control-plane versus tenant-scoped route, including the case where both sessions coexist.
- [ ] 4.2 Add regression coverage for tenant and account mutations with both session cookies, and verify missing/wrong tokens remain rejected.
- [ ] 4.3 Verify local HTTP cookie security configuration and update runtime/published Chinese documentation for the two CSRF domains.
- [ ] 4.4 Run format, type, focused/full tests, materialized OpenAPI, contract checks, and live endpoint verification where infrastructure is available.
