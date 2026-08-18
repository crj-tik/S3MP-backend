## 1. Bootstrap implementation

- [x] 1.1 Add an idempotent repository operation that checks active platform administrators under a database lock and creates the configured account only when missing.
- [x] 1.2 Add a non-interactive bootstrap module with explicit development-only configuration and safe password handling.
- [x] 1.3 Add container entrypoint and Compose environment wiring; keep production disabled by default; inject bootstrap credentials only into the API service.

## 2. Validation

- [x] 2.1 Test first startup and repeated startup; validate the production/disabled guards statically and through configuration paths.
- [x] 2.2 Build and start the container entrypoint, then confirm login with the created local development administrator and stable account ID on repeated checks.
