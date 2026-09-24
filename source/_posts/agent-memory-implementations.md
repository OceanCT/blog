---
title: "Agent学习笔记（七）记忆管理：会话、压缩与跨任务记忆"
date: 2026-09-23 13:14:14
updated: 2026-09-23 13:14:14
description: "区分会话保存、上下文压缩与跨任务记忆，比较 LangGraph、Letta、Mem0 及 OpenAI、Anthropic 的相关接口。"
categories: ["Agent 学习笔记"]
tags: ["Agent", "Memory", "框架"]
---

调研进行到第二天，助手需要接着读昨天的资料；对话变长以后，又不能把所有搜索结果原样放进下一次模型请求。与此同时，用户已经确认过“报告要注明实验条件”，我们希望下一项调研也能沿用这个要求。这些需求都常被称为 Memory，但实现时要分别处理。

第二篇已经从 MemGPT 和 Letta 解释了上下文与外部记忆的关系。这里把问题落到工程实现：保存什么、什么时候压缩、怎样重新读取，以及不同组件替我们完成哪一步。

## 先区分三种要保存的东西

| 对象 | 调研助手中的例子 | 后续怎样使用 |
| --- | --- | --- |
| 执行与会话状态 | 当前草稿、待执行调用、已有消息 | 恢复同一项任务，继续下一步 |
| 本次模型的上下文 | 当前问题、近期调用结果、历史摘要 | 直接进入下一次模型请求 |
| 跨任务记忆 | 已确认的报告偏好、项目约定 | 新任务开始时按需读取或检索 |

把消息写进数据库，只说明以后还能读到它。程序仍要选择哪些内容交给模型。如果把数据库里的全部历史重新发送，持久化问题解决了，上下文过长的问题依然存在。

同样，把十万字历史压成几千字摘要，只处理了当前上下文的体积。哪些偏好值得跨任务保存、旧要求如何被新要求替代，还需要另外定义。

## 会话保存：LangGraph Checkpointer 与 SDK Session

LangGraph 的 checkpointer 保存一个 thread 的图状态与执行进度，store 则用于跨 thread 的应用数据。我们可以把“这次读到了哪篇论文”放在执行状态，把“该用户要求标注实验条件”放在按用户组织的 store。写入 store 以后，模型节点还要读取需要的记录，构造本次输入。[官方持久化说明](https://docs.langchain.com/oss/python/langgraph/persistence)。

OpenAI Agents SDK 的 session 可以加载并保存会话历史，让连续调用沿用同一份记录；Claude Agent SDK 也提供会话续接能力。它们能减少维护历史记录的工作，但会话续接本身并没有定义哪些事实应成为另一项任务的长期记忆。[OpenAI 运行结果与状态](https://developers.openai.com/api/docs/guides/agents/results)、[Claude Agent SDK 会话](https://code.claude.com/docs/en/agent-sdk/sessions)。

选择这一层实现时，先确定想恢复的是消息历史，还是包含分支和待执行任务的运行状态。第五篇的检查点恢复解决后者，不能只用“支持记忆”概括这些差别。

## 上下文压缩：摘要怎样进入下一轮请求

一种容易自行实现的做法，是保留近期消息，把较早的历史交给摘要模型，再用摘要替换这段历史：

```text
压缩前：任务要求 + 早期搜索与讨论 + 最近几轮工具调用
                       ↓ 摘要模型
压缩后：任务要求 + 历史摘要       + 最近几轮工具调用
                       ↓
                  下一次模型请求
```

切分时要避免把工具调用和对应结果拆散。摘要还需要保留继续工作所需的信息，例如已经排除的方案、未解决的问题和证据出处。如果只压成“已完成调研，准备写报告”，字数虽然少了，模型却可能重新做一遍搜索。

### LangChain SummarizationMiddleware

LangChain 的摘要中间件在模型调用前检查触发条件，划分待总结历史与保留的近期消息，调用配置的摘要模型，再更新消息列表。触发阈值、保留范围和摘要提示词都可以配置。[短期记忆与摘要示例](https://docs.langchain.com/oss/python/langchain/short-term-memory)。

读实现时，还要注意摘要模型实际看到了多少旧消息。我们查看的[固定版本源码](https://github.com/langchain-ai/langchain/blob/3971e49d24e1b0eef9f2446011583d5510fbbf44/libs/langchain_v1/langchain/agents/middleware/summarization.py)中，`trim_tokens_to_summarize` 默认限制送入摘要模型的历史长度。因此，“待压缩历史”与“摘要模型实际读到的历史”可能并不相同；早期信息可能在生成摘要之前已经被裁掉。评估时应同时记录输入裁剪与摘要遗漏。

这种实现便于检查提示词、替换摘要模型和调整保留规则。它的效果依赖具体消息与任务，不能仅凭框架提供了一个 summarize 接口判断记忆质量。

### OpenAI 与 Anthropic 的 Compaction

OpenAI Responses 提供 compaction。返回的压缩上下文可以包含加密的 compaction 项，也可能保留其他历史项；应用应按接口要求把返回窗口用于后续请求。这个压缩项不是供人阅读的普通摘要，不能用“逐句检查摘要”同样的方式解释它保留了什么。[官方 Compaction 说明](https://developers.openai.com/api/docs/guides/compaction)。

Anthropic 也提供 compaction，支持按需压缩或在达到阈值时压缩，并允许相应模式下保留近期对话、调整摘要提示。具体模式的兼容条件需要按所用模型和接口核对。[官方 Compaction 说明](https://platform.claude.com/docs/en/build-with-claude/compaction)。

这类服务接口减少了应用自己组织压缩请求的工作。与开源摘要中间件相比，比较重点是能控制哪些输入和保留规则、能观察什么输出，以及压缩后能否继续完成任务。

## 跨任务记忆：谁决定写入和读取

### LangGraph Store：由应用组织读写策略

Store 提供存储与查询的位置。应用可以在任务开始时读取用户偏好，在结束时提取经过确认的结论，再写入对应记录。何时查询、怎样避免误记、什么时候替换旧记录，都由程序或我们安排的模型步骤决定。

如果已有数据库和明确的更新规则，这种方式容易融入现有服务。它也意味着记忆策略需要自己维护，存储接口不会自动判断一条结论是否值得长期保留。

### Letta：将记忆管理纳入有状态 Agent

Letta 的 memory blocks 将一部分持久信息放进 Agent 的上下文，块可以通过 API 或允许的工具更新。它适合解释“哪些信息持续可见、谁可以修改这些信息”这一类设计。更多外部内容则可以通过相应检索机制按需取回。[Memory blocks 文档](https://docs.letta.com/v1-sdk/memory/memory-blocks)。

与只提供存储接口相比，Letta 将 Agent 状态和记忆操作组织得更完整。代价是应用需要适应它的对象和生命周期。块的结构、共享与更新过程已在[第二篇](/blog/2026/09/14/agent-memory-memgpt-letta/)展开；这里关注的是是否需要采用这套运行方式。[Letta 开源仓库](https://github.com/letta-ai/letta)。

### Mem0：把记忆处理接到已有 Agent 外围

Mem0 提供独立的记忆层。应用可以提交交互内容，让它提取事实、决定或偏好并存储，后续按问题搜索相关记忆，再把结果加入模型输入。它有自运行的开源实现，也提供托管服务。[记忆写入机制](https://docs.mem0.ai/core-concepts/memory-operations/add)、[开源仓库](https://github.com/mem0ai/mem0)。

这种接法不要求替换整个 Agent 循环，适合已有运行系统、希望增加记忆处理的情况。仍要检查提取是否准确、旧事实怎样更新，以及删除是否覆盖所有副本。

### Anthropic Memory Tool：模型通过工具维护文件式记忆

Anthropic 的 Memory Tool 定义了文件式记忆操作。Claude 提出读取或修改请求，应用执行操作并返回结果；`/memories` 由应用映射到实际文件或数据库。数据保存在应用控制的存储中。[官方 Memory Tool 说明](https://platform.claude.com/docs/en/agents-and-tools/tool-use/memory-tool)。

它与应用主动调用 Mem0 的常见接法，在读写发起者上不同：前者让模型通过工具提出记忆操作，后者可以由应用在固定时机提交内容、调用检索。两者都需要考虑当前用户能读写哪些记忆，以及新旧内容如何保持一致。

## 怎样判断记忆真的有帮助

| 当前主要问题 | 可以比较的实现 |
| --- | --- |
| 同一任务中断后继续 | LangGraph checkpointer、SDK session 与对应运行状态 |
| 历史太长，下一轮放不下 | 自写摘要、LangChain 中间件、OpenAI/Anthropic compaction |
| 需要自己规定跨任务读写规则 | 数据库或 LangGraph store |
| 希望采用包含记忆操作的 Agent 运行方式 | Letta |
| 希望给已有 Agent 接上记忆层 | Mem0，或自定义记忆工具 |
| 希望 Claude 通过文件式接口管理记忆 | Anthropic Memory Tool 与应用存储 |

对日志压缩调研，可以用同一段历史比较不同策略：早期给出“只接受无损方案”，中途更正一次实验条件，最后要求据此写报告。检查压缩以后是否还遵守限制、采用更正后的数据、保留出处，再记录输入 token、额外调用和耗时。只比较摘要长度，会漏掉真正影响任务的损失。

跨任务记忆还要单独检查：新会话能否取回已确认的偏好，取消的偏好是否仍影响答案，不同用户的记录会不会混入。同一套记忆实现可能在这些检查上表现不同，选型需要回到具体任务。

[上一篇：资料检索与 RAG](/blog/2026/09/23/agent-open-source-components/) · [下一篇：多 Agent 协作的实现方案](/blog/2026/09/23/agent-multi-agent-implementations/) · [Agent 学习笔记专栏](/blog/columns/agent/)
