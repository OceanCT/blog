---
title: "Agent学习笔记（五）从 LangGraph 理解 Agent 框架怎样设计"
updated: 2026-09-15 10:55:27
date: 2026-09-15 10:51:30
description: "从调研助手拆解 Agent 框架的状态、调度、恢复、人工介入与记忆，并比较 LangChain、CrewAI 和 AutoGen 的组织方式。"
categories: ["Agent 学习笔记"]
tags: ["Agent", "LangGraph", "框架"]
---

我们已经讨论了 Agent 怎样规划、保存记忆和调用工具。实际写代码时，还会遇到 LangGraph、LangChain、CrewAI、AutoGen 这些名字。它们与 ReAct、MemGPT、Gorilla 有什么关系？如果论文中的方法已经讲清楚了，框架还要解决什么？

我们继续做那个日志压缩调研助手：它需要寻找资料、读取原文、比较指标、写出报告，并在得到确认后交付。一次顺利的演示不难组织；真正麻烦的是读到一半服务超时、用户第二天才回复、两条检索同时返回，或者报告已经写成功但程序没收到响应。框架的作用，要从这些具体的执行问题看。

## 先把方法、模型、框架和评测放到各自的位置

ReAct 描述一种根据观察继续选择行动的过程。我们可以让模型先提出搜索调用，收到结果后再决定读取哪篇资料。Gorilla 研究怎样训练模型，把需求转成 API 调用。MemGPT 讨论有限上下文与外部记忆如何配合。它们提供可以被实现的机制与研究证据，范围并不相同。

LangGraph 则提供组织程序执行的抽象：哪些数据是当前状态，哪段代码现在运行，运行后进入哪里，以及怎样保存进度。我们可以在这样的运行结构里实现 ReAct，也可以放进一个完全按固定顺序执行的流程。BFCL 是 benchmark（评测基准），用题目与检查规则测量工具调用能力；它的主要贡献是评测设计，没有规定 Agent 应采用哪套运行架构。框架执行成功、模型给出正确答案、评测通过，是需要分别观察的结果。

| 对象 | 在调研助手里回答的问题 |
| --- | --- |
| 模型与训练方法 | 能否理解需求、选择工具、生成有依据的内容？ |
| Agent 方法 | 怎样组织观察、行动、反思和记忆使用？ |
| 框架与运行时 | 怎样调度代码、传递状态、暂停并恢复？ |
| 工具及协议 | 怎样访问搜索、文件和外部服务？ |
| Benchmark（如 BFCL） | 用什么测试题和判分规则检查能力？ |

这张表按职责划分，不表示每个项目只属于其中一格。一个框架可以附带预置的 Agent 循环、记忆组件和评测接口；用到这些组件，也仍要理解它们各自负责什么。前面的机制可回看站内的[规划篇](/blog/2026/09/14/agent-planning-react-reflexion-lats/)、[记忆篇](/blog/2026/09/14/agent-memory-memgpt-letta/)和[工具调用篇](/blog/2026/09/14/agent-tools-toolformer-gorilla-bfcl/)。

## 从一个自己写的循环开始

假设先不用框架，我们可以写一个这样的程序。这里是说明流程的伪代码：

```python
while budget_remaining():
    context = build_context(task_state, relevant_memory)
    response = model(context, available_tools)
    if response.is_final:
        return response.answer
    for call in response.tool_calls:
        validate_arguments_and_permission(call)
        result = execute(call)
        task_state.record(call, result)
```

这个循环已经可以表达一种工具型 Agent。工具执行结果进入状态，下一次模型调用读到结果，再选择行动。程序中的循环控制、校验和记录，都由宿主代码完成。

任务变长以后，就会出现新的需求。`task_state` 只在内存里，进程退出后怎样继续？用户暂时不批准报告，是否一直占着进程等待？两个读取任务并行返回，怎样合并证据？执行超时以后，重跑哪一段才合理？我们当然可以继续自己写，但必须定义清楚状态、调度和恢复之间的约定。

LangGraph 把这些约定做成可复用的运行结构。它支持显式定义图，也提供保留普通函数与控制流写法的 Functional API；后者通过入口函数与任务边界接入相同运行时。因此，理解框架的重点在执行语义，画出流程图只是其中一种表达方式。[官方说明：LangGraph 概览](https://docs.langchain.com/oss/python/langgraph/overview)、[Functional API](https://docs.langchain.com/oss/python/langgraph/functional-api)。

## LangGraph 的图，到底由什么组成

我们先按自己的任务设计一条流程：

```text
接收需求 → 收集证据 → 起草报告 → 检查证据
                ↑                  │
                └── 缺资料且有预算 ──┘
                                   │ 通过
                                   ↓
                               等待用户审阅
                                /       \
                              批准      要求修改
                               ↓          ↓
                              交付       修改草稿
```

这张流程对应几个程序对象。**State** 是当前状态，**Node** 是接收状态并执行工作的函数，**Edge** 规定接下来运行哪个节点。节点可以调用模型、读取文件，也可以只检查一个布尔值。一个节点并不天然等于一个 Agent。[这些对象的接口定义见官方 Graph API](https://docs.langchain.com/oss/python/langgraph/graph-api)。

### State：程序需要记住什么

假设我们为调研任务保存这些字段：

```text
question         用户要比较什么
constraints      必须无损、允许的数据范围、时间预算
sources          已找到的资料及来源地址
evidence         从资料中提取的事实和出处
unresolved       尚未解决的比较问题
draft            当前报告
revision         当前草稿版本
remaining_steps  还允许执行多少步
```

这些字段组成应用状态，不意味着每次都要全部塞进模型输入。比如完整 PDF 可以保存在文件存储里，状态只记资料 ID 和提取结果；起草报告时，代码再挑选相关证据构造上下文。

这样，“存了什么”与“模型这一次看到了什么”就分开了。前者服务于程序继续运行，后者受上下文窗口、任务相关性与权限约束。状态里还有多少预算，应由程序更新和检查，不能让模型随意把计数改大。

### Node：一段工作返回哪些变化

`collect` 节点可以把新证据写入 `evidence`；`draft` 节点读取证据后返回新报告；`check` 节点返回尚缺的出处。节点只需提交自己产生的更新，其余状态可以保留。

以我们自己的证据合并规则为例，旧状态已有论文 A 的一条事实，两个读取节点分别返回论文 B、C 的事实。若简单使用“后来的列表覆盖前面的列表”，就会丢内容。我们需要规定合并方式，例如按“资料 ID + 页码 + 事实 ID”去重后追加。

LangGraph 把字段更新的合并函数称为 **reducer**。默认更新通常覆盖旧值；需要累积的字段可指定合并函数。reducer 只执行我们定义的规则：把两份列表拼起来，并不会判断两篇论文是否矛盾，也不会自动辨别同一实验的不同版本。[状态更新与 reducer 的说明](https://docs.langchain.com/oss/python/langgraph/graph-api#reducers)。

### Edge：下一步由谁决定

固定边适合表达确定的先后关系，例如读取完成后做提取。条件边根据状态选择下一节点，例如还有未解决问题且预算充足就继续查资料，否则起草或报告缺口。

模型也可以参与决定：检查节点让模型提出缺少哪些证据，路由代码再决定是否进入搜索节点。业务约束由代码落实，例如剩余步数为零时终止补充检索。这样可以保留模型判断任务内容的灵活性，同时明确程序允许哪些转移。

图可以包含循环，所以不能只把 LangGraph 当成 DAG 调度器。DAG 是有向无环图，而“搜索后检查，缺证据就再搜索”需要回路。另一方面，画了回路就要有退出条件；递归步数上限可以作为保护，任务本身仍应定义何时成功、何时停止并交代未完成项。

## 并行节点怎样交换数据

假设已经拿到两篇论文地址，读取 A 与读取 B 互不依赖，就可以放到同一执行步骤中并行运行。两者完成后，把更新合并到状态，下一步的比较节点才读取这些结果。

LangGraph 的底层运行时采用受 Pregel 启发的分步执行方式。每一步先选中待运行节点，再执行它们，最后应用更新；同一步中产生的更新，要到下一步才对其他节点可见。这种执行步骤称为 **super-step**。它为“这次计算读到哪个版本的数据”提供了明确边界。[官方运行时说明](https://docs.langchain.com/oss/python/langgraph/pregel)。

对我们的调研助手，这意味着不能指望读取 A 的节点执行到一半时，读取 B 的节点就自动看到 A 刚写出的状态。如果 B 必须消费 A 的结果，应建立先后依赖；如果二者只是在最后共同供比较节点使用，则应设置汇合关系，并定义并发写入字段的合并规则。

这个框架也不会替我们判断业务上的独立性。两次只读请求可能适合并行，两次修改同一篇报告则可能冲突。图的调度结构与外部资源的并发控制，都需要在设计时交代清楚。

## 保存进度以后，怎样继续一项任务

**Checkpointer** 负责保存图执行的检查点。检查点包含某个阶段的状态与继续执行所需的信息；`thread_id` 用来把同一执行上下文的历史串起来。这里的 thread 是逻辑标识，不是操作系统线程，也不是用户的权限凭证。

在我们的应用里，一项持续调研可以对应一个 thread。用户第二天回来，服务先验证他能访问这项任务，再使用同一个标识继续执行。启动一项独立调研，则使用另一个标识，避免报告与调用历史混在一起。

LangGraph 按 super-step 保存检查点，也会记录同一步内已完成节点的写入。如果读取 A 成功、读取 B 失败，恢复时可以复用已记录的 A 结果，重试未完成部分。[检查点与 pending writes 的机制](https://docs.langchain.com/oss/python/langgraph/checkpointers)。

保存后是否能跨进程恢复，还取决于存储实现。`InMemorySaver` 将数据放在当前进程内存中，进程退出后就会丢失；文件型 SQLite 或数据库型存储才能提供相应的持久保存能力。只在代码里加了一个 saver 名称，不能据此宣称系统已经具有重启恢复能力。[持久化配置与内存存储边界](https://docs.langchain.com/oss/python/langgraph/persistence)。

### 恢复执行为什么仍可能重复写入

假设交付节点依次完成两件事：向文档服务创建报告，然后把返回的文件 ID 保存到状态。文档服务已经创建成功，但程序在保存状态前崩溃。恢复时，检查点里没有成功记录，重跑节点就可能再创建一份。

问题出在两个系统之间：外部文档写入与本地检查点提交没有天然组成一个原子事务。对这个具体场景，我们可以给每次交付分配稳定的幂等键，例如“任务 ID + 草稿版本 + 交付动作”。服务端识别重复键并返回同一结果；如果接口不支持幂等，就需要通过业务标识查询已有结果，或设计操作记录与人工核对流程。

节点拆分、任务结果保存可以缩小重放范围，却不能消除所有外部写入窗口。设计恢复机制时，应问清楚：哪一段代码可能再跑一次，重复之后会发生什么，以及怎样查明真实结果。图完成记录是执行证据，外部系统中的最终状态仍要核对。

## 人工介入怎样成为可恢复的步骤

报告写好之后，等待审阅可以使用 `interrupt(payload)`。它把需要审阅的内容交给调用端，并暂停图的执行。后续调用带上相同的 `thread_id` 和 `Command(resume=...)`，恢复值会成为该次 `interrupt` 的返回值，程序据此继续分支。

一个容易漏掉的细节是：恢复时，包含 interrupt 的节点会从头运行，interrupt 前的代码可能再次执行。因此，在同一个审阅节点中先“发送一次通知邮件”，再 interrupt，恢复后可能再次发送邮件。需要把这样的副作用放到清楚的执行边界，并处理重复执行。[官方 interrupt 与恢复规则](https://docs.langchain.com/oss/python/langgraph/interrupts)。

在我们的应用设计中，待审批记录还应包含报告版本、目标位置与内容摘要。用户批准的是这份具体报告；如果中途草稿被替换，就应该重新确认授权是否仍适用。传入一个 `True` 只代表程序收到了值，用户身份、资源权限和版本匹配要由应用服务验证。

## 一段能直接运行的小例子

下面用固定材料代替搜索与模型生成，观察“收集 → 起草 → 暂停 → 恢复 → 分支”的完整运行过程。它不会发布文件，批准后只改变状态。这样可以先把框架行为看清楚，再替换具体节点里的工作代码。

这段示例已使用 `langgraph==1.2.11` 验证暂停、批准和拒绝分支。保存为 `agent_graph_demo.py` 后运行：

```bash
python -m pip install "langgraph==1.2.11"
python agent_graph_demo.py
```

```python
from typing import TypedDict
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command, interrupt


class State(TypedDict):
    question: str
    evidence: list[str]
    draft: str
    approved: bool
    status: str


def collect(state: State):
    # 本地固定材料，用来观察执行流程，不调用搜索服务。
    return {"evidence": ["报告应同时列出压缩后占比和处理耗时。"]}


def draft(state: State):
    return {"draft": state["question"] + "\n" + "\n".join(state["evidence"])}


def review(state: State):
    decision = interrupt({"draft": state["draft"], "action": "review"})
    return {"approved": decision is True}


def route(state: State):
    return "accepted" if state["approved"] else "rejected"


def accepted(state: State):
    return {"status": "approved_for_delivery"}


def rejected(state: State):
    return {"status": "needs_revision"}


builder = StateGraph(State)
for name, node in [
    ("collect", collect), ("draft", draft), ("review", review),
    ("accepted", accepted), ("rejected", rejected),
]:
    builder.add_node(name, node)
builder.add_edge(START, "collect")
builder.add_edge("collect", "draft")
builder.add_edge("draft", "review")
builder.add_conditional_edges("review", route, {
    "accepted": "accepted", "rejected": "rejected",
})
builder.add_edge("accepted", END)
builder.add_edge("rejected", END)
graph = builder.compile(checkpointer=InMemorySaver())

config = {"configurable": {"thread_id": "report-demo"}}
paused = graph.invoke({"question": "比较日志压缩方案"}, config)
print("等待审阅：", paused["__interrupt__"][0].value)
# 演示代码模拟一次批准；真实服务由通过身份验证的审阅请求传入。
finished = graph.invoke(Command(resume=True), config)
print("状态：", finished["status"])
```

第一次 `invoke` 运行到 `review` 时暂停，返回待审阅草稿。第二次使用相同配置恢复，`review` 得到批准值，把 `approved` 写进状态，条件边选择 `accepted`，最终状态为 `approved_for_delivery`。换一个新 `thread_id` 无法定位原来的待审阅任务。

把演示中的 `Command(resume=True)` 改成 `Command(resume=False)`，就会走拒绝分支并返回 `needs_revision`。这个例子把拒绝后的修改留给下一次请求；前面完整调研流程中的自动修改回路，还需要增加反馈字段、修改节点和修订次数上限。

这里没有模型调用，所以它首先验证的是一个可暂停的工作流。把 `collect` 换成真实的检索与读取，把 `draft` 换成根据证据生成报告，再加入根据工具结果决定后续动作的节点，才逐步形成我们要的 Agent。`compile` 把节点、边和存储配置组织成可执行图，它不会训练模型，也不会替我们补齐节点内部的业务逻辑。

## 框架中的记忆，与 MemGPT 是什么关系

状态保存与模型记忆很容易被混为一谈。假设报告进度保存在数据库里，但下一次调用模型时，我们只传入一句“继续”。模型并不会自动访问那份数据库；程序仍要读取相关数据并构造上下文，或者给模型提供查询工具。

LangGraph 提供两种相互补充的持久化接口：checkpointer 面向一个 thread 的图状态，store 面向跨 thread 的应用数据。我们可以把“这项任务读到了第几篇论文”留在检查点里，把经过确认的“用户偏好中文报告”放在按用户划分的 store 中。短期与长期在这里主要描述使用范围，不能直接理解为只保存几分钟或几个月。[官方持久化接口对比](https://docs.langchain.com/oss/python/langgraph/persistence)。

MemGPT 则进一步讨论模型上下文有限时，哪些信息留在当前上下文、哪些放到外部存储，以及怎样通过调用管理信息。LangGraph 提供的存储接口可以承载我们实现的记忆策略，但安装它不会自动得到 MemGPT 的分层管理过程。

例如，我们可以在每次模型节点执行前，按当前问题从 store 查询相关偏好和事实，选择少量结果与任务状态一起进入上下文；任务结束后，再经过规则或模型提议与校验，决定更新哪些记忆。这里的选择、归纳、过期与删除传播都属于应用的记忆策略。框架提供读写位置与调用时机，具体记什么仍需设计。[LangGraph 记忆概念说明](https://docs.langchain.com/oss/python/concepts/memory)。

## 常见框架为什么看起来很不一样

理解了一套完整运行过程，再比较其他框架就容易一些：先看它让开发者以什么对象表达工作，再看运行时怎样处理状态和控制权。下面按 2026 年 9 月 15 日查阅的官方文档介绍，具体接口应随项目锁定的版本核对。

### LangChain 与 LangGraph：便捷入口和运行结构

在当前 LangChain 中，`create_agent` 可以根据模型、工具和提示词建立 Agent，减少手写常见循环的工作。其 Agent 构建在 LangGraph 之上，可以使用底层的持久化与人工介入等能力。

因此，同一个调研助手可以先从 LangChain 的 Agent 入口开始；当我们需要明确控制“收集、检查、等待审阅、交付”之间的状态转移时，再直接使用 LangGraph 组织图。LangChain 也允许通过 middleware 调整运行行为，不能简单按“简单任务用一个、复杂任务只能用另一个”划死边界。需要比较的是现有抽象能否清楚表达我们的流程。[LangChain 官方概览](https://docs.langchain.com/oss/python/langchain/overview)。

### CrewAI：从角色、任务与团队组织工作

CrewAI 的 Crew 以 Agent、Task 和协作过程组织任务。例如我们可以定义资料研究者与报告作者，让前者完成证据整理，后者消费结果写报告。顺序过程按照任务顺序执行；层级过程引入负责协调的管理者。

这种入口接近“谁负责什么、交付什么”。但角色名称本身不会使模型获得专业知识，“审稿人”也不保证发现错误。我们仍要给它来源、检查标准与可用工具，并检查任务输出。[CrewAI 的 Crew 定义与过程](https://docs.crewai.com/en/concepts/crews)。

CrewAI 同时提供 Flow，用状态、事件触发和路由组织应用过程。因而可以在外围 Flow 中落实收集、审批和交付顺序，再把需要协作的部分交给 Crew。不能把它概括成只有几个角色互相聊天。[CrewAI Flows](https://docs.crewai.com/en/concepts/flows)。

### AutoGen：从消息交互和 Agent 运行时组织工作

AutoGen 的 AgentChat 面向单 Agent 和多 Agent 对话应用，底层 Core 提供事件驱动的 Agent 运行机制。可以把资料研究者的结果作为消息交给报告作者，再让检查者返回反馈；开发者需要安排参与者、消息流向和结束条件。

在调研任务里，这种表达方式让“谁接到什么消息、由谁继续处理”更突出。若采用轮流发言或选择下一位参与者的协作方式，就应明确谁有权结束任务、哪些信息需要共享，以及怎样避免重复讨论。AutoGen 的不同版本也有接口差异，旧版 0.2 示例不能直接当成当前 AgentChat 的用法。[AutoGen 官方分层与版本迁移入口](https://microsoft.github.io/autogen/stable/index.html)。

| 入口 | 首先组织的对象 | 我们的调研任务可以怎样表达 |
| --- | --- | --- |
| LangGraph | 状态、节点、转移 | 把收集、检查、审阅与交付明确连接 |
| LangChain Agent | 模型、工具与 Agent 循环 | 配置调研工具，并在循环前后加入控制逻辑 |
| CrewAI | Agent、Task、Crew，外围可用 Flow | 规定研究与写作职责，组织任务和交付顺序 |
| AutoGen AgentChat / Core | 对话参与者、消息与事件 | 把证据、草稿与反馈在参与者之间传递 |

这些是理解入口，不是互斥的能力清单。图里可以放多 Agent，角色型框架也可以运行固定流程。选型要拿同一任务验证：中断后能否接着做、失败后哪段重跑、状态是否便于检查、能否限制成本，而不是比较谁的角色名称更多。

## 如果自己设计一个完整框架，需要哪些部分

回到我们的调研助手，可以把运行系统分成几段相连的工作。接到请求后，服务验证用户与任务范围，建立或加载任务状态；运行时据此选择下一节点。模型节点构造上下文、接收模型输出，工具节点检查并执行调用；结果进入状态，再触发下一步。

在这条路径旁边，需要持久化与事件记录。前者支持恢复，后者让用户看到“正在读取哪篇资料”，也让开发者能定位一次失败。一个可追踪的调用记录可以包含任务 ID、节点名、调用 ID、耗时、错误类型和结果引用；不必为了可观测性把全部敏感正文复制进日志。

具体到服务边界，我们还需要自行决定以下事项：

| 部分 | 必须作出的设计决定 |
| --- | --- |
| 模型适配 | 如何统一消息与调用格式，如何处理超时和结构化输出错误 |
| 工具执行 | 哪些工具可用，参数与权限怎样检查，哪些动作支持重试 |
| 调度控制 | 怎样表达依赖、并行、预算、取消与终止 |
| 状态与恢复 | 保存什么，怎样识别任务，如何处理重复执行与版本变化 |
| 上下文与记忆 | 每次给模型看什么，哪些事实跨任务保存，何时删除 |
| 人工介入 | 用户在批准哪个对象和版本，恢复请求怎样验证 |
| 观察与验收 | 怎样还原执行过程，怎样检查外部结果和任务质量 |

不同框架已经实现了其中不同范围的公共部分，业务实现可以复用它们。数据库、服务端认证、工具凭据管理、任务队列和执行隔离等基础设施仍需按部署方式接入，使用一个框架的库并不等于整个服务已经具备这些能力。

尤其要把“运行得可恢复”与“回答得正确”分开验证。一次任务可以完整保存每个错误结论，也可以成功恢复后继续调用错误工具。证据是否支持结论、报告是否满足用户要求，需要回到前面讨论的评测与验收标准。

## 面试时可以沿着哪些问题继续讲

**“LangGraph 与 ReAct 有什么关系？”** ReAct 描述根据观察继续行动的模式，LangGraph 可以用模型节点、工具节点和回路实现这种模式。实现还需要规定上下文构造、工具执行和退出条件，同一运行时也可以承载其他策略。

**“State、上下文和长期记忆为什么要分开？”** State 记录程序运行所需的数据，上下文是本次实际传给模型的信息，长期记忆保留跨任务可复用的内容。保存数据以后还需要选择和读取，三者不必一一对应。

**“有 checkpointer 就不会重复执行了吗？”** 恢复依据已保存的进度，尚未记录完成的代码可能重跑。外部写入与检查点之间存在失败窗口，仍需稳定的操作标识、幂等或结果核对。内存型 checkpointer 也无法提供跨进程恢复。

**“多 Agent 与多个节点有什么区别？”** 节点是工作函数，可以只是字段校验。一个子 Agent 往往包含自己的模型循环、上下文和工具选择，可以作为节点或子图被调用。增加节点不等于增加独立决策者。

**“什么时候自己写循环，什么时候用框架？”** 可以先列出真实需求。如果任务很短、失败后允许完整重来，普通程序可能已经足够清楚；如果存在多步状态、人工等待、并行与恢复需求，就应比较框架能否减少这些机制的维护成本。这个选择应通过任务样例和失败演练验证。

对我们的调研助手，第一轮演练可以很具体：两篇资料读取时让一篇超时，检查另一篇结果是否保留；草稿暂停后重新启动服务，检查能否恢复同一任务；拒绝审阅，检查是否停止交付；模拟交付响应丢失，检查是否重复创建报告。框架是否适合这项工作，会在这些运行结果里体现出来。

[上一篇：工具调用如何学会，又如何验收](/blog/2026/09/14/agent-tools-toolformer-gorilla-bfcl/) · [Agent 学习笔记专栏](/blog/columns/agent/)
