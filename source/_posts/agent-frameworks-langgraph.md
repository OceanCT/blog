---
title: "Agent学习笔记（五）模型接入与执行编排：从 SDK 到 LangChain、LangGraph"
date: 2026-09-15 10:51:30
updated: 2026-09-23 13:45:24
description: "从直接 HTTP 调用解释 API、SDK 与兼容接口，再比较工具调用循环及 LangGraph 的状态、并行、暂停和恢复。"
categories: ["Agent 学习笔记"]
tags: ["Agent", "LangGraph", "SDK", "框架"]
---

模型已经能够返回工具名称和参数，我们也会写函数执行这些请求，那么为什么还需要 Agent 框架？要回答这个问题，可以先把一次调用完整地走通，再看任务变长以后，程序还要承担哪些工作。

我们想做一个日志压缩调研助手：读取论文和实验记录，比较吞吐与压缩率，最后形成报告。模型负责根据已有信息提出下一步，程序负责执行工具、传回结果，并控制流程。模型接入解决双方怎样交换消息，执行编排解决这些调用怎样连续运行、失败以后怎样继续。

## 从 HTTP 请求看 SDK 到底做了什么

先不使用框架，也不使用 SDK。模型服务提供一个 API 地址，程序按约定发送请求，就能获得响应。以 DeepSeek 的 Chat Completions 接口为例，配置好 `DEEPSEEK_API_KEY` 后，可以直接发送：

```bash
curl https://api.deepseek.com/chat/completions \
  -H "Authorization: Bearer $DEEPSEEK_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "deepseek-flash",
    "messages": [
      {"role": "user", "content": "调研日志压缩方案时，应比较哪些实验条件？"}
    ],
    "stream": false
  }'
```

这里，URL 决定请求发给哪个服务、调用哪个接口；请求头携带身份凭据和内容类型；JSON 中的 `model` 指定模型，`messages` 提供对话。服务端返回 JSON，程序再从响应里读取回答。[DeepSeek 官方调用示例](https://api-docs.deepseek.com/)。

如果改用 OpenAI 的 Python SDK，同样的调用可以写成：

```python
import os
from openai import OpenAI

client = OpenAI(
    api_key=os.environ["DEEPSEEK_API_KEY"],
    base_url="https://api.deepseek.com",
)
response = client.chat.completions.create(
    model="deepseek-flash",
    messages=[
        {"role": "user", "content": "调研日志压缩方案时，应比较哪些实验条件？"}
    ],
    stream=False,
)
print(response.choices[0].message.content)
```

SDK 运行在我们的程序里。它接收函数参数，拼好请求路径和请求头，把数据序列化成 JSON，发送请求，再把响应解析成便于访问的对象。连接、超时、重试和流式读取也可以由 SDK 封装。模型推理仍在服务端进行。

```text
直接调用：应用代码 ── HTTP 请求 / JSON 响应 ── 模型服务
使用 SDK：应用代码 ── SDK ── HTTP 请求 / JSON 响应 ── 模型服务
```

所以 SDK 可以省掉一部分网络通信代码，也可以被跳过。上面两段代码展示的是同一个 API 调用的两种写法，尚未加入工具执行或多轮 Agent 循环。

### 为什么 OpenAI SDK 可以调用 DeepSeek

SDK 按一套 API 约定组织请求、解析响应。只要目标服务提供兼容的接口，它就能继续工作。上面的 `base_url` 指向 DeepSeek，因此请求直接发往 DeepSeek，使用的也是 DeepSeek 的密钥和模型。

DeepSeek 同时提供 OpenAI 和 Anthropic 兼容入口。使用 Anthropic SDK 时，可以将服务地址配置为 `https://api.deepseek.com/anthropic`，再通过 `client.messages.create(...)` 调用。[官方 Anthropic 兼容接口说明](https://api-docs.deepseek.com/guides/anthropic_api/)。

```text
OpenAI SDK   → DeepSeek 的 OpenAI 兼容入口   → DeepSeek 模型
Anthropic SDK → DeepSeek 的 Anthropic 兼容入口 → DeepSeek 模型
```

这里兼容两套格式的是服务端。两个 SDK 各自沿用原来的接口约定，服务端接受对应的请求，并返回对应格式的响应。

如果目标服务没有提供兼容入口，只改地址就不够：请求路径可能不同，工具参数和返回字段也可能不同。比如 Chat Completions 通过 `choices[0].message` 读取消息，Anthropic Messages 通过 `content` 内容块表达返回内容。这时需要转换格式，或者改用相应的 SDK。即使有兼容入口，也应核对应用实际用到的字段和功能是否被支持。

## 消息与工具描述：SDK 的输入和输出是什么

`messages` 表示谁说了什么，工具参数的 schema 则描述一个工具接受哪些输入。两者可以出现在同一次请求里：前者告诉模型当前任务与历史，后者告诉模型有哪些可调用操作。这些是 API 的约定；具体字段名称和工具调用能力，要看所用接口与模型。

假设应用已经实现 `search_documents(query)`，用于搜索本地实验记录。调用模型时，发送的是用户问题和工具描述；函数的代码仍留在应用中。工具描述中的参数 schema 可以表达为：

```json
{
  "type": "object",
  "properties": {
    "query": {"type": "string", "description": "要搜索的内容"}
  },
  "required": ["query"]
}
```

它说明调用搜索时需要提供一个字符串参数 `query`。模型根据任务生成工具名称和参数，SDK 将服务端响应交回程序；此时搜索函数还没有执行。SDK 返回的也不一定是工具调用列表，还可能包含回答文本、结束原因和用量信息。

上面的 HTTP 示例采用 Chat Completions 格式。OpenAI 还提供 Responses API；下面把它与 Anthropic 的 Messages API 放在一起，对照一次工具调用的请求与结果：

| 一次交互中的对象 | OpenAI Responses API | Anthropic Messages API |
| --- | --- | --- |
| 工具参数定义 | 函数工具的 `parameters` | 工具的 `input_schema` |
| 模型请求调用工具 | `function_call`，包含名称与 JSON 字符串形式的 `arguments` | assistant 消息中的 `tool_use` 内容块，`input` 是 JSON 对象 |
| 程序返回工具结果 | `function_call_output`，用 `call_id` 对应调用 | user 消息中的 `tool_result`，用 `tool_use_id` 对应调用 |

下面是同一次搜索在两个接口中的关键字段。为了看清往返关系，省略了模型名等请求配置和无关响应字段；这不是一次真实运行的日志。

```text
OpenAI Responses
请求 input:
  [{"role":"user","content":"查询方案 A 的吞吐和实验条件"}]
响应 output 中的一项:
  {"type":"function_call","call_id":"call_1",
   "name":"search_documents","arguments":"{\"query\":\"方案 A 吞吐 实验条件\"}"}
应用执行搜索后，追加结果:
  {"type":"function_call_output","call_id":"call_1",
   "output":"实验记录第 3 页：吞吐 800 MB/s，单线程，数据集 X。"}

Anthropic Messages
请求 messages:
  [{"role":"user","content":"查询方案 A 的吞吐和实验条件"}]
响应 assistant 的 content 中的一项:
  {"type":"tool_use","id":"toolu_1",
   "name":"search_documents","input":{"query":"方案 A 吞吐 实验条件"}}
应用执行搜索后，追加 user 消息:
  {"role":"user","content":[
    {"type":"tool_result","tool_use_id":"toolu_1",
     "content":"实验记录第 3 页：吞吐 800 MB/s，单线程，数据集 X。"}
  ]}
```

第二次请求需要让模型同时看到原来的问题、调用请求和工具结果。手动管理历史时，应保留完整的相关响应项，再追加结果；Responses 也提供服务端续接方式。收到结果以后，模型可能请求读取原文，也可能生成比较结论，程序据此继续循环。上面的数值只是用于说明消息结构。接口细节见 [OpenAI function calling](https://developers.openai.com/api/docs/guides/function-calling) 和 [Anthropic tool use](https://platform.claude.com/docs/en/agents-and-tools/tool-use/how-tool-use-works)。

用普通模型 SDK 的单次请求方法时，本地工具仍由应用执行。Agent SDK 或工具循环辅助器会进一步封装执行工具、回填结果和再次请求的过程。例如 Anthropic 的 [tool runner](https://platform.claude.com/docs/en/agents-and-tools/tool-use/tool-runner) 会调用注册的工具并继续请求，直到模型不再要求调用工具或达到配置的迭代上限。判断一个 SDK 替我们做了多少工作，要看使用的是哪一层接口。

## Agent 循环：谁调用工具，什么时候结束

如果自己写，循环可以是下面这样。这里用伪代码省略两家 API 的格式差异：

```python
history = [user_question]
for step in range(max_steps):
    response = call_model(history, tool_descriptions)
    history.extend(response.items)
    if response.is_complete:
        return response.answer
    if not response.tool_calls:
        return handle_incomplete_response(response)
    for call in response.tool_calls:
        args = validate(call.arguments)
        result = registered_tools[call.name](**args)
        history.append(tool_result(call.id, result))
return report_budget_exhausted()
```

循环负责把模型提出的动作变成实际调用。没有工具调用也不一定意味着任务成功，输出可能因长度限制等原因中止，所以程序还要检查完成状态。工具出错时，是重试、把错误交回模型，还是终止任务，也需要有明确处理。

任务短、工具少时，这样的程序很容易理解。若多个任务反复需要消息转换、流式结果、重试和运行记录，就可以考虑复用已有的 Agent 循环。常见实现的区别在于开发者从哪里接入，以及哪些执行细节已经由库安排好。

### LangChain：统一消息与常见执行循环

LangChain 的模型适配器把服务商响应转换成统一消息。例如工具调用进入 `AIMessage.tool_calls`，工具结果进入 `ToolMessage`；下一轮请求再转换回相应服务商的格式。这样，工具执行代码不必分别认识每家 API 的字段。[消息转换源码](https://github.com/langchain-ai/langchain/blob/3971e49d24e1b0eef9f2446011583d5510fbbf44/libs/partners/openai/langchain_openai/chat_models/base.py#L217)。

`create_agent` 接收模型、工具和系统提示词，建立模型与工具交替执行的循环，还可以通过 middleware 在调用前后调整行为。这个 Agent 建立在 LangGraph 上，底层负责状态与执行过程。[LangChain Agent 文档](https://docs.langchain.com/oss/python/langchain/agents)。

如果应用固定使用一种模型服务，或者多个服务的兼容接口已经覆盖所需功能，直接沿用同一个 SDK 就很方便。此时不必只为切换模型增加一层适配。LangChain 还提供可复用的执行逻辑；搜索函数如何查资料、哪些错误值得重试，仍由应用决定。同步、异步、批量和流式调用等多种路径，也解释了通用实现为什么会比一个固定用途的循环大得多。

### OpenAI Agents SDK：在应用里定义并运行 Agent

OpenAI Agents SDK 提供 Agent、工具和运行器。应用定义角色指令与工具函数，运行器组织模型调用和工具执行，并提供运行结果、追踪及后续交接的接口。它与直接调用 Responses API 的区别，是已经实现了循环这一层；服务器部署、业务工具和存储仍由应用安排。[官方 Agents SDK 说明](https://developers.openai.com/api/docs/guides/agents/sdk)。

对于调研助手，我们可以把搜索和读取函数交给它，由运行器推进一次任务。若还需要规定“检查不通过就补查，用户批准以后才交付”，这些业务转移仍要通过应用代码或相应编排能力表达。

### Claude Agent SDK：接入已有的工具环境和循环

Claude Agent SDK 通过 Python 或 TypeScript 接入 Claude Code 的执行能力，包含文件读写、命令执行等内置工具，以及权限、会话和 hooks。它运行 Claude Code 二进制程序；相比从工具函数开始搭一个循环，接入时已经带着一套工具环境和上下文管理方式。[官方 Agent SDK 说明](https://code.claude.com/docs/en/agent-sdk/overview)。

这适合需要在文件和命令环境中连续工作的任务。开发者主要配置可用工具、权限与行为扩展；若想从底层自行定义消息处理和循环，直接使用 Messages API 或普通客户端 SDK 更容易看清每一步。SDK 包的公开代码与底层 Claude Code 运行程序也应分开看，不能因为有公开仓库就把整个执行系统当作可修改的开源实现。[Python SDK 仓库](https://github.com/anthropics/claude-agent-sdk-python)。

| 实现入口 | 已提供的公共部分 | 应用主要控制什么 |
| --- | --- | --- |
| 模型 SDK + 自己写循环 | API 请求、响应对象；部分 SDK 有工具循环辅助器 | 历史、工具调度、退出与错误处理 |
| LangChain | 统一消息、模型适配、常见 Agent 循环及中间件 | 工具、运行策略与业务规则 |
| OpenAI Agents SDK | Agent 运行循环、工具调用与运行接口 | Agent 定义、业务工具与外围流程 |
| Claude Agent SDK | Claude Code 循环、内置工具与会话能力 | 工具授权、配置及 hooks 扩展 |

这里主要比较可接入应用的实现。LangChain、LangGraph 和 OpenAI Agents SDK 可作为开源代码阅读与修改的起点；模型 API 本身是服务接口，采用开源客户端不会使服务端模型和执行服务一并开源。

## 执行编排：循环之外还要保存哪些约定

假设助手读到一半服务超时，用户第二天才回复，或者两条检索同时返回。此时我们需要知道当前做到了哪一步、下一步运行什么，以及哪些工作可以复用。执行编排就是把这些状态与转移关系写清楚。

LangGraph 让开发者显式定义状态、工作节点和转移，也提供保留普通函数与控制流写法的 Functional API。一个节点可以调用模型，也可以只处理数据；我们可以用它实现 Agent 循环，也可以组织完全固定的工作流。[LangGraph 概览](https://docs.langchain.com/oss/python/langgraph/overview)、[Functional API](https://docs.langchain.com/oss/python/langgraph/functional-api)。

因此，LangChain 与 LangGraph 的区别可以从接入位置理解：前者先给我们一个常见 Agent 循环，后者让我们直接安排任务的执行结构。需要多少控制，取决于现成循环能否表达自己的任务。

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

## 怎样比较这些实现

对调研助手，可以先验证一次模型调用与工具结果回填，再检查复杂流程：读取 A 成功、读取 B 超时以后，是否只需补跑 B；报告等待审阅时能否暂停；恢复后会不会重复写入。前面的例子已经能观察暂停与分支，跨进程恢复还需要持久存储，外部写入还需要幂等处理。

选择普通 SDK、Agent SDK 或图运行时，最终是在决定哪些执行约定由自己维护。若只需要一个短循环，普通代码就足够清楚；若需要显式状态、并行汇合和暂停恢复，LangGraph 这样的运行结构才有更直接的价值。

执行状态中保存的历史怎样压缩、哪些事实值得跨任务保留，属于[记忆管理](/blog/2026/09/23/agent-memory-implementations/)；研究者和检查者怎样分别运行、传递结果，属于[多 Agent 协作](/blog/2026/09/23/agent-multi-agent-implementations/)。这两类策略可以接在同一个执行系统上。

[上一篇：工具调用如何学会，又如何验收](/blog/2026/09/14/agent-tools-toolformer-gorilla-bfcl/) · [下一篇：资料检索与 RAG 的实现方案](/blog/2026/09/23/agent-open-source-components/) · [Agent 学习笔记专栏](/blog/columns/agent/)
