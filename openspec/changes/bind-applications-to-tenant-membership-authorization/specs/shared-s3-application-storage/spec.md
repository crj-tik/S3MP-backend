## MODIFIED Requirements

### Requirement: Application-owned storage namespace
每个 active 应用 SHALL 拥有一个租户内唯一且稳定的逻辑存储命名空间。命名空间 SHALL 绑定 tenant_id 和 application_id，并 SHALL 在应用生命周期内保持稳定；应用重命名不得隐式改变已存在对象的物理 Key。应用的授权代表 Membership、storage space、namespace 和 API Key SHALL 必须属于同一 tenant_id；解析授权代表不得改变或跨越应用命名空间。

#### Scenario: Application namespace is derived
- **WHEN** 应用请求访问相对路径 `reports/2026.xlsx`
- **THEN** 系统 SHALL 从 application principal、其同租户授权代表和数据库绑定推导该应用命名空间，再生成完整对象目标

#### Scenario: Cross-tenant representative is supplied
- **WHEN** 应用绑定或请求解析使用其他租户的 Membership、storage space 或 namespace
- **THEN** 系统 SHALL 返回拒绝结果且不得访问或探测目标对象

#### Scenario: Cross-application identifier is supplied
- **WHEN** 应用 API Key 请求另一个应用的 storage space 或 namespace
- **THEN** 系统 SHALL 返回 `403 permission_denied`，且不得访问或探测目标对象
