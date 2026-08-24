## ADDED Requirements

### Requirement: Platform tenant-admin derives current-tenant authority
The authorization service SHALL treat platform `tenant-admin` as a global-user role. For a tenant request, it SHALL derive the complete tenant permission set only when the authenticated user has an ACTIVE Membership in the current tenant. It SHALL never merge Membership, RoleBinding, or permissions from another tenant.

#### Scenario: Active membership receives full tenant authority
- **WHEN** a user has platform `tenant-admin` and an ACTIVE Membership in the current tenant
- **THEN** every published non-platform tenant permission SHALL be effective for that request

#### Scenario: Missing or inactive membership is denied
- **WHEN** a user has platform `tenant-admin` but no ACTIVE Membership in the current tenant
- **THEN** the tenant request SHALL be denied and no tenant permissions SHALL be derived

#### Scenario: Cross-tenant membership is not reused
- **WHEN** a user has an ACTIVE Membership in tenant A and requests tenant B without an ACTIVE Membership there
- **THEN** tenant A's authorization SHALL not affect the decision for tenant B

#### Scenario: Revocation invalidates derived authority
- **WHEN** the platform `tenant-admin` grant expires or is revoked
- **THEN** the authorization version/cache SHALL be invalidated and subsequent checks SHALL deny derived tenant permissions

### Requirement: Tenant-local tenant-admin is not an implicit authorization source
The authorization service SHALL not treat a tenant-local role named `tenant-admin` created by legacy bootstrap logic as the source of platform tenant-admin authority. Ordinary tenant roles SHALL continue to require explicit tenant RoleBinding or group membership.

#### Scenario: Legacy tenant-admin binding is not trusted
- **WHEN** a legacy tenant-local `tenant-admin` Role or RoleBinding remains in storage
- **THEN** authorization SHALL ignore it as a platform tenant-admin grant

#### Scenario: Ordinary tenant role still requires binding
- **WHEN** a user has no platform `tenant-admin` grant and no explicit binding to a tenant role
- **THEN** the user SHALL not receive that role's permissions

### Requirement: Tenant-admin can delegate complete tenant authority
A user with platform `tenant-admin` and an ACTIVE Membership in the current
tenant SHALL be allowed to delegate any published non-platform tenant
permission, including permissions marked non-delegable for ordinary users. The
existing tenant, resource-scope, expiry, and no-self-grant constraints SHALL
still apply.

#### Scenario: Tenant-admin delegates a normally non-delegable permission
- **WHEN** a tenant-admin grants a role containing a normally non-delegable tenant permission to another principal in the current tenant
- **THEN** the binding SHALL be created when its target, scope, and expiry are valid

#### Scenario: Tenant-admin cannot self-grant
- **WHEN** a tenant-admin attempts to bind a role to its own principal
- **THEN** the request SHALL be rejected with the stable self-grant authorization error
