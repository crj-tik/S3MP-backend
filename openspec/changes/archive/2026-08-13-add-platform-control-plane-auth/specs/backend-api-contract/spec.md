## ADDED Requirements

### Requirement: Authentication and platform APIs are contract-declared
The service SHALL declare login, logout, account context, tenant-session
selection, and platform tenant lifecycle operations in the published contract
before exposing them at runtime. The contract SHALL distinguish public account
authentication from account-session, tenant-session, and platform authorization.

#### Scenario: Frontend performs browser login
- **WHEN** the frontend calls the declared login operation with a supported credential payload
- **THEN** the runtime SHALL provide the declared status, cookie behavior, and stable error envelope
