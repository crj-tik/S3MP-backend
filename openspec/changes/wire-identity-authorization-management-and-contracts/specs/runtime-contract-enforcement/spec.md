## MODIFIED Requirements

### Requirement: Runtime operation coverage
The service SHALL register exactly one authenticated or explicitly public runtime route for every OpenAPI operationId in the published `/api/v1` contract, and SHALL fail contract verification when a declared operation is missing or a registered public operation is undeclared. Verification SHALL additionally require contract-declared protected operations to execute successfully through the production dependency graph under a real database-backed application lifecycle.

#### Scenario: Declared operation is absent
- **WHEN** contract verification finds an operationId without a registered runtime route
- **THEN** verification SHALL fail and identify the missing operationId

#### Scenario: Registered management route lacks production service
- **WHEN** a contract-declared identity or authorization management route has no executable production service dependency
- **THEN** lifecycle integration verification SHALL fail before release

### Requirement: Application-service execution boundary
Public routers SHALL only translate HTTP input and output; an application service receiving PrincipalContext SHALL perform tenant resource resolution, authorization, mutation semantics, and external-operation coordination. Public routers MUST NOT directly access ORM persistence or object storage. Router response models SHALL be strict contract projections rather than untyped persistence payloads.

#### Scenario: A file mutation is requested
- **WHEN** a client invokes a file mutation endpoint
- **THEN** the router SHALL delegate to an application service that performs authorization, persistence, and storage coordination before returning the contract response

#### Scenario: 身份管理资源被读取
- **WHEN** 客户端请求用户、成员、组、角色、角色绑定或授权解释资源
- **THEN** 路由 SHALL 委派给接收 PrincipalContext 的应用服务，并以声明的严格响应 DTO 返回结果
