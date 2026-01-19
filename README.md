# avocado
A self-hosted CalDAV-based intelligent scheduler that aggregates external calendars and turns fuzzy tasks into dynamically planned events using AI.

## 项目名称
avocado
（基于 Radicale 的 WebDAV/ICS 聚合与智能任务调度系统）

---

## 1. 项目简介

avocado是一个自托管的智能日程与任务管理系统，以 **CalDAV** 作为唯一用户输入与输出接口，实现：

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

## 2. 核心设计约束（必须满足）

- ✅ 所有用户输入统一走 CalDAV
- ✅ 任务也必须以“日程格式”输入（VEVENT）
- ✅ 手机原生日历即可创建与编辑
- ❌ 不依赖客户端私有 API
- ❌ 不要求用户精确填写时间

---

## 3. 技术选型

### CalDAV Server（核心数据层）
- Radicale（轻量、纯协议、适合作为“日程数据库”、易于自动化/AI 接入）

---

## 4. 日历结构设计（强约定）

Radicale 中至少维护以下日历集合：

| 日历名 | 用途 |
|---|---|
| `schedule` | 固定日程 + GPT 已排期任务 |
| `inbox-tasks` | 用户创建的“未排期任务” |
| `external-feeds` | 外部 WebDAV / ICS 聚合结果（只读） |
| `ai-generated` | GPT 生成的摘要、规划、日志（可选） |

---

## 5. 日程与任务的统一建模方式

### 5.1 固定日程（Fixed Event）
- 标准 `VEVENT`
- 明确 `DTSTART / DTEND`
- 直接写入 `schedule`
- GPT 不主动改动（仅提示冲突）

### 5.2 任务（Flexible Task）
为保证手机端可创建，任务仍使用 `VEVENT` 表示，按以下约定：

- 创建在 `inbox-tasks` 日历中
- `CATEGORIES` 必须包含 `TASK`
- 不要求 `DTSTART`
- 必须提供“截止约束”（显式或隐式）

#### 任务元数据（推荐：DESCRIPTION 结构化块）
用户可在备注中手动填写，系统解析：
[AI_TASK]
deadline=2026-02-01 23:59
estimate=90m
window=weeknights
flex=soft
[/AI_TASK]
