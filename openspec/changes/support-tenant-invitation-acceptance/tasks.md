## 1. Inspect and extend account-context contracts

- [x] 1.1 Locate the auth routes, AccountContext DTO/serializer, Membership model/repository, and existing account CSRF/auth dependencies.
- [x] 1.2 Update `GET /api/v1/auth/me` serialization and queries to return active and invited memberships with `membership_id` and `membership_status` while preserving existing tenant fields.

## 2. Implement invitation acceptance

- [x] 2.1 Add `POST /api/v1/auth/tenant-invitations/{membership_id}/accept` under account authentication and account-domain CSRF protection.
- [x] 2.2 Implement ownership, invited/expiry validation, atomic idempotent `invited` → `active` transition, and stable invalid-membership errors.
- [x] 2.3 Return the updated AccountContext from the acceptance endpoint without creating a tenant session.

## 3. Verify behavior and documentation

- [x] 3.1 Add route/service tests for successful acceptance, repeated acceptance, foreign/missing/ineligible memberships, CSRF failure, and concurrent/idempotent updates.
- [x] 3.2 Add `/auth/me` contract tests covering active and invited entries and tenant selection rejection for invited memberships.
- [x] 3.3 Update API schema/documentation and run the focused test suite plus relevant lint/type checks.
