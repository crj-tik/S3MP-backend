## ADDED Requirements

### Requirement: Development browser origin configuration
The local runtime SHALL accept an explicit allowlist of development browser
origins and, when credentials are enabled, SHALL return exact allowed origins
rather than a wildcard. Production configuration MUST reject insecure cookie
transport and unrestricted credentialed origins.

#### Scenario: Local frontend sends credentialed request
- **WHEN** a configured development origin sends a credentialed browser request
- **THEN** the API SHALL return the matching allowed origin and credential headers
