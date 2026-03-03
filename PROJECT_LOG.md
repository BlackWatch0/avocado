# Avocado Project Log

最后更新: 2026-03-03

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
- `[AI Task]` 至少包含字段: `locked`、`editable_fields`、`user_intent`、`updated_at`。
- 用户层事件 UID 使用 namespaced 格式；若遇到历史 UID 冲突，写入会跳过并记录 `skip_seed_uid_conflict` 审计事件。
- 若存在同名托管日历（stack/user/new）副本，副本不再参与源数据复制，且会清理其窗口内事件避免重复展示。
- 管理页面支持中英文双语；默认按浏览器语言自动选择，用户可手动切换并持久化偏好。
- AI 改动仅作用于 `user_intent` 非空的事件；无意图事件即使 AI 返回变更也会被跳过并记录审计。
- AI 规划请求仅把 `user_intent` 非空且未锁定事件作为 `target_events`；其余事件仅作为上下文约束，避免误改与 token 浪费。
- 定时同步（`trigger=scheduled`）在 planning payload 未变化时跳过 AI 请求，并记录 `skip_ai_same_payload` 审计，避免重复消耗 token。
- 配置文件为 `config.yaml`，关键字段:
  - CalDAV: `base_url`、`username`、`password`
  - AI: `enabled`、`base_url`、`api_key`、`model`
  - Sync: `window_days`、`interval_seconds`、`freeze_hours`、`timezone_source`、`timezone`
  - Calendar Rules: `stack_calendar_*`、`user_calendar_*`、`new_calendar_*`
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
| 2026-03-03 | 防重复触发修复：AI 成功改动后消费意图 + 后态哈希去重 | `avocado/sync/pipeline.py`, `tests/test_ai_request_audit.py` | 仅对“成功应用 AI 改动”的事件清空 `user_intent`；`last_applied_ai_hash` 改为记录 AI 应用后的最终状态，避免下一轮因 AI 自身写回再次触发 | 风险低；若希望同一意图持续生效需再次填写 `user_intent`，回滚可恢复旧哈希策略与清空时机 | AVO-064 |
| 2026-03-03 | AI payload 重构：本地解析 `[AI Task]` 并提升字段 | `avocado/sync/pipeline.py`, `avocado/task_block.py`, `avocado/planner.py`, `avocado/core/models/ai_task_fields.py`, `tests/test_task_block.py`, `tests/test_ai_request_audit.py` | 发送给 AI 的 `description` 改为仅正文；`[AI Task]` 解析后拆为 `ai_task`（`locked/category/user_intent`）与 `x-*` 元字段（`x-version/x-editable_fields/x-updated_at`）；同时只发 Stage 层并按 UID 去重，压缩 `calendar_id` 为短别名后回映射 | 风险中等；prompt 需适配新 payload 结构，回滚可恢复旧 `description` 内嵌 `[AI Task]` 传输 | AVO-063 |
| 2026-03-03 | Prompt 独立存储并迁移到根目录 | `avocado/config_manager.py`, `docker-compose.yml`, `avocado/templates/admin.html`, `avocado/static/admin/i18n.js`, `README.md`, `config.example.yaml`, `tests/test_config_manager.py` | `ai.system_prompt` 从 `config.yaml` 分离到根目录 `ai_system_prompt.txt`（容器 `/app/ai_system_prompt.txt`）；首次读取可自动迁移旧配置/旧路径 `data/ai_system_prompt.txt`；后台单独 Prompt 区域可编辑 | 风险低；升级时需确保根目录 prompt 文件可写，回滚可改回 `config.yaml` 内嵌存储 | AVO-062 |
| 2026-03-03 | 指标升级：AI 请求字节改为 Token 消耗 | `avocado/ai_client.py`, `avocado/sync/pipeline.py`, `avocado/web_admin/routes/ai.py`, `avocado/persistence/state_store/repo_audit.py`, `avocado/static/admin/ai_bytes_chart.js`, `avocado/static/admin/i18n.js`, `tests/test_ai_request_audit.py`, `tests/test_web_admin.py` | 审计记录新增 `prompt_tokens/completion_tokens/total_tokens`；图表改展示 token 消耗；`/api/ai/test` 也写入 `ai_request` 指标点，便于快速观测 | 风险低；历史仅有字节数据的记录不会进入 token 图，回滚可恢复 `request_bytes` 聚合 | AVO-061 |
| 2026-03-03 | AI payload I/O 测试日志落盘 | `avocado/ai_client.py`, `avocado/core/models/config.py`, `config.example.yaml`, `README.md`, `tests/test_ai_client_payload_logging.py` | 新增 `ai.payload_logging_enabled/payload_log_path/payload_log_max_chars`；每次 AI 请求记录请求体与响应体（JSONL），用于联调；默认关闭 | 风险中等；开启后可能记录敏感业务文本，联调后建议关闭或清理 | AVO-060 |
| 2026-03-03 | 管理端模型列表加载稳定性修复 | `avocado/static/admin/index.js`, `avocado/templates/admin.html` | AI 连通性测试后模型下拉改为“全量替换重建”而非增量追加；静态脚本版本号刷新防缓存导致旧逻辑残留 | 风险低；仅前端行为调整，回滚可恢复旧追加逻辑 | AVO-059 |
| 2026-03-03 | 重复托管日历创建修复（路径归一匹配） | `avocado/integrations/caldav/helpers.py`, `avocado/integrations/caldav/service.py`, `tests/test_caldav_service.py` | `ensure_managed_calendar` 增加按规范化路径匹配（host/scheme 差异兜底），避免同一路径被误判为新日历导致重复创建 | 风险低；若供应商路径语义特殊可回滚匹配策略 | AVO-058 |
| 2026-03-03 | 宿主机时区自动读取 + 管理后台时区来源配置 | `avocado/timezone_utils.py`, `avocado/sync/engine.py`, `avocado/sync/pipeline.py`, `avocado/web_admin/routes/config.py`, `avocado/templates/admin.html`, `avocado/static/admin/*`, `avocado/core/models/config.py`, `config.example.yaml`, `README.md`, `tests/test_timezone_utils.py`, `tests/test_web_admin.py` | 同步窗口与 AI planning payload 的 `timezone` 改为按 `sync.timezone_source` 解析：`host` 自动检测宿主机时区，`manual` 使用 `sync.timezone`；管理后台新增“时区来源（自动/手动）+ 宿主机/生效时区展示”并提供 `GET /api/system/timezone`。 | 风险低；若自动识别不符合预期，可将 `timezone_source` 切回 `manual` 并显式设置 `timezone`。 | AVO-056 |
| 2026-03-02 | 模型层模块化拆分（`core/models`） | `avocado/core/models/*`, `avocado/config_manager.py`, `avocado/ai_client.py`, `avocado/planner.py`, `avocado/reconciler.py`, `avocado/task_block.py`, `tests/*` | 原 `avocado/models.py` 拆分为 `constants/time_utils/config/entities`，全仓切换到 `from avocado.core.models import ...`，配置与实体语义保持不变。 | 风险低；若需回滚可恢复 `avocado/models.py` 单文件并批量改回 import。 | AVO-049 |
| 2026-03-02 | CalDAV 集成层拆分（`integrations/caldav`） | `avocado/integrations/caldav/*`, `avocado/tools/*`, `avocado/sync/*`, `avocado/web_admin/routes/*` | 原 `caldav_client.py` 拆分为 `service/codec/calendar_ops/delta_ops/helpers`，保留 token 增量、窗口索引、X-AVO 字段读写能力。 | 风险中等；若出现供应商兼容回归可回滚到旧单文件实现。 | AVO-050 |
| 2026-03-02 | 状态库持久化拆分（`persistence/state_store`） | `avocado/persistence/state_store/*`, `avocado/sync/*`, `avocado/web_admin/*`, `tests/*` | 原 `state_store.py` 按 repo 粒度拆分为 `sync_runs/audit/snapshots/meta/mappings/tombstones/new_cleanup`，`StateStore` 通过 mixin 组装，schema 初始化逻辑保持单次执行。 | 风险中等；若迁移后出现 SQL 行为差异可回滚到旧 `state_store.py`。 | AVO-051 |
| 2026-03-02 | 同步引擎拆分（`sync/engine + pipeline + writeback`） | `avocado/sync/*`, `avocado/scheduler.py`, `tests/test_sync_engine_*` | 原 `sync_engine.py` 重构为多模块：身份与意图助手函数独立，`run_once` 下沉到 `pipeline.py`，写回重试与冲突处理下沉到 `writeback.py`，外部入口统一 `from avocado.sync import SyncEngine`。 | 风险中等；若出现行为回归可整包回滚 `avocado/sync/*`。 | AVO-052 |
| 2026-03-02 | 管理端后端拆分（`web_admin` 包化 + 路由分组） | `avocado/web_admin/app.py`, `avocado/web_admin/context.py`, `avocado/web_admin/schemas.py`, `avocado/web_admin/utils.py`, `avocado/web_admin/routes/*`, `avocado/main.py`, `tests/test_web_admin.py` | 原 `web_admin.py` 拆分为 app 工厂+分路由模块，HTTP API 路径不变，入口更新为 `avocado.web_admin.app:app`。 | 风险中等；若路由绑定异常可回滚到单文件 `web_admin.py`。 | AVO-053 |
| 2026-03-02 | 管理端前端模块化（ES Modules + 样式分片） | `avocado/static/admin/*`, `avocado/static/admin/styles/*`, `avocado/templates/admin.html` | 原 `static/admin.js` 拆分为 `index/i18n/state/dom/api/config_form/calendars_table/logs_sync/logs_audit/ai_changes/ai_bytes_chart/ui/utils`；原 `admin.css` 拆分为 `base/layout/components/logs`；页面改为 `<script type=\"module\">` 加载。 | 风险中等；若浏览器或路径解析异常可回滚 `admin` 目录与 `admin.html`。 | AVO-054 |
| 2026-03-02 | 工具脚本解耦到 `tools` 子包 | `avocado/tools/*`, `README.md`, `tests/test_smoke_test.py` | `smoke_test/e2e_sync_suite/user_case_runner` 迁移到 `avocado.tools`，README 与测试入口同步更新为 `python -m avocado.tools.*`。 | 风险低；若脚本调用路径不兼容可回滚文件位置并恢复命令。 | AVO-055 |
| 2026-03-02 | 锁定语义修正：`[AI Task].locked` 强约束 AI 不改动 | `avocado/sync_engine.py`, `avocado/web_admin.py`, `avocado/static/admin.js`, `avocado/templates/admin.html`, `avocado/models.py`, `config.example.yaml` | 同步引擎在 AI 目标筛选与应用阶段统一按 `[AI Task]` 中 `locked` 判定是否可改；管理端新增“Locked Source”来源日历锁定勾选（持久化到 `calendar_rules.locked_calendar_ids`），用于将来源事件默认视为不可被 AI 修改。 | 风险低；仅收紧 AI 可修改范围。若需恢复旧行为，可回滚本条并移除 `locked_calendar_ids`。 | AVO-048 |
| 2026-03-02 | 三日历协作重构（`user/stack/new`）与状态层升级 | `avocado/sync_engine.py`, `avocado/state_store.py`, `avocado/caldav_client.py`, `avocado/models.py`, `avocado/web_admin.py`, `avocado/static/admin.js`, `avocado/templates/admin.html`, `avocado/smoke_test.py`, `avocado/e2e_sync_suite.py`, `avocado/user_case_runner.py`, `config.example.yaml`, `README.md`, `tests/*` | 同步引擎重写为 Step 0-9 增量架构；新增 `sync_tokens/event_mappings/suppression_tombstones/pending_new_cleanup` 持久化；`stack` 成为窗口内目标真相，`user` 增量 patch，`new` 仅入栈后清理；管理端与配置键全面迁移到 `stack/user/new`；新增 `ai.enabled` 与 `sync.freeze_hours`；移除 `immutable/per_calendar_defaults` 运行链路；全量测试通过（`53 passed`）。 | 风险中等（破坏性配置变更）；回滚需恢复旧配置键与旧 state schema 备份。 | AVO-047 |
| 2026-02-27 | 修复“简介型意图”误改时间导致事件看似丢失 | `avocado/sync_engine.py`, `tests/test_sync_engine_helpers.py` | 新增意图语义防护：当 `user_intent` 属于“写入简介/描述”等文本型请求且不包含明确改时关键词时，自动屏蔽 AI 对 `start/end` 的变更，仅允许描述类字段更新；新增审计事件 `ai_change_time_blocked_description_intent` 便于追踪。针对 `run_id=248` 的异常定位为“被改到 2026-02-27 00:00”，并非删除。 | 风险低；若用户希望在同一意图中既改简介又改时间，需明确写出时间变更指令（如“提前30分钟”），否则时间改动会被拦截。 | AVO-046 |
| 2026-02-27 | 三日历端到端用例集增强 + AI 目标事件过滤修复 | `avocado/user_case_runner.py`, `tests/fixtures/user_cases_zh.json`, `avocado/sync_engine.py`, `avocado/planner.py`, `avocado/task_block.py`, `tests/test_sync_engine_helpers.py`, `tests/test_sync_engine_invalid_datetime.py`, `tests/test_task_block.py` | 新增 UTF-8 中文真实用例运行器（默认 `tests/fixtures/user_cases_zh.json`），每条用例同时校验 `stage/user/intake` 三日历状态；新增 `intake -> user -> stage` 迁移验证。同步引擎改为仅对 `user_intent` 目标事件请求 AI，非目标事件在 payload 中作为锁定约束，且无目标事件时直接跳过 AI 调用；同时统一 `user_intent` 的 `null/None` 归一化为空字符串。`manual-window` 实测通过：`run_id=226`，6/6 用例通过。 | 风险低；AI 调用目标更聚焦，若需要“全量重排”可后续加显式模式开关；回滚可恢复原 `all_events` 直传策略。 | AVO-045 |
| 2026-02-27 | 新增真实环境 E2E 测试集：读写配置 + 触发 Sync + 校验 AI 与固定日程 + 落盘日志 | `avocado/e2e_sync_suite.py`, `README.md` | 新增 `python -m avocado.tools.e2e_sync_suite`：读取 `config.yaml`，执行配置写读回环测试；创建临时测试事件（可编辑与锁定）；触发 `manual-window` 全链路同步；校验 AI 是否执行移动指令、锁定日程是否不变、immutable 源日程是否镜像到用户层；自动清理测试事件；将完整过程写入 `data/test_logs/` 并输出 JSON 汇总 | 风险中等；脚本会在测试环境真实写入并删除日历事件，请勿在生产环境直接运行 | AVO-044 |
| 2026-02-27 | 新增自动联调脚本：读取现网 `config.yaml` 一键检查 | `avocado/smoke_test.py`, `README.md` | 新增 `python -m avocado.tools.smoke_test`：自动校验 CalDAV 连接/日历读取、AI 连通性与模型列表；可选 `--run-sync` 直接执行一次 `manual-window` 同步并输出变更/冲突；支持自定义窗口与跳过单侧检查 | 风险低；`--run-sync` 会写入测试环境数据，生产环境请谨慎 | AVO-043 |
| 2026-02-27 | 修复 Class Schedule 未同步到用户层：immutable 日历镜像到 user-layer | `avocado/sync_engine.py`, `tests/test_sync_engine_run_once.py` | immutable 日历事件不再仅用于规划约束，同时会以 `locked=true` 镜像到用户层（使用 namespaced UID），并随源事件变更自动更新；仍保持源 immutable 日历只读不回写 | 风险中等；若用户同时订阅源 immutable 日历与用户层，可能在客户端看到“源+镜像”双份展示，可按需隐藏源日历 | AVO-042 |
| 2026-02-27 | 移除 AI Task `mandatory` 生效链路 + 禁止编辑保留日历默认行为 | `avocado/task_block.py`, `avocado/sync_engine.py`, `avocado/web_admin.py`, `avocado/static/admin.js`, `tests/test_task_block.py`, `tests/test_sync_engine_source_layer.py` | `[AI Task]` 规范化不再写入 `mandatory`，历史 `mandatory` 字段会被忽略；同步引擎仅以 `locked` 判断是否允许 AI 修改；管理页对 `stage/user/intake` 三个保留日历的默认行为输入项禁用，且后端更新接口会过滤这三类日历的行为配置写入 | 风险低；旧配置中 `mandatory=true` 将不再阻止 AI，若需强约束请改用 `locked=true` | AVO-041 |
| 2026-02-27 | Debug 日志增强：按 run_id 归类 + AI 链路细粒度审计 | `avocado/state_store.py`, `avocado/sync_engine.py`, `avocado/web_admin.py`, `avocado/templates/admin.html`, `avocado/static/admin.js`, `avocado/static/admin.css` | 同步任务改为“开始建档 + 结束回填状态”；新增 run 级别调试事件（`run_start`、`window_selected`、`ai_changes_normalized`、`ai_change_evaluate`、`skip_ai_*`）；审计接口支持 `run_id` 过滤，管理页日志支持按 `run_id` 筛选，点击 Sync Runs 中的 `#id` 可快速查看该轮全量操作 | 风险低；审计量会增加，数据库增长更快，可后续增加保留策略 | AVO-040 |
| 2026-02-27 | 修复 manual-window 稳定性与 AI 目标过滤 | `avocado/reconciler.py`, `avocado/sync_engine.py`, `avocado/web_admin.py` | 修复 `editable_fields` 计算中的 `tuple & set` 运行时异常；AI 返回命中 `locked/mandatory` 事件时改为显式跳过审计（`ai_change_skipped_locked`）而非冲突；同步归一化阶段会清理锁定/强制事件中的遗留 `user_intent`，减少 AI 误命中；撤销接口增加无 `get_event_by_uid/etag` 兼容 | 风险低；锁定事件上的历史意图会被清空，若需执行需先解锁或在可编辑事件中下达意图 | AVO-039 |
| 2026-02-27 | 合并修复汇总（PR #3 ~ #9）：同步安全性与可控性增强 | `avocado/sync_engine.py`, `avocado/reconciler.py`, `avocado/task_block.py`, `avocado/web_admin.py`, `tests/test_*` | 合并包含 7 类修复：1) immutable/source 日历默认只读，避免回写污染；2) 重复日历清理增加归属校验；3) AI Task YAML 非法时容错；4) AI 返回非法 datetime 按条目降级并审计；5) AI 改动严格尊重 `editable_fields`；6) 撤销 AI 改动增加并发校验；7) 补充对应单测覆盖 | 风险低；若需回滚可按 PR 粒度回退（#3~#9），但会失去对应防护能力 | AVO-038 |
| 2026-02-27 | 修复多层 UID 连锁重排：清理嵌套 UID + AI 执行后消费意图 | `avocado/sync_engine.py` | 启动/同步时自动清理 stage 与 user-layer 中 `depth>=2` 的嵌套托管 UID；AI 对事件成功应用（或判定无实际变化）后会清空该事件 `user_intent`，避免同一指令每轮重复触发导致事件持续漂移 | 风险中等；若希望同一意图持续生效需重新填写 `user_intent` | AVO-037 |
| 2026-02-27 | 修复 intake 新日程重复导入与删除循环问题 | `avocado/sync_engine.py` | intake 日历仅处理 raw UID（depth=0）；对已托管 UID（depth>=1）直接清理，避免再次加前缀导致 `a:b:c` 扩散；导入时遇到 UID 冲突也会尝试删除 intake 源条目并回填已存在 user 事件 | 风险低；若误判极少数手工特殊 UID，可回滚到上一版本策略 | AVO-036 |
| 2026-02-27 | 定时同步无变化时跳过 AI 请求 | `avocado/sync_engine.py`, `avocado/state_store.py` | 新增 planning payload 指纹存储；`trigger=scheduled` 且 payload 与上次一致时不调用 AI，写入 `skip_ai_same_payload` 审计事件 | 风险低；首次部署或手动/启动触发仍会正常请求 AI，如需恢复旧行为可回滚该判定分支 | AVO-035 |
| 2026-02-27 | 去重规划输入：不再重复收集可编辑源日历事件 | `avocado/sync_engine.py` | 构建 AI planning payload 时仅保留 immutable 源日历事件与 user-layer 事件；可编辑源日历事件由 user-layer 镜像代表，避免重复进入模型导致重复日程或错判 | 风险低；若某源事件未成功镜像到 user-layer，可能暂时不参与规划（可通过审计定位） | AVO-034 |
| 2026-02-27 | 修复 AI 改简介后 `user_intent` 被覆盖清空 | `avocado/sync_engine.py` | AI 返回 `description` 时，应用后会强制保留原事件 `user_intent`，避免下一轮同步被判 `no_intent` 而跳过 | 风险低；仅在 AI 应用链路补一层意图保留，不影响字段冲突策略 | AVO-033 |
| 2026-02-27 | 修复 stage 镜像 Duplicate UID 导致整轮同步失败 | `avocado/caldav_client.py`, `avocado/sync_engine.py` | `upsert_event` 在 UID 冲突时新增时间窗口检索回退；stage 镜像写入遇到 `calobjects_by_uid_index` 冲突时自动执行“删除同 UID + 重试一次”，失败则跳过单条并记录审计，不再中断整轮同步 | 风险低；极端情况下仅跳过单条 stage 镜像事件，不影响 user-layer 主写入链路 | AVO-032 |
| 2026-02-27 | 修复 user_intent 跨层未生效：源日历意图自动同步到用户层 | `avocado/sync_engine.py`, `tests/test_sync_engine_helpers.py` | 当用户在 `personal/intake` 等非 stage 源日历更新 `user_intent` 时，系统会同步到对应 user-layer 事件并触发重排；减少 `ai_change_skipped_no_intent` 误跳过 | 风险低；仅增强意图同步，不改变既有锁定/冲突策略 | AVO-031 |
| 2026-02-27 | AI 修改条目默认精简展示 | `avocado/web_admin.py`, `avocado/static/admin.js` | AI 修改条目列表默认 `limit` 下调为 15（前后端一致），避免日志页一次性列出过多条目导致页面过长 | 风险低；仅默认展示数量调整，不影响历史数据存储与接口兼容 | AVO-030 |
| 2026-02-27 | 修复 AI 修改记录空白展示（旧审计兼容回退） | `avocado/web_admin.py`, `avocado/sync_engine.py`, `avocado/static/admin.js`, `tests/test_web_admin.py` | `GET /api/ai/changes` 对旧审计记录增加回退：标题回退到 UID、时间尝试从 patch/当前事件补全、原因缺失时给出可读提示；过滤“无实际字段变化”的记录；同步侧新增 `ai_change_skipped_no_effect`，避免写入空变更记录 | 风险低；仅展示层与审计记录过滤增强，不影响同步主流程 | AVO-029 |
| 2026-02-27 | API 连通性测试支持模型列表下拉 | `avocado/ai_client.py`, `avocado/web_admin.py`, `avocado/templates/admin.html`, `avocado/static/admin.js`, `tests/test_web_admin.py`, `README.md` | 点击“测试 API 连通性”后返回可用 `models` 列表并填充 `Model` 下拉框；测试文案去掉“AI”字样 | 风险低；若供应商不支持 `/models` 接口则列表为空，仍可保留当前模型值 | AVO-026 |
| 2026-02-27 | AI 请求字节图增强：自动刷新 + 90天默认保留 + 自定义范围 | `avocado/state_store.py`, `avocado/web_admin.py`, `avocado/templates/admin.html`, `avocado/static/admin.js`, `avocado/static/admin.css`, `tests/test_web_admin.py`, `README.md` | 新增 `GET /api/metrics/ai-request-bytes` 专用指标接口；图表从审计独立查询并默认展示近 90 天，可自定义天数；前端每 30 秒自动刷新，失败时使用本地缓存兜底显示 | 风险低；仅新增查询与前端展示逻辑，不影响同步主流程 | AVO-025 |
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
| AVO-027 | AI 记忆与关键词学习（跨日程持续优化） | Todo | 系统可从历史日程中提炼关键词/偏好并形成可复用记忆，在新一轮排程时纳入提示词和约束，且支持查看与清理记忆 | P1 | AVO-015, AVO-024 | 2026-02-27 |
| AVO-028 | 新建日程初始化指令（如 `/i`） | Todo | 用户创建新日程时可通过指令触发 AI 初始化，自动补全时间、时长、位置等字段，并结合历史记忆与规则生成可编辑结果 | P1 | AVO-022, AVO-027 | 2026-02-27 |

### In Progress
| ID | 标题 | 状态 | 验收标准 | 优先级 | 依赖项 | 最后更新 |
| --- | --- | --- | --- | --- | --- | --- |
| (空) | - | - | - | - | - | - |

### Done
| ID | 标题 | 状态 | 验收标准 | 优先级 | 依赖项 | 最后更新 |
| --- | --- | --- | --- | --- | --- | --- |
| AVO-069 | 高负载自动切换更强模型（按事件数阈值） | Done | 新增 `ai.high_load_model` 与 `ai.high_load_event_threshold`；当本轮规划事件数达到阈值时自动使用高负载模型；后台可配置并落盘 | P1 | AVO-068 | 2026-03-03 |
| AVO-068 | 新导入日程无意图也触发一次 AI 安排 | Done | 本轮从 `new` 日历导入到 stage 的事件，即使 `user_intent` 为空也会进入 `target_events` 并触发 AI 请求；无新导入且无意图时仍跳过 | P0 | AVO-067 | 2026-03-03 |
| AVO-067 | `[AI Task]` 标签精简与模板文件独立化 | Done | 注入时仅保留 `locked/user_intent`；不再自动写入 `version/editable_fields/category/updated_at`；模板改为独立 `ai_task_template.yaml` 文件加载 | P1 | AVO-063 | 2026-03-03 |
| AVO-066 | Docker 默认管理端口改为 1443 | Done | `docker compose up -d --build` 后默认映射 `1443:8080`，重启无需额外指定端口 | P2 | AVO-011 | 2026-03-03 |
| AVO-065 | AI Token 图改为“每次 Sync 一点”并补零值 | Done | 每次已结束 Sync 都产生一条 token 统计点；未触发 AI 的 Sync 也记录 0；前端图表可展示 0 值点 | P1 | AVO-061 | 2026-03-03 |
| AVO-064 | 防重复触发：成功改动后消费意图 + 后态哈希去重 | Done | AI 成功改动后仅清空对应事件 `user_intent`；下一轮不因 AI 自身写回重复触发 | P0 | AVO-061, AVO-063 | 2026-03-03 |
| AVO-063 | AI payload 结构升级（独立 `ai_task` + `x-*`） | Done | `[AI Task]` 字段独立上送，`description` 仅正文；仅发送 Stage 且 UID 去重；`calendar_id` 压缩并回映射 | P0 | AVO-062 | 2026-03-03 |
| AVO-062 | Prompt 独立文件存储与根目录迁移 | Done | `ai_system_prompt.txt` 独立持久化并由后台编辑；支持旧配置自动迁移 | P1 | AVO-053, AVO-054 | 2026-03-03 |
| AVO-061 | AI 消耗指标改为 Token 统计 | Done | 后端审计与前端图表均基于 `total_tokens` 展示，可区分 prompt/completion | P1 | AVO-060 | 2026-03-03 |
| AVO-060 | AI 请求/响应测试日志导出 | Done | 可配置导出每次 AI 请求/响应内容到 JSONL，便于联调复盘 | P1 | AVO-053 | 2026-03-03 |
| AVO-059 | 管理端模型下拉稳定性修复 | Done | 连通性测试后模型列表正确覆盖更新，前端缓存不再导致旧逻辑残留 | P1 | AVO-054 | 2026-03-03 |
| AVO-058 | 重复托管日历创建修复 | Done | 管理日历按路径归一匹配，避免同路径重复创建保留日历 | P0 | AVO-050, AVO-047 | 2026-03-03 |
| AVO-056 | 宿主机时区自动读取与后台来源切换 | Done | 同步窗口与 AI payload 使用自动/手动时区来源；后台可查看宿主机与生效时区并切换来源 | P1 | AVO-053, AVO-054 | 2026-03-03 |
| AVO-055 | 工具脚本迁移到 `avocado.tools` | Done | `smoke/e2e/user_case_runner` 统一使用 `python -m avocado.tools.*` 运行，README 与测试路径同步更新 | P1 | AVO-049 | 2026-03-02 |
| AVO-054 | 管理端前端 ES Modules 模块化 | Done | 管理页改为 `type=module`，JS/CSS 拆分到 `static/admin` 多模块，原页面功能可用 | P0 | AVO-053 | 2026-03-02 |
| AVO-053 | `web_admin` 后端路由分包重构 | Done | `web_admin` 拆分 app/context/schemas/utils/routes，API 路径保持不变，测试通过 | P0 | AVO-052 | 2026-03-02 |
| AVO-052 | 同步引擎拆分为 pipeline/writeback/helpers | Done | `SyncEngine` 迁移到 `avocado.sync` 包，`run_once` 与写回逻辑分层，单测通过 | P0 | AVO-051 | 2026-03-02 |
| AVO-051 | `state_store` repo 化拆分 | Done | `StateStore` 拆分为 schema + repo mixin，状态表读写行为不变，测试通过 | P0 | AVO-050 | 2026-03-02 |
| AVO-050 | CalDAV 集成层模块化 | Done | `caldav_client` 拆分为 `integrations/caldav` 子模块并保持原能力 | P0 | AVO-049 | 2026-03-02 |
| AVO-049 | 模型层拆分到 `core/models` | Done | `models.py` 拆分为 4 个领域文件并完成全仓 import 迁移 | P0 | AVO-047 | 2026-03-02 |
| AVO-048 | 锁定语义修正（AI Task.locked 优先）+ 来源日历锁定开关恢复 | Done | AI 在目标筛选和应用阶段严格遵守 `[AI Task].locked`；管理页可对来源日历勾选 `Locked Source` 并落盘生效 | P0 | AVO-047 | 2026-03-02 |
| AVO-047 | 三日历协作引擎重构（user/stack/new） | Done | 完成 Step 0-9 同步流程重构；管理端与配置切换到 `stack/user/new`；新增 token/mapping/tombstone/cleanup 状态表；移除 immutable/per_calendar_defaults 运行链路；测试通过 | P0 | AVO-041, AVO-045 | 2026-03-02 |
| AVO-046 | 248 号运行“简介意图误改时间”防护修复 | Done | 当意图为描述型请求时，AI 不得改动 `start/end`；审计可见拦截事件；`run_id=248` 场景复盘确认并非删除而是误改到午夜 | P0 | AVO-045 | 2026-02-27 |
| AVO-045 | 三日历真实用例校验与 AI 目标过滤修复 | Done | 用例集覆盖 user/intake 输入及 stage/user/intake 三日历断言；无 `user_intent` 时不发 AI；“提前30分钟”意图在真实环境稳定命中并通过 | P0 | AVO-022, AVO-040, AVO-044 | 2026-02-27 |
| AVO-044 | 真实环境 E2E 同步测试集与日志落盘 | Done | 一条命令覆盖配置读写、固定日程保护、AI 移动指令执行、immutable 镜像校验并自动清理；全程有文件日志与 JSON 汇总 | P0 | AVO-043, AVO-042 | 2026-02-27 |
| AVO-043 | 自动联调脚本（读取现网 config） | Done | 使用一条命令完成 CalDAV/AI/配置检查，并可选执行一次真实同步；输出结构化结果用于快速定位环境问题 | P1 | AVO-040 | 2026-02-27 |
| AVO-042 | immutable 日历同步到用户层镜像 | Done | `Class Schedule` 等 immutable 日历事件在用户层可见并随源更新；源 immutable 日历保持只读不被回写 | P0 | AVO-041 | 2026-02-27 |
| AVO-041 | 删除 mandatory 生效语义并锁定保留日历行为编辑 | Done | `[AI Task]` 不再含 `mandatory` 且旧字段不影响调度；`stage/user/intake` 在管理页不可编辑默认行为，后端也会忽略其行为更新请求 | P0 | AVO-039, AVO-040 | 2026-02-27 |
| AVO-040 | 审计日志按触发 run 分组与深度调试 | Done | 每次同步有独立 run_id；可按 run_id 查看审计日志；AI 请求到变更应用链路均有细粒度事件，便于排查“未更新”与“被校验拦截” | P0 | AVO-039 | 2026-02-27 |
| AVO-039 | 修复 manual-window 崩溃与锁定事件误命中 AI | Done | `manual-window/scheduled` 不再出现 `tuple & set` 崩溃；锁定/强制事件被 AI 返回时会被跳过并可观测；撤销接口在服务能力受限时仍可回退执行 | P0 | AVO-038 | 2026-02-27 |
| AVO-038 | 合并 PR #3~#9 的同步稳健性修复包 | Done | immutable/source 不再被误回写；AI 非法数据不再中断整轮同步；撤销与字段编辑约束具备并发与边界保护；相关单测通过 | P0 | AVO-015, AVO-024, AVO-037 | 2026-02-27 |
| AVO-037 | 清理嵌套 UID 并避免 user_intent 重复触发 | Done | 历史 `a:b:c` 事件不再参与正常排程链路并会被收敛/清理；同一 `user_intent` 只触发一次 AI 执行，不再每轮重复改动 | P0 | AVO-036 | 2026-02-27 |
| AVO-036 | 修复 intake 已托管 UID 重复导入与残留清理 | Done | intake 中出现已托管 UID 时不再重复导入 user-layer，且会被自动清理；同 UID 冲突不再导致源条目残留循环 | P0 | AVO-022, AVO-034 | 2026-02-27 |
| AVO-035 | 定时同步 payload 未变化时跳过 AI 调用 | Done | 每轮 `scheduled` 同步在输入完全一致时不再触发 AI 请求，并记录可观测审计事件 | P0 | AVO-034 | 2026-02-27 |
| AVO-034 | 规划输入去重（源编辑层与用户层不重复） | Done | AI payload 不再同时包含可编辑源事件与其 user-layer 镜像，避免重复收集造成重复日程 | P0 | AVO-022 | 2026-02-27 |
| AVO-033 | AI 描述改写时保留 user_intent | Done | AI 返回 description 并写入后，事件 `user_intent` 仍保持用户输入，不再在下一轮出现 `ai_change_skipped_no_intent` 循环 | P0 | AVO-031 | 2026-02-27 |
| AVO-032 | Stage 镜像 UID 冲突容错修复 | Done | 出现 `calobjects_by_uid_index` 冲突时不会导致整轮同步报错；系统会尝试修复冲突并继续后续事件处理 | P0 | AVO-022 | 2026-02-27 |
| AVO-031 | 源日历 user_intent 自动同步到 user-layer | Done | 在非 stage 日历修改 `user_intent` 后下一轮同步会将意图写入 user-layer 对应事件，并参与 AI 重排，不再被 `no_intent` 跳过 | P0 | AVO-022, AVO-020 | 2026-02-27 |
| AVO-030 | AI 修改条目默认展示数量精简 | Done | AI 修改条目默认展示最近 15 条，页面不再一次性铺满全部历史记录 | P2 | AVO-024 | 2026-02-27 |
| AVO-029 | AI 修改记录旧审计兼容回退展示 | Done | 历史记录缺少标题/时间/原因时仍可显示 UID、可读原因与身份信息，不再出现整页 `(Untitled)` 和 `- -> -` | P1 | AVO-024 | 2026-02-27 |
| AVO-026 | API 连通性测试回填模型下拉 | Done | 连通性测试后可加载并显示可用模型下拉列表；按钮文案改为“测试 API 连通性” | P1 | AVO-014 | 2026-02-27 |
| AVO-025 | AI 请求字节图三个月保留与自动刷新 | Done | 图表默认展示近 90 天数据并支持自定义天数；每 30 秒自动刷新；接口异常时可回退本地缓存显示 | P1 | AVO-023 | 2026-02-27 |
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
