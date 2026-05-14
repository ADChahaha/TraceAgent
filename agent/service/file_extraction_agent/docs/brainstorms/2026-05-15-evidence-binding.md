# Brainstorm: 证据绑定 Prompt Gate

**日期**: 2026-05-15
**状态**: 可进入实现计划
**类型**: 架构/技术

## 摘要

目标是让模型“看到证据就绑上去”，不要等字段值完全确定后才回头找证据。当前最稳的做法是把证据绑定拆成硬状态机：`read` 暴露候选文本，`anchors/read/query_table` 暴露 inline id，`bind_evidence` 只能使用最近暴露的 inline id；同时要求每个 `reason` 先分析上一轮 action，再说明下一轮 action。

## 理解收敛

原始想法是改 prompt，让 `reason` 不再写成空泛的“等待下一步”，而是表达：

```text
上一轮 action 结果
  -> 是否支持某个 schema 字段
  -> 本轮准备调用的工具
```

其中 paragraph 证据必须走：

```text
read(.md)
  -> reason 判断是否可能支持字段
  -> anchors(.md) 获取 Sxxx inline id
  -> bind_evidence(...)
```

list/table 证据可以走：

```text
read(.list/.table) 或 query_table(.table)
  -> 直接使用刚暴露的 Ixxx/Rxxx
  -> bind_evidence(...)
```

## 分析

### 已采纳方案

- **把 prompt 变成动作衔接器**：`reason` 必须写“上一步看到什么，所以这一步做什么”，避免出现固定模板式空话。
- **用工具状态约束模型**：`anchors` 只能紧跟同一路径 paragraph `read`；`bind_evidence` 只能使用最近的 inline-producing 结果。
- **把 evidence 绑定前移**：只要当前 inline 可能支持字段，就先绑定到候选 evidence buffer；字段值和 enum decision 可以后面通过 `review_field/write_field` 定案。
- **允许连续绑定同一来源**：同一个 inline 来源可以连续执行多个 `bind_evidence`，便于同一句话支持多个字段；一旦插入非 bind 工具，旧 inline 上下文失效。

### 可选增强

- **evidence debt ledger**：在 prompt 中要求每次 `read` 后显式判断 `matched_fields`。如果非空，下一步必须取 inline 或绑定；如果为空，下一步才允许继续浏览。
- **tool result hint**：`read/anchors/query_table` 可以在返回里加只读 `next_action_hint`，提示“如果这段支持字段，下一步绑定这些编号”。这能降低模型漏绑率，但要避免把字段判断做进工具层。
- **候选优先，定案后置**：允许先绑定稍宽的候选证据，`review_field` 再过滤背景、重复和弱相关 selector。
- **失败恢复策略**：严格的 immediate gate 会让模型在插入别的工具后必须重读。这个成本可接受，因为证据绑定正确性比少一次 read 更重要。

## 建议

先保持当前硬 gate，不在工具里自动判断字段。模型负责判断语义，工具负责约束顺序和 selector 来源：

```text
read
  -> reason 判断字段可能性
  -> anchors/read/query_table 暴露 inline id
  -> bind_evidence 绑定最近 inline id
  -> review_field/write_field 定案
```

如果后续实验仍然出现漏绑，再考虑加 `matched_fields` 风格的 reason 格式要求或只读 `next_action_hint`。
