## Purpose

将应用 API Key 所代表的目标资源与请求声明的操作应用分离，使同租户应用协作可审计而不暴露内部应用标识。

## ADDED Requirements

### Requirement: Application API requests declare an audit actor
应用 API Key 的文件、上传、下载、删除、对象操作和 multipart 请求 SHALL 携带 `application_code`。系统 SHALL 在 API Key 所属租户内解析该 code 为 active 操作应用，并将其作为审计主体；该 code MUST NOT 选择 API Key 的目标存储命名空间。

#### Scenario: Another application acts with a target application's key
- **WHEN** 应用 A 使用应用 B 的有效 API Key，并携带同租户 active 应用 A 的 code 请求 B 的文件操作
- **THEN** 系统 SHALL 在 B 的命名空间执行经 Key scope 允许的操作，并记录 A 为操作应用、B 为目标应用

#### Scenario: Audit actor code is absent, inactive, or outside the key tenant
- **WHEN** 应用 API 请求未携带 code，或 code 在 API Key 所属租户中不存在或不是 active 应用
- **THEN** 系统 SHALL 拒绝请求且不得调用对象存储，也不得泄露其他租户是否存在该 code

### Requirement: Browser requests retain human actor attribution
浏览器管理端的数据面请求 SHALL 使用内部 `application_id` 选择目标应用，并 SHALL 以当前已认证用户或其租户主体作为审计主体。浏览器端不得通过请求参数伪造应用 API 操作主体。

#### Scenario: Browser user operates a selected application
- **WHEN** 已认证浏览器用户在已选择的应用页面上传、下载或删除文件
- **THEN** 系统 SHALL 使用请求 application_id 的命名空间，并记录该用户为操作主体
