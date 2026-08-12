## ADDED Requirements

### Requirement: Trusted principal context for protected operations
The service SHALL derive `PrincipalContext` for protected operations only from server-verified session, API Key, or service credentials. The derived context MUST bind tenant, principal, membership, authorization version, and credential provenance; clients MUST NOT supply these values as trusted input.

#### Scenario: Request has no valid credential
- **WHEN** a caller invokes a protected file or administration operation without a usable credential
- **THEN** the service SHALL return `401 authentication_required` before resource lookup or mutation

#### Scenario: Authorization version has changed
- **WHEN** a credential was established before membership, role, or policy state advances its authorization version
- **THEN** the service SHALL reject the stale credential or re-evaluate it against the current server-side authorization state before permitting the operation

### Requirement: Resource-level file authorization evidence
For every file action, the service SHALL evaluate tenant, principal, storage space, canonical relative key, action, active role bindings, and explicit deny rules before invoking storage. It SHALL retain a non-secret authorization evidence record containing the decision, reason, matching binding identifiers, policy version, and evaluation time.

#### Scenario: Explicit deny matches a requested object
- **WHEN** a principal has an allow binding and a matching deny binding for a file action in the requested storage space or key prefix
- **THEN** the service SHALL deny the action and SHALL not invoke object storage

#### Scenario: Caller requests an out-of-scope key
- **WHEN** a principal requests a file action outside its effective storage-space or prefix scope
- **THEN** the service SHALL return `403 permission_denied` without revealing object existence
