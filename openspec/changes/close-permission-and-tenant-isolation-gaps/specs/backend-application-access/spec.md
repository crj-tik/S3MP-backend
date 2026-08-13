## MODIFIED Requirements

### Requirement: 应用身份与 Owner
系统 SHALL 将应用建模为独立 principal，并 SHALL 要求至少一个有效用户或用户组 Owner；Owner 失效时 SHALL 标记应用待接管而非静默删除。有效 Owner 的判断 SHALL 基于当前主体和 membership 状态，且 SHALL 在 Owner 关系变更、membership 状态变更和治理扫描时重新计算。处于待接管状态的应用及其 API Key SHALL 不得继续发起新的受保护请求，直至经授权接管恢复。

#### Scenario: 最后一个 Owner 被停用
- **WHEN** 应用最后一个有效 Owner 失效
- **THEN** 系统 SHALL 原子地标记应用待接管、阻止其 API Key 的新认证并通知租户管理员

#### Scenario: 存在已停用 Owner 记录
- **WHEN** 应用仍有 Owner 记录但所有 Owner 的 membership 或主体均已失效
- **THEN** 系统 SHALL 将该应用视为失主，而不得把 Owner 记录本身视为有效 Owner
