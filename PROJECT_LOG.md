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
- 用户层事件 UID 使用 namespaced 格式；若遇到历史 UID 冲突，写入会跳过并记录 `skip_seed_uid_conflict` 审计事件。
- 若存在同名托管日历（stage/user）副本，副本不再参与源数据复制，且会清理其窗口内事件避免重复展示。
- 管理页面支持中英文双语；默认按浏览器语言自动选择，用户可手动切换并持久化偏好。
- AI 改动仅作用于 `user_intent` 非空的事件；无意图事件即使 AI 返回变更也会被跳过并记录审计。
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
| 2026-02-27 | 管理页新增 AI 修改条目列表与三点操作菜单 | `avocado/sync_engine.py`, `avocado/state_store.py`, `avocado/caldav_client.py`, `avocado/task_block.py`, `avocado/web_admin.py`, `avocado/templates/admin.html`, `avocado/static/admin.js`, `avocado/static/admin.css`, `tests/test_web_admin.py`, `README.md` | 新增 `GET /api/ai/changes` 列表，展示标题/时间/变更内容/原因；每条支持三点菜单执行“撤销本次 AI 修改”和“按提示要求再改”，并触发下一轮同步 | 风险中等；撤销依赖审计快照完整性，历史旧记录缺少快照时无法撤销 | AVO-024 |
| 2026-02-27 | 日志页新增 AI 请求字节数折线图 | `avocado/sync_engine.py`, `avocado/templates/admin.html`, `avocado/static/admin.js`, `avocado/static/admin.css`, `README.md` | 同步时新增 `ai_request` 审计事件并记录 `request_bytes`；管理页日志标签增加折线图，展示最近 AI 请求字节数趋势 | 风险低；仅新增审计记录与前端可视化，不影响同步主流程 | AVO-023 |
| 2026-02-27 | 三日历流转与自定义时间段同步 | `avocado/models.py`, `avocado/sync_engine.py`, `avocado/web_admin.py`, `avocado/templates/admin.html`, `avocado/static/admin.js`, `config.example.yaml`, `tests/test_web_admin.py`, `tests/test_models.py`, `README.md` | 新增 `intake`（新日程）日历并自动确保存在；`intake` 事件在同步时导入 `user-layer` 后从 `intake` 删除；新增 `POST /api/sync/run-window` 和管理页“一键自定义时间段同步” | 风险中等；若 intake 删除失败可能保留源事件，但导入 UID 命名空间可避免用户层重复 | AVO-022 |
| 2026-02-27 | 管理页日志体验升级：分栏卡片 + 详情折叠展示 | `avocado/templates/admin.html`, `avocado/static/admin.css`, `avocado/static/admin.js` | 日志页拆分为 Sync/Audit 双卡片；同步日志支持状态徽标与长文本省略；审计 `details` 改为摘要 + 可折叠完整 JSON，避免详情挤在单行导致页面过长 | 风险低；仅前端展示逻辑变更，不影响后端接口与数据 | AVO-021 |
| 2026-02-27 | 防止普通新建日程被 AI 改时间：仅对有意图事件应用 AI 改动 | `avocado/sync_engine.py`, `tests/test_sync_engine_helpers.py` | 新增 `user_intent` 守卫；AI 返回的改动若目标事件 `user_intent` 为空则直接跳过并写入 `ai_change_skipped_no_intent` 审计日志 | 风险低；若需恢复旧行为可回滚该守卫逻辑 | AVO-020 |
| 2026-02-27 | 管理页体验改进：AI测试改为行内链接 + 中英文切换 | `avocado/templates/admin.html`, `avocado/static/admin.js`, `avocado/static/admin.css`, `README.md` | 移除顶部 AI 测试按钮，将 AI 测试入口改为 AI Base URL 下方蓝色超链接；新增中英文界面，默认按浏览器语言自动切换并支持手动覆盖 | 风险低；仅前端展示与交互调整，不影响后端 API 协议 | AVO-019 |
| 2026-02-27 | 修复重复日历放大问题：同名托管副本隔离 + 冲突写入降级 | `avocado/sync_engine.py`, `avocado/caldav_client.py`, `avocado/web_admin.py`, `tests/test_sync_engine_helpers.py`, `tests/test_web_admin.py` | 同名托管副本日历不再作为源日历参与复制，并自动清理其窗口内事件；遇到 UID 唯一键冲突时降级为跳过并记录审计，避免整轮同步失败；管理页可标记 `managed_duplicate` 日历 | 风险中等；会清理同名副本日历窗口内事件，必要时可回滚版本并从 CalDAV 服务端恢复 | AVO-018 |
| 2026-02-27 | 修复用户层日程重复：旧UID迁移去重与删除回退 | `avocado/sync_engine.py`, `avocado/caldav_client.py` | 迁移旧UID后立即从本轮 `user_map` 移除旧事件，避免同轮重复处理；删除旧事件时支持 `href -> uid` 回退查找，提升旧事件清理成功率 | 风险低；若个别 CalDAV 服务仍拒绝删除，可回滚此变更并保留日志定位 | AVO-017 |
| 2026-02-27 | 增加用户层日历保证与管理页运行日志查询 | `avocado/models.py`, `avocado/web_admin.py`, `avocado/sync_engine.py`, `avocado/templates/admin.html`, `avocado/static/admin.js`, `avocado/static/admin.css`, `config.example.yaml`, `tests/test_models.py`, `README.md` | 新增 `user_calendar_id/user_calendar_name` 并在后端自动确保用户层日历存在；管理页新增同步日志与审计日志查询面板 | 风险低；日志查询为只读能力，不影响同步写入流程 | AVO-016 |
| 2026-02-27 | 同步策略升级：全日历打标 + 用户层对比stage触发重排 + 分类标签 | `avocado/sync_engine.py`, `avocado/task_block.py`, `avocado/planner.py`, `avocado/models.py`, `tests/test_task_block.py`, `README.md` | 所有非stage日历事件统一补全简化版 `[AI Task]`；轮询先比对用户层(日历非stage)与stage差异再触发AI重排；AI结果写入分类标签 `category`（缺失时本地回退分类） | 风险中等；若分类不准可通过手工编辑 `[AI Task].category` 覆盖 | AVO-015 |
| 2026-02-27 | 管理页新增 AI 连通性测试、提示词管理与时区下拉 | `avocado/web_admin.py`, `avocado/ai_client.py`, `avocado/models.py`, `avocado/planner.py`, `avocado/static/admin.js`, `avocado/templates/admin.html`, `config.example.yaml`, `tests/test_web_admin.py`, `tests/test_models.py`, `README.md` | 新增 `POST /api/ai/test` 测试 API 连通性；AI Base URL 默认 OpenAI；新增可编辑 `system_prompt`；时区改为下拉选择 | 风险低；AI 测试依赖供应商兼容的 chat/completions 接口，失败不影响核心同步流程 | AVO-014 |
| 2026-02-27 | 管理页新增 CalDAV 日历列表与按日历默认行为配置 | `avocado/static/admin.js`, `avocado/templates/admin.html`, `avocado/static/admin.css`, `avocado/web_admin.py`, `avocado/models.py`, `avocado/sync_engine.py`, `config.example.yaml`, `tests/test_models.py`, `tests/test_web_admin.py`, `README.md` | 点击 Sync 后自动刷新 CalDAV 日历列表；可按日历配置 immutable/editable、default locked、default mandatory；新增 `per_calendar_defaults` 配置并接入同步逻辑 | 风险中等；若日历列表获取失败，配置表单仍可使用；可回滚至上个管理页版本 | AVO-013 |
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
| AVO-024 | AI 修改条目可观测与可操作化（撤销/按提示重改） | Done | 管理页可列出 AI 修改条目（标题、时间、改动、原因）；每条支持撤销与提示词重改，并触发同步 | P0 | AVO-023 | 2026-02-27 |
| AVO-023 | 日志页 AI 请求字节趋势可视化 | Done | 同步时记录 `ai_request.request_bytes`；管理页日志可显示最近请求字节数折线图 | P1 | AVO-021 | 2026-02-27 |
| AVO-022 | 三日历管理与自定义时间段同步 | Done | 新增 intake 日历并在每轮同步导入到 user-layer 后删除；管理页可提交 start/end 触发自定义窗口同步 | P0 | AVO-016, AVO-020 | 2026-02-27 |
| AVO-021 | 管理页日志布局与详情可读性优化 | Done | 日志页分成同步/审计两个独立卡片；长 message 不再撑爆布局；审计 details 默认摘要显示并可折叠查看完整 JSON | P1 | AVO-016 | 2026-02-27 |
| AVO-020 | 仅对含 user_intent 的事件应用 AI 改动 | Done | 普通新建事件在无 `user_intent` 时不会被 AI 改时间；审计日志可见 `ai_change_skipped_no_intent` | P0 | AVO-015 | 2026-02-27 |
| AVO-019 | 管理页中英文切换与 AI 测试入口改版 | Done | AI 测试入口位于 AI Base URL 下方并为超链接样式；页面支持浏览器语言自动切换中英文并可手动修改 | P1 | AVO-014 | 2026-02-27 |
| AVO-018 | 修复同名托管日历导致的重复扩散 | Done | 同名 user/stage 副本日历不会再参与源数据复制且会清理窗口内副本事件；UID 冲突不会导致整轮同步失败；管理页可识别重复托管日历 | P0 | AVO-017 | 2026-02-27 |
| AVO-017 | 修复用户层日程重复（UID迁移） | Done | 旧 plain UID 迁移为 namespaced UID 后不再出现同轮双记录；旧事件删除支持回退策略 | P0 | AVO-016 | 2026-02-27 |
| AVO-016 | 用户层日历自动确保 + 管理页日志查询 | Done | 系统自动确保 user-layer 日历存在并在管理页可识别；管理页可查询同步运行日志与审计日志 | P1 | AVO-015 | 2026-02-27 |
| AVO-015 | 同步引擎改为用户层vs stage差异触发重排并增加分类标签 | Done | 所有非stage日历事件均有简化版 `[AI Task]`；轮询比对用户层与stage差异决定是否重排；AI变更后写入 `category` | P0 | AVO-013, AVO-014 | 2026-02-27 |
| AVO-014 | 管理页支持 AI 测试接口、提示词管理、时区下拉 | Done | 可在管理页测试 AI API 连通性；AI 默认 Base URL 为 OpenAI；可编辑系统提示词；时区使用下拉选择 | P1 | AVO-012 | 2026-02-27 |
| AVO-013 | 管理页支持日历列表与按日历默认行为配置 | Done | 点击 Sync 后可刷新并展示 CalDAV 日历；可按日历保存 immutable/locked/mandatory 默认行为并被同步引擎使用 | P1 | AVO-012 | 2026-02-27 |
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
