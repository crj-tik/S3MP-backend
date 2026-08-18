## ADDED Requirements

### Requirement: Platform audit events support resource filters
The platform audit-event list SHALL support optional `resource_type` and
`resource_id` filters in addition to the existing action filter. All supplied
filters SHALL be combined with logical AND, and the endpoint SHALL remain
protected by the platform audit read permission and return only the established
safe audit projection.

#### Scenario: Operator opens a tenant's audit history
- **WHEN** an authorized operator requests audit events with the tenant resource type and identifier
- **THEN** the API SHALL return only audit events for that exact resource

#### Scenario: Resource filters are combined with action
- **WHEN** an operator supplies `resource_type`, `resource_id`, and `action`
- **THEN** the API SHALL return only events matching all three values
