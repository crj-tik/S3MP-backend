## Purpose

为异步 copy、move 与 delete 文件操作提供可恢复、可审计且不会绕过当前授权的持久化执行能力，使已接受请求能在故障、重启和撤权竞态后收敛到明确终态。

## ADDED Requirements

### Requirement: Durable file-operation execution
系统 SHALL 为已接受的 copy、move 和 delete 请求持久化执行所需的 canonical 源/目标、acting principal、授权版本、幂等身份、尝试次数、结果和状态。独立执行者 SHALL 领取待执行记录，并且同一记录在同一时间不得被多个执行者产生冲突性副作用。

#### Scenario: 同一操作被重复领取
- **WHEN** 多个执行者同时尝试领取同一个 pending 或已过期 lease 的文件操作
- **THEN** 系统 SHALL 只允许一个有效 lease 持有者执行该尝试，其他执行者不得产生对象存储副作用

### Requirement: Retry and terminal outcomes
系统 SHALL 对暂时性 provider 或数据库故障安排有限、可观测的重试；对不可恢复验证、授权或输入错误 SHALL 记录终态。move 在目标已验证但源删除失败时 SHALL 记录 partial_failure，且不得将其报告为 succeeded。

#### Scenario: 暂时性对象存储故障
- **WHEN** worker 因可重试的对象存储故障无法完成文件操作
- **THEN** 系统 SHALL 记录 retry_wait、下一次尝试时间和脱敏错误原因

#### Scenario: 重试次数耗尽
- **WHEN** 文件操作达到配置的最大重试次数
- **THEN** 系统 SHALL 记录 failed 终态和可审计错误原因，且不得继续无限重试

### Requirement: Execution-time authorization
在执行每个对象副作用前，系统 SHALL 以持久化的操作语义重新授权当前 acting principal。任何主体状态、API Key、授权版本、scope、storage space 或 canonical prefix 的不匹配 SHALL 阻止执行并形成可审计终态。

#### Scenario: 原权限已失效
- **WHEN** 文件操作创建后其当前授权不再允许源读、目标写或源删除
- **THEN** 执行者 SHALL 将操作记录为 cancelled 或 failed，且不得执行对应对象副作用
