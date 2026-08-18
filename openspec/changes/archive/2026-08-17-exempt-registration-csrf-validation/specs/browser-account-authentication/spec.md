## MODIFIED Requirements

### Requirement: Browser mutation protection
The system SHALL protect browser-authenticated unsafe requests with CSRF
validation. It SHALL issue secure cookies in production and allow non-secure
cookies only in the explicitly configured development environment. The public
account login and public account registration endpoints SHALL be exempt from
CSRF validation because they do not require an existing browser session.

#### Scenario: Cross-site mutation lacks CSRF proof
- **WHEN** a browser session submits an unsafe request without valid CSRF proof
- **THEN** the system SHALL reject it before mutating state

#### Scenario: Public registration with no browser session
- **WHEN** an unauthenticated client submits a valid account registration request
- **THEN** the system SHALL process registration without requiring a CSRF cookie or `X-S3MP-CSRF` header

#### Scenario: Public registration with stale browser cookies
- **WHEN** a client submits a valid account registration request while carrying a stale account or tenant session cookie
- **THEN** the system SHALL not reject the request solely because CSRF proof is absent for that public registration endpoint

#### Scenario: Authenticated account mutation remains protected
- **WHEN** a browser session submits logout, tenant selection, platform management, or another unsafe authenticated request without the CSRF proof for its security domain
- **THEN** the system SHALL reject the request before mutating state
