---
title: "K8S学习笔记（一）从三个副本理解控制循环与架构"
date: 2026-09-15 14:02:33
updated: 2026-09-15 14:25:23
description: "从部署一个服务开始，理解 K8S 的期望状态、控制器、调度器、节点执行与服务入口及其协作过程。"
categories: ["K8S 学习笔记"]
tags: ["K8S", "系统设计"]
---

假设我们已经写好一个 HTTP 服务，把它打成容器镜像，并在一台机器上启动。程序能处理请求之后，新的问题很快出现：进程退出了谁来重启，机器坏了去哪里补实例，访问量增加后怎样扩到三个副本，发布新版本时怎样避免同时停掉所有旧实例？

如果只有一两台机器，可以通过脚本和人工处理。机器与服务越来越多以后，脚本还要知道每台机器的剩余资源、当前版本、健康状态和网络入口，失败后还要判断哪些操作已经完成。Kubernetes，也就是 K8S，主要解决的就是这种跨机器运行容器化应用的管理问题。

这是 K8S 专栏的第一篇。我们从“让一个服务保持三个可用副本”出发，理解配置怎样变成运行中的容器，以及各组件为什么需要这样协作。

## 容器启动之后，还有哪些事情要管理

容器镜像封装程序和依赖，容器运行时负责创建、启动和停止容器。它们让“用同一份程序运行一个实例”更容易，但集群还需要回答：这个实例放在哪台机器上？它退出以后是否重启？整台机器不可用以后是否补新实例？用户应该访问哪个地址？

我们给这项服务定一个目标：运行三个副本，对外提供稳定入口，新版本逐步替换旧版本。这样就有了几类相互关联的任务：

| 需要管理的事情 | 对这个服务意味着什么 |
| --- | --- |
| 副本数量 | 少了一个实例，要能发现并补齐 |
| 资源与放置 | 为实例选择满足 CPU、内存及其他约束的机器 |
| 服务发现 | 实例地址变化后，调用方仍能找到服务 |
| 健康状态 | 区分进程还活着与已经可以接流量 |
| 版本更新 | 控制新旧实例的替换速度，观察新版本是否可用 |

这些目标需要不同组件协作。K8S 不会自动修好业务代码，也不保证任何故障下都零中断；它提供描述目标、观察运行状态、持续执行修正的机制。[官方组件概览](https://kubernetes.io/docs/concepts/overview/components/)。

## 最重要的变化：从执行命令到维护目标

直接写脚本时，我们通常说：“去机器 A 启动一个容器。”命令结束以后，容器可能过五分钟就退出；除非另外写监控与恢复逻辑，这条命令已经完成了自己的工作。

使用 K8S 时，我们更常表达：“这个应用应该有三个副本，使用指定镜像。”这是一份持续有效的期望。系统不断观察现实，如果当前受管理的副本不足，就执行创建；后续我们把期望改为五个，系统再逐步补到五个。

这种反复比较期望与现实的过程叫 **reconciliation，调谐**。执行它的程序叫 **controller，控制器**。控制器不是只响应一次创建请求，它要在对象变化、失败和重试之后继续使系统接近期望状态。[控制器机制](https://kubernetes.io/docs/concepts/architecture/controller/)。

可以用下面的伪代码理解调谐。它省略了并发、正在删除的对象和创建失败等细节：

```python
while running:
    desired = read_desired_replicas()
    actual = list_owned_active_instances()
    if len(actual) < desired:
        create_missing_instances(desired - len(actual))
    elif len(actual) > desired:
        remove_excess_instances(len(actual) - desired)
    wait_for_change_or_retry()
```

这里还有一个容易误解的地方：三个对象存在，不代表三个实例已经能提供服务。副本管理、容器健康、流量就绪分别有自己的判断。K8S 通过多个控制过程协作，而不是用一个数字覆盖所有状态。

## 先认识几个对象，再看架构

**Node** 是集群中的工作节点，可以是一台物理机或虚拟机。**Pod** 是 K8S 调度和管理的基本工作负载单元，包含一个或多个紧密协作的容器。同一 Pod 的容器共享网络环境，并可以挂载共享卷；它们作为一个整体安排到同一个 Node。Pod 也经常只有一个业务容器。[Pod 定义与生命周期](https://kubernetes.io/docs/concepts/workloads/pods/pod-lifecycle/)。

## ReplicaSet：这一组 Pod 少了，谁来补

假设我们直接创建三个 Pod，分别叫 A、B、C。它们可以运行服务，但如果 B 被删除，仅靠剩下的两个 Pod，没有谁负责记住“这里原本应该有三个”。我们需要一个持续保存目标、检查数量的对象，这就是 **ReplicaSet**。

ReplicaSet 中有几项关键配置：`replicas` 指定期望副本数，`template` 保存创建 Pod 所用的模板，`selector` 通过标签匹配 Pod。模板包含镜像、启动参数和资源需求等信息。系统还通过 Pod 上的 `ownerReferences` 记录它归哪个控制器管理，计数时不会把集群里所有 Pod 都算进去。

严格说，ReplicaSet 是保存在 API 中的对象，真正执行检查与增删的是 **ReplicaSet 控制器**。平时说“ReplicaSet 补了一个 Pod”，指的就是控制器根据这个对象执行了操作。

```text
ReplicaSet：期望 3 个 Pod，模板使用镜像 v1
  ├─ Pod A
  ├─ Pod B
  └─ Pod C

B 被删除后：A、C → 控制器发现缺 1 个 → 按模板创建 Pod D
```

新建的 D 有自己的身份，不是把 B 复活。控制器先向 API Server 提交 Pod 对象；之后由 Scheduler 选择机器，再由那台机器上的 kubelet 启动容器。这也解释了为什么“已经补了一个 Pod 对象”和“服务已经恢复三个可用实例”之间还需要时间。

反过来，把目标数量从 3 改为 2，控制器就会删除多余副本。ReplicaSet 负责使受管理的有效副本数量接近目标，并不会保证三个实例始终健康。假设 B 仍然存在，只是内部容器崩溃，在 Deployment 常用的重启策略下，通常由 kubelet 重启容器；单纯没有 Ready，不会让 ReplicaSet 立即再补一个 Pod。[ReplicaSet 的工作机制](https://kubernetes.io/docs/concepts/workloads/controllers/replicaset/)。

## Deployment：新旧两组副本怎样交接

既然 ReplicaSet 能维持数量，为什么还需要 **Deployment**？因为发布新版本时，我们还要决定旧版本什么时候减少、新版本什么时候增加，以及新实例没有准备好时是否继续替换。

比如当前三个 Pod 都使用 v1，现在希望更新为 v2。直接修改 ReplicaSet 的 Pod 模板，只会影响以后根据模板创建的 Pod，已有 Pod 不会因此自动全部替换。Deployment 在上面增加了版本更新的控制：为新模板管理新的 ReplicaSet，并协调新旧两组的目标数量。

```text
Deployment：目标版本 v2，期望副本数 3，采用滚动更新
  │
  ├─ 旧 ReplicaSet：模板使用 v1
  │    目标数量逐步减少：3 → 2 → 1 → 0
  │
  └─ 新 ReplicaSet：模板使用 v2
       目标数量逐步增加：0 → 1 → 2 → 3
```

图中表示两组的变化方向，箭头并不要求新旧两组同时各变一个。Deployment 根据更新策略和新 Pod 的可用状态调整数量。例如允许额外增加一个副本、要求至少保持三个可用副本时，可以先把新组扩到 1；等新 Pod 可用，再把旧组从 3 缩到 2，然后继续替换。更新期间，新旧 Pod 可以同时存在。

在这个过程中，Deployment 控制器决定“旧组现在要几个、新组现在要几个”，每个 ReplicaSet 控制器负责落实自己那一组的数量。如果旧组此时仍要求两个副本，却有一个 Pod 被删除，旧 ReplicaSet 仍会补齐它，直到 Deployment 调低该组的目标。

这两层分别处理了版本过渡和组内副本维护。平时我们通常只创建、修改 Deployment，让它管理下面的 ReplicaSet；手动修改它所管理的 ReplicaSet，可能又被 Deployment 的下一轮调谐改回去。[Deployment 与滚动更新](https://kubernetes.io/docs/concepts/workloads/controllers/deployment/)。

对象中经常出现两个字段：`spec` 描述期望，`status` 记录组件观察到的状态。例如希望三个副本，与当前就绪几个副本，是不同信息。提交新 spec 后，status 需要经过实际执行才会变化，通常不会在同一次请求中立即达到目标。

## 整体架构：谁记录目标，谁真正执行

K8S 集群通常分为控制平面和工作节点。控制平面管理集群对象、作出调度与控制决策，工作节点运行应用容器。先把主要关系画出来：

```text
用户 / kubectl
      │ API 请求
      ▼
kube-apiserver ↔ etcd
      ▲
      │ 读取、监听、更新集群对象
      ├── controller-manager
      ├── scheduler
      └── 各 Node 上的 kubelet
                     │ CRI
                     ▼
                  容器运行时
                     │
                  应用容器
```

图中的连接主要表示控制信息流。业务 HTTP 请求走服务网络，通常不会经过 kube-apiserver。

### API Server：我们怎样把目标交给集群

`kube-apiserver` 是一个提供 HTTPS 接口的服务。我们执行 `kubectl apply -f deployment.yaml` 时，kubectl 根据本地连接配置找到 API Server，携带身份凭据，把文件中的配置转换成 API 请求。这里可以类比普通后端：kubectl 是客户端，API Server 接收请求，对象就是通过接口读写的数据。

例如，创建 Deployment 的接口路径如下，正文发送对应的对象数据：

```http
POST /apis/apps/v1/namespaces/default/deployments
Content-Type: application/json
```

路径中的 `apps/v1` 表示 API 组与版本，`default` 是命名空间，`deployments` 是资源类型。查询这个命名空间中的 Deployment，可以向同一路径发送 GET。`apply` 会根据客户端模式和对象是否存在使用相应的读取、创建或 PATCH 操作，因此不能把每次 apply 都理解为一个 POST。

收到写入请求后，API Server 检查调用者身份、操作权限、对象字段以及准入规则，再把通过检查的对象保存下来。如果我们声明三个副本，成功返回时保存的是这份部署目标；实际容器由后续组件启动。[Kubernetes API 的请求与资源形式](https://kubernetes.io/docs/reference/using-api/api-concepts/)。

### etcd：为什么集群需要一个数据库

**etcd 是分布式键值数据库。** K8S 用它持久保存集群对象，例如 Deployment 的期望副本数、Pod 配置、节点信息和组件报告的状态。可以把一个对象理解成键所对应的一份结构化数据；具体存储编码由 K8S 处理，使用者通过 API 读取对象。

如果目标只存在某个控制器的内存里，进程重启后就会丢失。把对象存入数据库，控制器重启后便能重新读取目标和已记录的状态，再检查现实、继续工作。订单、聊天记录等应用数据通常由应用自己的数据库保存；etcd 在这里存的是管理集群所需的数据。

控制平面的数据库还需要在多台机器之间保持一致的已提交记录。etcd 使用 Raft 协议复制数据，写入需要集群多数成员参与形成共识。这样，在仍有多数成员可用等条件下，可以容忍部分成员故障；失去多数成员后则无法正常提交新的写入。这种取舍优先保护集群管理数据的一致性。[etcd 的设计目标](https://etcd.io/docs/v3.6/learning/why/)。

其他组件通常通过 API Server 操作 Kubernetes 对象。让所有组件直接改数据库，会使它们依赖内部存储格式，并分散权限与字段检查。统一入口把这些规则集中起来，也让客户端面对稳定的 API。数据库可靠保存了“期望三个副本”，接下来仍然需要控制器、调度器和节点把这个目标落实。

### Controller Manager：发现期望与实际的差异

`kube-controller-manager` 运行多种控制器，例如前面介绍的 Deployment 和 ReplicaSet 控制器。控制器通过 API 读取已有对象，并使用 Watch 机制接收变化：建立监听后，API Server 持续返回相关对象的新增、修改或删除信息，客户端不必每次都重新查询完整列表。连接中断或记录过期时，客户端需要重新建立监听，必要时重新读取列表。

Deployment 控制器观察到新配置，就通过 API 创建或调整 ReplicaSet；ReplicaSet 控制器再通过 API 创建缺少的 Pod 对象。这些组件根据共享对象接续工作。控制器重启后可以重新读取对象并继续调谐，无需让最初那次 kubectl 请求一直等到所有容器启动。[API 的列表与 Watch 机制](https://kubernetes.io/docs/reference/using-api/api-concepts/)。

### Scheduler：为尚未分配的 Pod 选择节点

`kube-scheduler` 观察尚未绑定 Node 的 Pod，根据资源需求和调度约束寻找合适节点。选择完成后，把绑定结果写回 API。

调度结果说明 Pod 应该去哪里，实际启动还由对应 Node 的 kubelet 完成。没有满足条件的节点时，Pod 可以一直处于未调度状态；重新提交同一配置并不会创造更多 CPU 或内存。

### Kubelet 与容器运行时：落实到机器上

每个工作节点上的 `kubelet` 关注分配给本节点的 Pod，通过 **CRI（Container Runtime Interface）** 与兼容的容器运行时交互，例如 containerd，落实容器的创建和运行，并报告状态。

一个 kubelet 管理所在 Node 上的 Pod，因此整个 Node 失联时，不能期待这台机器上的 kubelet 在别处创建替代实例。跨节点的故障处理需要控制平面与其他节点共同参与。以上组件分工可对应到[官方架构说明](https://kubernetes.io/docs/concepts/overview/components/)。

## 提交三个副本之后，究竟发生了什么

下面是一份 Deployment 示例，选择一个公开 HTTP 镜像，声明三个副本。它用于阅读对象结构，本篇没有向任何集群执行部署。

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: notes-web
spec:
  replicas: 3
  selector:
    matchLabels:
      app: notes-web
  template:
    metadata:
      labels:
        app: notes-web
    spec:
      containers:
        - name: web
          image: nginx:1.27
          ports:
            - containerPort: 80
          resources:
            requests:
              cpu: "100m"
              memory: "64Mi"
          readinessProbe:
            httpGet:
              path: /
              port: 80
```

`replicas` 表示期望数量；`template` 是创建 Pod 的模板。`labels` 是对象标签，`selector` 用它识别要管理的对象。这里 `100m` 表示 0.1 个 CPU 的请求量，`64Mi` 是内存请求量；requests 参与调度资源核算，不等于配置了资源使用上限，limits 是另一个设置。[资源请求与限制](https://kubernetes.io/docs/concepts/configuration/manage-resources-containers/)。

假设通过 `kubectl apply` 提交它，正常路径大致如下：

1. API Server 接受并保存 Deployment 对象。请求成功说明对象已提交，不代表容器已经运行。
2. Deployment 控制器管理对应 ReplicaSet，ReplicaSet 控制器创建缺少的 Pod 对象。
3. Scheduler 为尚未绑定的 Pod 选择节点。
4. 各节点 kubelet 根据 Pod 配置让运行时拉取镜像、启动容器，并进行相关健康检查。
5. 运行状态回报后，我们才能观察哪些 Pod 已运行、哪些已经 Ready。

这些动作通过对象状态协作，不是一条要求所有组件同时成功的同步函数调用。调度失败、镜像拉取失败、应用启动失败，都会停在不同位置，排查时应找到最后已完成的阶段。

## Pod 的地址会变化，访问入口怎么办

三个 Pod 可能拥有不同 IP，替换后 IP 还可能变化。可以再创建一个 **Service**，用相同的 `app: notes-web` 标签选择后端。常见的 ClusterIP Service 提供集群内部稳定的访问入口，EndpointSlice 记录对应后端端点及其状态。

节点网络上的代理或等价实现据此转发连接。常见组件是 `kube-proxy`，某些网络方案会使用其他实现；Pod 网络连通性通常还涉及 CNI 网络插件。Service 对象本身不是一个运行 HTTP 业务的进程。[Service 官方说明](https://kubernetes.io/docs/concepts/services-networking/service/)。

如果需要从集群外访问，还要根据环境配置 LoadBalancer、Ingress、Gateway 等入口能力；声明一个普通 ClusterIP Service 并不会自动获得可从互联网访问的地址。Pod 的持久数据则需要卷与存储系统支持，也不能因为副本能重建就认为业务数据已经得到保护。

## 进程退出、没有就绪、整台机器失联，处理不同

假设容器进程退出，kubelet 可以按重启策略在原 Pod 内重启容器。Pod 仍可能是原来的身份，只是容器重启次数增加。假设 Pod 被删除，ReplicaSet 观察到受管理副本不足，会创建新的 Pod。整个节点失联时，还需要故障检测、节点与 Pod 状态处理以及可能的驱逐、替换过程，不会瞬间把旧 Pod 平移到另一台机器。[Pod 生命周期](https://kubernetes.io/docs/concepts/workloads/pods/pod-lifecycle/)。

健康检查也有不同目的。**Readiness** 表示当前是否适合接流量；失败通常让该 Pod 不再作为就绪后端接收常规 Service 流量，并不直接触发容器重启。**Liveness** 用于发现需要重启的容器。**Startup** 给启动较慢的应用留出时间，成功前会抑制配置的 liveness 和 readiness 检查。[探针说明](https://kubernetes.io/docs/concepts/workloads/pods/probes/)。

例如应用进程已经启动，但必要依赖尚未准备好，就可能 Running 而未 Ready。又比如业务数据库暂时变慢，把它直接作为 liveness 失败条件，可能导致大量容器反复重启。探针应该表达我们希望系统采取的动作，而不只是“某个 URL 是否返回成功”。

## 为什么需要持续调谐，而不是一次执行到底

分布式系统中的观察可能落后，写入可能冲突，请求可能成功但响应丢失。因此，控制器必须考虑重复观察与重试。假设创建请求超时，下一轮应重新读取当前对象，确认实际是否已经创建，避免只因没收到响应就持续增加副本。

实际控制逻辑比“数一数少几个”复杂，还要考虑对象归属、正在创建或删除的实例、版本冲突和重试退避。控制器倾向于围绕当前状态重新决策，而不是依赖某条事件恰好只被处理一次。[控制器设计](https://kubernetes.io/docs/concepts/architecture/controller/)。

这种机制也有边界：如果镜像不存在，或者所有节点都不满足资源需求，系统会继续报告无法收敛的状态，需要人或其他系统改变条件。声明期望提供了修正目标，不意味着任何目标都能自动实现。

[返回 K8S 专栏](/blog/columns/k8s/)
