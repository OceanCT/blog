---
title: "Agent学习笔记（八）多 Agent 协作：任务委派、交接与团队调度"
date: 2026-09-23 13:14:14
updated: 2026-09-23 13:14:14
description: "从职责、上下文和控制权出发，比较 LangGraph、OpenAI 与 Claude Agent SDK、AutoGen、CrewAI 的协作实现。"
categories: ["Agent 学习笔记"]
tags: ["Agent", "多Agent", "框架"]
---

一个调研助手可以自己搜索、写作，再检查报告。把它拆成研究者、作者和检查者以后，为什么可能有帮助？增加的实现又是什么？

先看一个具体需求：检查者只拿到草稿，看不见原始证据，就只能检查行文，很难核实吞吐数值；如果把所有搜索过程都交给它，又可能让检查上下文充满无关内容。多 Agent 协作首先需要安排每个参与者的职责、输入和工具，再决定结果交给谁。

## 多个 Agent 分开的是哪些东西

研究者可以使用搜索和读取工具，输出带出处的证据；作者根据证据起草；检查者按照要求核对结论。它们可以使用同一个底层模型，但拥有各自的指令、上下文和工具范围。

程序里有三个节点，并不意味着一定有三个 Agent。一个节点可能只检查字段是否为空；一个 Agent 则可以在自己的上下文中连续调用模型和工具，完成一项子任务。把这个子任务放进节点或子图，才连接到外围的执行编排。

如果自己实现，最初的版本可以是固定顺序。下面是流程伪代码：

```python
evidence = researcher.run(question)
draft = writer.run(question, evidence)
feedback = reviewer.run(question, evidence, draft)
```

检查者发现缺少实验条件以后，还需要把问题交回研究者补查，再修订草稿。这时要决定继续运行谁、传递哪些消息、最多修订几轮，以及由谁输出最终结果。

## 三种常见的交接方式

**固定流程**由程序决定先后顺序，例如“研究 → 写作 → 检查”，检查失败再进入补查分支。它适合步骤和验收规则已经明确的任务，流程可以直接写成函数调用，也可以交给图运行时管理。

**主 Agent 调用子 Agent**类似工具调用。主 Agent 发出一项范围明确的子任务，子 Agent 运行自己的循环并返回结果，主 Agent 继续负责汇总和最终回答。两个互不依赖的资料核对任务可以并行执行，但要避免同时修改同一份报告。

**控制权交接或团队调度**则需要选择下一位继续处理的参与者。控制权交接可以让专家接手后续对话；团队调度可以让成员按顺序发言，或者根据状态选择下一位。两者都要定义上下文传递和终止规则，否则容易把同一批信息反复讨论。

这些方式的主要差别是：结果是否返回原来的调用者，谁保有任务的控制权，以及下一位参与者看到多少历史。

## LangGraph 与 LangChain：把协作写进已有流程

LangGraph 可以把子 Agent 放进节点或子图，用状态和边规定交接。例如检查节点返回缺失证据，条件边决定回到研究节点还是结束。第五篇讲过的持久化与暂停机制可以继续用于这条流程。

LangChain 的多 Agent 模式也包括子 Agent 工具和 handoff 等组织方式。若已有 LangChain 工具循环，可以把一项独立分析封装成子 Agent 工具；若交接条件需要由程序明确控制，则可以进一步用 LangGraph 表达。[官方多 Agent 模式](https://docs.langchain.com/oss/python/langchain/multi-agent)。

这种方案的特点是我们直接安排消息与状态之间的关系。框架负责运行结构，证据怎样筛选、检查结果怎样改变流程，需要自己写清楚。

## OpenAI Agents SDK：区分工具式委派与 Handoff

OpenAI Agents SDK 可以把 Agent 暴露为工具。主 Agent 调用它获得结果，再继续负责最终回答；也可以通过 handoff 把后续处理交给另一个 Agent。两种机制对应不同的任务所有权。[官方 Orchestration 与 Handoffs](https://developers.openai.com/api/docs/guides/agents/orchestration)。

对调研助手，调用“核对实验条件”更适合作为子任务返回结果；若希望把用户接下来的提问都交给负责某个专题的专家，则可以考虑 handoff。选择哪一种，取决于专家完成工作后是否应该回到原来的主持者，而不只是要不要多写一个角色。

## Claude Agent SDK：在独立上下文里完成子任务

Claude Agent SDK 的 subagent 可以使用专门的指令和工具范围，在自己的会话中执行任务。中间的工具调用留在子 Agent 上下文里，最终消息返回主 Agent；独立任务还可以并行运行。[官方 Subagents 说明](https://code.claude.com/docs/en/agent-sdk/subagents)。

这适合把大量局部探索留在子任务中，例如分别读取两组实验记录，最后各自返回证据与结论。它与 OpenAI 的工具式委派都可以形成“主 Agent → 子任务 → 返回结果”的结构；具体差异在于运行环境、子 Agent 配置及上下文管理的接口。主 Agent 仍要检查返回结果是否完整，不能只凭一段摘要认定资料已经核实。

## AutoGen：以参与者与消息调度组织团队

AutoGen 的 AgentChat 提供 Agent 和 Team，Core 提供事件驱动的运行机制。`RoundRobinGroupChat` 让参与者按顺序运行；`SelectorGroupChat` 可以借助模型选择下一位参与者，也允许开发者提供选择逻辑。[项目架构](https://github.com/microsoft/autogen)、[参与者选择机制](https://microsoft.github.io/autogen/stable/user-guide/agentchat-user-guide/selector-group-chat.html)。

把研究者、作者和检查者放进团队以后，调度器选择接下来由谁处理消息。开发者需要规定终止条件，并检查选择器是否不断让同一角色重复工作。它适合用来理解团队调度与消息交互的设计。

AutoGen 官方仓库已进入维护模式，不再增加新功能，并建议新用户采用 Microsoft Agent Framework。实际选型时需要把这一维护状态计入考虑。[官方维护说明](https://github.com/microsoft/autogen)。

## CrewAI：从角色、任务与交付关系开始

CrewAI 的 Crew 以 Agent、Task 和协作过程组织工作。我们可以给研究者分配收集证据的任务，再让作者消费结果；顺序过程按任务顺序执行，层级过程引入负责协调的管理者。外围还可以使用 Flow 表达状态、事件触发和路由。[Crew 文档](https://docs.crewai.com/en/concepts/crews)、[Flow 文档](https://docs.crewai.com/en/concepts/flows)。

相对于直接定义图中的状态转移，这个入口更接近“谁负责什么、交付什么”。采用它时仍要检查任务之间实际传递的内容，而不是只写几个角色名称。研究者和检查者都可能漏看同一项实验条件，职责描述本身不能保证独立核验。

## 怎样选择协作实现

| 主要需要表达什么 | 可以考察的实现 | 核对重点 |
| --- | --- | --- |
| 固定顺序、条件回路与恢复 | 普通代码、LangGraph | 分支条件、共享状态、失败重跑范围 |
| 主 Agent 调用专家后继续汇总 | LangChain 子 Agent、OpenAI Agents SDK、Claude Agent SDK | 子任务输入、返回信息、上下文隔离 |
| 专家接手后续处理 | OpenAI Agents SDK handoff、LangChain handoff 模式 | 控制权与历史怎样转移 |
| 成员之间轮流或动态选择执行 | AutoGen Team | 下一位选择、消息可见范围和终止 |
| 按角色分配任务与交付物 | CrewAI Crew / Flow | 任务依赖、输出约定与协调者职责 |

LangGraph、LangChain、OpenAI Agents SDK、AutoGen 和 CrewAI 都有可阅读的开源实现；Claude Agent SDK 可以接入现成运行能力，但底层运行程序的可修改范围与这些库不同。开源实现有助于检查调度和消息传递，最终仍要用任务结果判断分工是否有效。

比较时可以给单 Agent 和多 Agent 相同资料与要求，检查报告是否遗漏实验条件、引用是否支持结论，并记录调用量、总耗时和人工返工。若检查者确实发现了单 Agent 漏掉的问题，就有了拆分的具体收益；若只是多写几段讨论，增加的调用没有改善结果，就没有必要维持这套分工。

[上一篇：记忆管理的实现方案](/blog/2026/09/23/agent-memory-implementations/) · [Agent 学习笔记专栏](/blog/columns/agent/)
