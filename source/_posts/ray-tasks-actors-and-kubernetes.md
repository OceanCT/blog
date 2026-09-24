---
title: "容器管理（二）Ray 怎样运行任务，以及它与 K8S 的关系"
date: 2026-09-18 11:47:06
updated: 2026-09-19 02:40:00
description: "从本地 Task 与 Actor 示例理解 Ray 的架构、结果传递、Ray Serve 和 KubeRay，并对照 K8S 的调度与恢复职责。"
categories: ["容器管理"]
tags: ["Ray", "K8S", "分布式计算"]
---

看过 K8S，再看 Ray，也会遇到集群、调度、资源、故障恢复和 Deployment。它们看起来相似，因为都要协调多台机器上的程序；但我们交给它们的工作不同。

假设要统计一批文本的词数。K8S 可以让装着处理程序的容器运行起来，Ray 则可以接收“对这几份文本分别调用统计函数”的请求，安排执行并把结果交回来。我们从这个小例子理解 Ray 的架构，再看它怎样与 K8S 配合。

## Ray 接管的是哪一部分工作

普通 Python 程序调用 `count_words(text)`，通常就在当前进程执行。要让多台机器共同处理文本，还需要传递参数、安排执行位置、等待结果，并处理进程退出等情况。

Ray Core 提供了三个基本对象：**Task** 是一次远程函数调用；**Actor** 是运行在专用工作进程中的有状态对象，可以连续调用它的方法；**ObjectRef** 是结果或数据的引用。调用者可以先拿到引用，继续提交其他工作，之后再获取结果。这里的 Actor 是计算模型中的有状态执行单元，与大模型 Agent 是不同概念。[Ray 核心概念](https://docs.ray.io/en/latest/ray-core/key-concepts.html)。

例如，把三份文本交给三个 Task，可以独立计算。若程序要长期保存累计计数，或者把模型加载到内存后多次复用，则可以创建 Actor。Task 与 Actor 的选择取决于是否需要保留工作进程中的状态。[Actor 的使用方式](https://docs.ray.io/en/latest/ray-core/actors.html)。

## 整体架构：用户的调用去了哪里

[![Ray 架构：用户启动 Driver，经节点运行时安排 Task 和 Actor，返回结果引用与对象数据](/images/container-management/ray-architecture.svg)](/blog/images/container-management/ray-architecture.svg)

图中画出 Ray Core 的主要执行路径，点击可放大。对应说明见 [Ray 任务生命周期](https://docs.ray.io/en/latest/ray-core/internals/task-lifecycle.html)。

**Driver** 是运行主程序的进程。我们写的 `ray.init()`、提交 Task 和获取结果等代码就在这里执行。通过 Ray Jobs 提交程序时，集群中的作业服务负责启动入口程序；它仍会形成执行应用逻辑的 Driver。

Ray 集群有一个 **Head 节点**，可以有多个 **Worker 节点**。Head 上运行 GCS（Global Control Service），管理节点、Actor 等集群元数据，也可以运行 Dashboard、Jobs 服务。Head 同样具备节点运行时，是否允许它承担应用计算可以通过资源配置控制。Worker 节点与 Worker 进程要分开理解：一个节点可以运行多个执行 Python 代码的进程。

每个节点上的 **Raylet** 负责本地资源调度、Worker 进程管理等工作，并参与跨节点调度。提交任务时，运行时根据资源与调度条件寻找执行位置；取得执行资源后，调用会交给相应的 Worker 进程。GCS 保存控制信息，不是要求所有函数参数和结果都从 Head 中转的中央执行器。

节点还有共享内存对象存储。较大的对象可以存入其中，通过 ObjectRef 引用；跨节点使用时，由运行时获取所需数据。小结果可能直接返回，不能把所有调用都理解为“先写对象存储，再让 Driver 下载”。我们需要关注的是：引用代表数据依赖，使用这个结果的任务必须等数据就绪后才能执行。

## 一个能在本机运行的 Task 与 Actor 例子

源码在 [GitHub 的 k8s-local-lab 目录](https://github.com/OceanCT/blog/tree/master/examples/k8s-local-lab)，与 K8S 实验共用环境。首次使用可以克隆仓库后初始化；已经跟着上一篇完成实验的读者，在原目录直接执行 `bash ray/run.sh` 即可：

```bash
git clone --depth 1 https://github.com/OceanCT/blog.git
cd blog/examples/k8s-local-lab
brew install colima docker
source ./init.sh
bash ray/run.sh
```

脚本使用 Colima 中的容器运行 Python 3.12 和 Ray 2.58.0，不需要 Docker Desktop，也不用在 Mac 的 Python 环境中安装 Ray。这个 Ray 实验运行在独立容器内，没有部署 KubeRay；它先让我们看清 Ray Core 自己完成什么。容器限制为 2 CPU、2 GiB 内存，下面是任务与累计计数部分的核心代码，完整程序在仓库的 `ray/demo.py`。

```python
import ray

@ray.remote(num_cpus=1)
def count_words(text):
    return len(text.split())

@ray.remote(num_cpus=1)
class Counter:
    def __init__(self):
        self.total = 0

    def add(self, value):
        self.total += value
        return self.total

if __name__ == "__main__":
    ray.init(num_cpus=2, include_dashboard=False)
    try:
        texts = ["hello ray", "one two three", "kubernetes"]
        refs = [count_words.remote(text) for text in texts]
        counts = ray.get(refs)
        print("counts:", counts)

        counter = Counter.remote()
        for value in counts:
            total = ray.get(counter.add.remote(value))
        print("total:", total)
    finally:
        ray.shutdown()
```

代码中的业务结果应为 `counts: [2, 3, 1]` 和 `total: 6`。实验代码把结果、执行进程 PID 和重启前后的计数输出为 JSON，保存在 `results/ray.log`。这个例子用很小的数据展示调用关系，调度开销可能比统计词数本身更大，不能用它说明并行加速效果。

按图中的顺序看：`ray.init` 在没有指定已有集群地址时启动本地 Ray；当前 Python 主进程是 Driver。三次 `.remote()` 提交三项工作并立即给回 ObjectRef。运行时安排 Worker 执行；`ray.get(refs)` 等待并取出结果，返回列表的顺序对应输入引用的顺序，并不要求任务按这个顺序完成。

之后 `Counter.remote()` 创建 Actor，调用它的 `add` 方法会更新同一个对象的累计值。这里每次等待结果，是为了直观看到顺序累加；批量 Task 则先全部提交，再一起等待，避免把独立工作人为串行化。

`num_cpus=2` 声明本地 Ray 的逻辑 CPU 容量，每个 Task 要求 1 个，因此这个例子最多同时安排两个这样的 Task。**Ray 的 CPU 资源声明主要用于调度记账，不等同于操作系统的 CPU 使用上限。** 函数若自行启动多个计算线程，仍可能消耗更多 CPU；容器的资源隔离需要底层运行环境配合。[Ray 的逻辑资源与物理资源](https://docs.ray.io/en/latest/ray-core/scheduling/resources.html)。

## 为什么还会看到 Ray Serve 的 Deployment

Ray Core 解决远程计算的基础问题。Ray Serve 在它之上组织长期运行的服务：把服务逻辑定义为 Deployment，创建多个 Replica，通过代理和路由把请求交给副本，并管理副本健康和扩缩容。每个 Serve Replica 基于 Ray Actor，Deployment 是应用服务的一组副本配置。[Ray Serve 概念](https://docs.ray.io/en/latest/serve/key-concepts.html)。

比如，一个文本处理 Deployment 配置两个副本，两者分别运行相同的处理逻辑。请求进入 Serve 后，路由选择可用副本执行。如果改成三个副本，Serve 增加的是 Actor 副本；这些 Actor 可以使用现有 Ray 节点的剩余资源，不必立即增加 Kubernetes Pod。

K8S Deployment 管理的是 Pod 模板、ReplicaSet 和 Pod 副本。Ray Serve Deployment 管理的是服务逻辑和 Actor 副本。二者都有“维持目标副本数”的控制思路，但它们控制的对象不同，不能把两个同名 Deployment 当作同一个接口。

## Ray 部署在 K8S 上时，谁负责哪一步

Ray 可以在本机或虚拟机上运行。需要在 K8S 中管理 Ray 集群时，可以使用 **KubeRay Operator**。Operator 是扩展 K8S 控制过程的程序：读取 RayCluster 等自定义对象，创建和维护 Ray Head、Worker 对应的 Pod。RayJob 用于组织作业提交与集群生命周期；RayService 用于组织 Ray Serve 应用及其集群。[KubeRay 的三类资源](https://docs.ray.io/en/latest/cluster/kubernetes/index.html)。

```text
用户提交 RayCluster 配置
    ↓
KubeRay Operator 创建 Head / Worker Pod
    ↓
K8S 调度 Pod，kubelet 启动其中的 Ray 进程
    ↓
用户提交 Ray 程序，Driver 调用 .remote()
    ↓
Ray 在已有计算资源中安排 Task / Actor
```

例如，K8S 先启动两个 Ray Worker Pod，每个提供两个逻辑 CPU。程序提交十个各需一个 CPU 的 Task 时，Ray 会按可用容量执行，其余等待；这不意味着 K8S 应创建十个 Pod。启用相应的自动扩容配置后，Ray 的资源需求还可以推动 Worker Pod 数量变化，但最终仍受 K8S 节点容量约束。

| 一次操作 | K8S 这一层 | Ray 这一层 |
| --- | --- | --- |
| 启动执行环境 | 创建并调度 Ray 的 Pod | 启动运行时，注册节点资源 |
| 提交统计函数 | 通常看不到每次函数调用 | 安排 Task，传参数，返回结果引用 |
| 保留累计计数 | 维持承载进程的容器 | Actor 保存并更新内存状态 |
| 扩大计算容量 | 为新增 Pod 找到节点并启动 | 在新增的 Ray 资源中安排工作 |

## 发生故障时，恢复的对象也不同

如果一个 Ray Worker 进程退出，但它所在的容器仍然运行，K8S 未必会重启这个容器。Ray 可以根据任务的重试配置处理受影响的计算。如果整个 Pod 消失，则还需要 K8S 与 KubeRay 恢复承载 Ray 的运行环境，计算是否重做由 Ray 和应用的故障处理机制决定。

Actor 重启也不等于内存状态自动恢复。可通过 `max_restarts` 配置允许的 Actor 重建次数，但重建会重新执行构造函数；前面 Counter 的累计值需要应用自行持久化并加载。对外部系统有写入的操作还要考虑重试导致的重复执行。实验代码给 Counter 设置 `max_restarts=1`，累计到 6 后调用 `ray.kill(counter, no_restart=False)`。由于终止请求是异步的，程序等待新进程 PID 出现，再检查计数是否回到 0；只在调用 kill 后立即读一次，有可能仍读到旧进程的状态。这里的自动检查说明“重新创建对象”与“恢复原有业务状态”之间还有应用自己的持久化工作。[Actor 故障恢复](https://docs.ray.io/en/latest/ray-core/fault_tolerance/actors.html)。

回到文本统计的例子：如果我们要保持几个容器运行，主要看 K8S 的对象与控制过程；如果我们要把许多函数调用分发出去并取回结果，就需要 Ray 这样的计算运行时。两者一起使用时，排查也应沿这条关系进行：先看 Pod 是否启动、Ray 节点是否加入，再看任务是否获得资源、执行是否失败、结果是否可用。

[返回容器管理专栏](/blog/columns/k8s/)
