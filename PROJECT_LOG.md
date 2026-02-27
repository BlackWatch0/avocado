# Avocado Project Log

最后更新: 2026-02-27

## 文档说明（固定模板）
- 记录格式模板（改动历史）: `YYYY-MM-DD | 变更主题 | 文件 | 行为变化 | 风险/回滚 | TODO`
- 任务卡模板（TODO）: `ID | 标题 | 状态 | 验收标准 | 优先级 | 依赖 | 最后更新`
- 维护规则: 每次 Codex 完成代码改动后，必须同步更新本文件的「改动历史」「TODO 看板」及必要约定。

## 项目目标与范围
### 当前目标
- 短期目标: 提供可运行的 Python + Docker 常驻服务，支持 CalDAV 日历同步、AI 调度与差异审计。
- 中期目标: 提供内网 Web 管理后台，支持配置热更新、规则维护、手动触发与状态观测。

### Out of Scope（当前明确不做）
- 不实现多租户与 RBAC。
- 不接入外部企业密钥管理系统（首版使用本地配置文件）。
- 不拆分多文档体系（首阶段单文件治理）。

### 关键约束
- 技术栈: Python。
- 部署方式: Docker 常驻 daemon。
- 同步策略: 定时轮询 + 手动触发。
- 规划窗口: 按自然日计算，默认未来 7 天，可配置长度。
- 冲突策略: 用户修改优先。

## 系统约定（长期有效）
### ADR-lite（精简架构决策）
- ADR-001: 项目文档治理采用单文件 `PROJECT_LOG.md`，作为需求、演进和任务状态唯一事实源。
- ADR-002: `README.md` 保持简洁，仅作入口说明并链接本文件。
- ADR-003: 改动历史按功能/任务记录，不按每次提交流水记账。
- ADR-004: Web 后台首版仅内网使用，不启用登录认证。

### 数据与接口约定
- `[AI Task]` 模块放置于事件 `DESCRIPTION` 字段，采用结构化 YAML 块。
- `[AI Task]` 至少包含字段: `locked`、`mandatory`、`editable_fields`、`user_intent`、`updated_at`。
- 配置文件为 `config.yaml`，关键字段:
  - CalDAV: `base_url`、`username`、`password`
  - AI: `base_url`、`api_key`、`model`
  - Sync: `window_days`、`interval_seconds`、`timezone`
- 后台 API（v1）:
  - `GET /api/config`
  - `PUT /api/config`
  - `GET /api/calendars`
  - `PUT /api/calendar-rules`
  - `POST /api/sync/run`
  - `GET /api/sync/status`
  - `GET /api/audit/events`

### 兼容性与安全约束
- 敏感信息不可写入公开日志，密钥输出需要掩码。
- 行为变化若涉及接口/策略，必须同步更新本章节或「项目目标与范围」。
- 重复事件策略默认实例级处理，不修改 RRULE。

## 改动历史（按功能/任务，最新在上）
| 日期 | 变更主题 | 涉及文件 | 行为变化 | 风险与回滚点 | 关联 TODO |
| --- | --- | --- | --- | --- | --- |
| 2026-02-27 | 新增无登录管理页面与配置编辑能力 | `avocado/web_admin.py`, `avocado/templates/admin.html`, `avocado/static/admin.css`, `avocado/static/admin.js`, `tests/test_web_admin.py`, `README.md` | 新增根路径管理页面（`/`）、新增 `GET /api/config/raw`、增强 `PUT /api/config` 密钥保留逻辑（空值或 `***` 不覆盖），支持页面保存配置与手动触发同步 | 风险中等；若页面交互异常可继续通过现有 API 运维，回滚可移除前端路由与静态资源 | AVO-012 |
| 2026-02-27 | 完善 README 与 Docker 部署说明 | `README.md`, `docker-compose.yml` | 重写 README 部署文档并补充完整 Docker 运维流程；将后台管理端口映射改为可配置 `${AVOCADO_ADMIN_PORT:-18080}`，新增容器健康检查 | 风险低；若需回滚可恢复上一个 README 与 compose 版本 | AVO-011 |
| 2026-02-27 | 落地 Avocado v1 MVP 代码骨架 | `avocado/*`, `tests/*`, `Dockerfile`, `docker-compose.yml`, `requirements.txt`, `config.example.yaml`, `README.md` | 新增配置管理、CalDAV 客户端、AI 客户端、同步引擎、冲突处理、SQLite 状态库、调度器、Web API、基础单元测试与容器化 | 主要风险为不同 CalDAV 供应商兼容性差异；可回滚到上一提交并保留文档基线 | AVO-002, AVO-003, AVO-004, AVO-005, AVO-006, AVO-007 |
| 2026-02-27 | 建立项目长期文档治理基线 | `PROJECT_LOG.md`, `README.md` | 新增唯一事实源文档、模板、TODO 看板与维护规则；README 增加文档入口 | 风险低；如需回滚可删除 `PROJECT_LOG.md` 并恢复 README 链接 | AVO-001 |

## TODO 看板
### Todo
| ID | 标题 | 状态 | 验收标准 | 优先级 | 依赖项 | 最后更新 |
| --- | --- | --- | --- | --- | --- | --- |
| AVO-008 | 真实 CalDAV 端到端兼容验证（Nextcloud/iCloud） | Todo | 在至少 2 种服务器上完成拉取、写回、冲突场景验证并记录差异 | P0 | AVO-005, AVO-006 | 2026-02-27 |
| AVO-009 | 后台安全加固（登录认证/反向代理建议） | Todo | 提供最小认证机制或明确反向代理鉴权指南并可配置开关 | P1 | AVO-007 | 2026-02-27 |
| AVO-010 | CI 基线（lint + unittest + docker build） | Todo | push/pull request 时自动执行基础质量校验 | P1 | AVO-002 | 2026-02-27 |

### In Progress
| ID | 标题 | 状态 | 验收标准 | 优先级 | 依赖项 | 最后更新 |
| --- | --- | --- | --- | --- | --- | --- |
| (空) | - | - | - | - | - | - |

### Done
| ID | 标题 | 状态 | 验收标准 | 优先级 | 依赖项 | 最后更新 |
| --- | --- | --- | --- | --- | --- | --- |
| AVO-012 | 无登录管理页面（展示并修改 config） | Done | 根路径可访问管理页；可展示全部配置；保存配置与手动同步可用；密钥留空不覆盖 | P1 | AVO-007 | 2026-02-27 |
| AVO-011 | 完善 README 与 Docker 部署文档 | Done | README 包含完整 Docker 部署/运维流程，compose 明确后台管理端口映射并可配置 | P1 | AVO-007 | 2026-02-27 |
| AVO-007 | 内网 Web 后台（配置、状态、手动同步） | Done | 提供配置读取/更新、规则更新、同步触发、状态与审计查询接口 | P1 | AVO-002, AVO-005 | 2026-02-27 |
| AVO-006 | 接入 OpenAI 兼容接口并完成 AI 结果回写 | Done | 可从配置读取 `base_url/api_key/model` 并生成变更集回写 | P0 | AVO-005 | 2026-02-27 |
| AVO-005 | 实现同步引擎（未来窗口、差异识别、冲突处理） | Done | 可执行一轮同步，支持 AI Task 注入、用户优先冲突策略、审计记录 | P0 | AVO-003, AVO-004 | 2026-02-27 |
| AVO-004 | 实现 `[AI Task]` YAML 解析与回写模块 | Done | 可稳定注入、解析、更新模块且不破坏其他描述文本 | P0 | AVO-002 | 2026-02-27 |
| AVO-003 | 实现 CalDAV 日历发现与固定日历规则管理 | Done | 可列出日历、自动建议固定日历并支持手工确认配置 | P0 | AVO-002 | 2026-02-27 |
| AVO-002 | 初始化 Python 服务骨架与 Docker 运行框架 | Done | 可加载配置启动服务，具备容器化运行入口 | P0 | AVO-001 | 2026-02-27 |
| AVO-001 | 建立项目长期同步文档机制 | Done | 根目录存在 `PROJECT_LOG.md`，包含目标/约定/历史/TODO/快照，README 提供入口 | P0 | 无 | 2026-02-27 |

## 当前状态快照
### 当前版本关键能力
- 已具备可运行的后端服务：配置管理、SQLite 状态库、定时调度与手动触发。
- 已具备 CalDAV 拉取/写回能力及 AI 临时日历镜像流程。
- 已具备 `[AI Task]` 自动注入与规范化处理能力。
- 已具备 OpenAI 兼容接口调用与 AI 变更应用链路。
- 已具备基础 API 与审计查询能力。

### 当前已知问题（Known issues）
- 真实 CalDAV 服务商兼容性仍需实机验证（字段细节与事件更新行为可能存在差异）。
- 后台当前无登录鉴权，仅适合受控内网环境。
- 目前测试以单元测试为主，尚未包含真实服务器集成测试。

### 下一阶段目标（最多 3 条）
- 完成 Nextcloud/iCloud 等主流 CalDAV 服务端联调验证（AVO-008）。
- 增加后台访问安全机制与部署建议（AVO-009）。
- 建立 CI 自动化质量门禁（AVO-010）。
