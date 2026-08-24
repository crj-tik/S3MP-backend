## 1. Contract and persistence model

- [x] 1.1 Define application API and browser data-plane route families in OpenAPI, including required application-code actor input and stable error responses.
- [x] 1.2 Add durable target-application and actor-application/user attribution fields to audits, upload intents, multipart sessions, and object operations; create and test migrations/backfill behavior.
- [x] 1.3 Update API documentation and generated frontend types to distinguish target application from audit actor.

## 2. Backend application API behavior

- [x] 2.1 Remove the temporary code-as-target and key-only data-plane behaviors that conflict with the approved model.
- [x] 2.2 Resolve application API target storage exclusively from the authenticated API Key and resolve request application_code as an active actor application in the same tenant.
- [x] 2.3 Enforce Key scopes and target application lifecycle without requiring the actor application to own or be authorized for the target directory.
- [x] 2.4 Persist and revalidate actor/target attribution for direct uploads, downloads, multipart flows, file deletion, and asynchronous object operations.
- [x] 2.5 Return a non-enumerating rejection for missing, inactive, or cross-tenant actor codes before any object-storage access.

## 3. Browser behavior

- [x] 3.1 Restore browser file endpoints that use internal application_id to select the target application and reject API Key credentials on those endpoints.
- [x] 3.2 Preserve current authenticated-user authorization and record the human user as the browser operation actor.
- [x] 3.3 Update frontend file pages and mocks to use only the browser application-ID route family.

## 4. Verification

- [x] 4.1 Add backend unit and HTTP tests for same-tenant cross-application API Key use, invalid actor code, cross-tenant actor code, and Key scope denial.
- [x] 4.2 Add end-to-end coverage for target namespace selection and actor/target audit attribution across upload, download, delete, multipart, and object-operation workflows.
- [x] 4.3 Add browser route tests proving application_id selects the target and the logged-in user is audited.
- [x] 4.4 Regenerate and validate OpenAPI/frontend types; run backend migrations, targeted test suites, frontend typecheck, lint, and tests.
