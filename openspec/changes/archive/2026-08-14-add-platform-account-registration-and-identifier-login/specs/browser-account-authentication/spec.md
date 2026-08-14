## MODIFIED Requirements

### Requirement: Account authentication supports two identifiers

The account login contract SHALL use `identifier` as the canonical input label and SHALL document that it accepts either email or company employee number. Existing email clients SHALL have a bounded compatibility path during the frontend migration, with conflicting `identifier` and legacy `email` values rejected.

#### Scenario: Account session is independent from tenant selection

- **WHEN** login succeeds with either identifier
- **THEN** the response SHALL establish only the account session and SHALL require the existing tenant-selection operation before tenant data APIs can be used
