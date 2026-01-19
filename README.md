# avocado

A self-hosted, CalDAV-based intelligent scheduler that aggregates external calendars and turns fuzzy tasks into dynamically planned events using AI.

**Language:** 中文 | [English](README.en.md)

---

## 项目名称

**avocado**（基于 Radicale 的 WebDAV/ICS 聚合与智能任务调度系统）

---

## 项目简介

avocado 是一个自托管的智能日程与任务管理系统，以 **CalDAV** 作为唯一用户输入与输出接口，实现：

- 聚合多个 **WebDAV / URL-ICS** 外部日历
- 允许用户通过手机原生日历直接创建日程或任务
- 将“不定时段任务”交由 GPT 自动排期
- 支持动态重排、拆分任务、冲突感知
- 对外提供标准 **CalDAV / WebDAV / ICS** 访问

系统定位：

- **CalDAV = 统一事实源（Single Source of Truth）**
- **WebDAV / ICS = 只读输入**
- **GPT = 调度与决策引擎**

---

## 核心设计约束（必须满足）

- ✅ 所有用户输入统一走 CalDAV
- ✅ 任务必须以“日程格式”输入（`VEVENT`）
- ✅ 手机原生日历即可创建与编辑
- ❌ 不依赖客户端私有 API
- ❌ 不要求用户精确填写时间

---

## 技术选型

### CalDAV Server（核心数据层）

- **Radicale**（轻量、纯协议、适合作为“日程数据库”、易于自动化/AI 接入）

---

## 日历结构设计（强约定）

Radicale 中至少维护以下日历集合：

| 日历名 | 用途 |
| --- | --- |
| `schedule` | 固定日程 + GPT 已排期任务 |
| `inbox-tasks` | 用户创建的“未排期任务” |
| `external-feeds` | 外部 WebDAV / ICS 聚合结果（只读） |
| `ai-generated` | GPT 生成的摘要、规划、日志（可选） |

---

## 日程与任务的统一建模方式

### 固定日程（Fixed Event）

- 标准 `VEVENT`
- 明确 `DTSTART / DTEND`
- 直接写入 `schedule`
- GPT 不主动改动（仅提示冲突）

### 任务（Flexible Task）

为保证手机端可创建，任务仍使用 `VEVENT` 表示，按以下约定：

- 创建在 `inbox-tasks` 日历中
- `CATEGORIES` 必须包含 `TASK`
- 不要求 `DTSTART`
- 必须提供“截止约束”（显式或隐式）

#### 任务元数据（推荐：DESCRIPTION 结构化块）

用户可在备注中手动填写，系统解析：

```
[AI_TASK]
deadline=2026-02-01 23:59
estimate=90m
window=weeknights
flex=soft
[/AI_TASK]
```

也可支持等价的 `X-AI-*` 字段（机器友好，可选）：

- `X-AI-TYPE: TASK`
- `X-AI-DEADLINE`
- `X-AI-ESTIMATE-MIN`
- `X-AI-WINDOW`
- `X-AI-FLEX`

---

## 任务调度与排期规则

### 基本原则

- 固定日程 > 已排期任务 > 未排期任务
- `deadline` 默认为硬约束（除非 `flex=soft`）
- 用户手动移动/标记的事件可被视为锁定（`X-AI-LOCK:1`）

### 排期输出

调度器会在 `schedule` 中创建新的 `VEVENT`：

- 含明确 `DTSTART / DTEND`
- `CATEGORIES: TASK,SCHEDULED`
- `X-AI-ORIGIN-UID` 指向原任务（inbox 事件）
- 支持拆分为多个子事件

---

## 动态调整机制

触发增量重排的情况：

- 用户新增/修改固定日程
- 用户修改任务 deadline / estimate
- GPT 更新用时预估
- 外部 ICS 更新占用时间

原则：

- 只重排受影响任务
- `X-AI-LOCK:1` 的事件不移动

---

## 系统组件划分（建议仓库结构）

```
repo/
├── caldav/        # Radicale 配置 / Docker
├── aggregator/    # WebDAV / ICS → CalDAV（external-feeds）
├── scheduler/     # 任务识别 + 排期逻辑（inbox → schedule）
├── ai/            # GPT：估时 / 拆分 / 摘要 / 决策建议
├── config/
│   ├── calendars.yaml
│   └── rules.yaml
└── docs/
```

---

## 用户端使用方式（无学习成本）

- 手机原生日历订阅/登录 CalDAV
- 新建事件：
  - 有明确时间 → 固定日程（写入 `schedule`）
  - 无明确时间 + 在备注写截止/用时 → 任务（写入 `inbox-tasks`）
- 系统自动排期：任务会在 `schedule` 中出现一个或多个占用时段

---

## 非目标（明确不做）

- ❌ 自定义前端日历 UI
- ❌ 替代系统 To-Do App
- ❌ 强制用户精确输入参数
