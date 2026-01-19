# TODO.md
## 可维护 TODO 列表（按优先级）

---

## P0 – 基础可运行（MVP）

- [ ] 部署 Radicale（Docker）
- [ ] 创建基础日历：
  - [ ] `schedule`
  - [ ] `inbox-tasks`
- [ ] CalDAV 账号与权限配置
- [ ] 手机端验证：
  - [ ] 可创建事件
  - [ ] 多日历可见

---

## P1 – 外部日历聚合（WebDAV / URL-ICS 输入）

- [ ] WebDAV / URL-ICS 拉取模块
- [ ] VEVENT 解析
- [ ] source_id 设计（`source_url + UID`）
- [ ] 写入 `external-feeds`
- [ ] 标记只读来源事件（如 `X-SOURCE-URL` / `X-SOURCE-UID` / hash）

---

## P2 – 任务识别与解析（CalDAV 输入统一）

- [ ] 从 `inbox-tasks` 读取 `CATEGORIES` 含 `TASK` 的 VEVENT
- [ ] 解析 `[AI_TASK]` 块（deadline/estimate/window/flex）
- [ ] 字段校验与默认值策略
- [ ] 缺失字段交由 GPT 补齐（estimate/拆分建议）

---

## P3 – 空闲时段计算

- [ ] 拉取 `schedule` 已占用事件（未来 N 天）
- [ ] 用户可用时间配置（工作日/周末/夜间）
- [ ] 生成候选时间槽（粒度 15/30/60min 可配）
- [ ] 按任务 window 过滤候选槽

---

## P4 – 排期算法（工程优先，可解释）

- [ ] Earliest-Deadline-First 排序
- [ ] Best-Fit 放置（减少碎片）
- [ ] 超长任务拆分（按粒度或 GPT 建议）
- [ ] 写入 `schedule`（`CATEGORIES: TASK,SCHEDULED`）
- [ ] 原任务标记为 scheduled（如 `X-AI-STATE:SCHEDULED`）

---

## P5 – GPT 调度增强

- [ ] 用时智能估算（结合任务标题/描述/历史统计）
- [ ] 拆分建议（阅读/写作/复盘等）
- [ ] 生成可读摘要与执行建议
- [ ] 冲突原因解释文本（写入描述或 `ai-generated`）

---

## P6 – 动态重排（增量）

- [ ] 变更检测（ETag / hash / last-sync）
- [ ] 受影响任务集合计算（局部重排）
- [ ] 锁定机制：`X-AI-LOCK:1` 不移动
- [ ] 任务重新落槽（保持稳定性与最小扰动）

---

## P7 – 可观测性与安全

- [ ] 结构化日志（任务→排期→调整）
- [ ] dry-run 模式（仅输出计划不写入）
- [ ] 回滚机制（保存旧事件快照或变更日志）
- [ ] CalDAV 最小权限、密钥管理、网络暴露策略（可配合 Tunnel）

---

## 终态定义

- [ ] 用户只需在手机日历里创建：
  - 固定日程：明确时间
  - 任务：只写截止/用时（可模糊）
- [ ] 系统可自动排期、可解释、可动态调整，并保持 CalDAV 兼容
