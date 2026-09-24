---
title: "容器管理（一）在 Mac 上验证 K8S：资源限制、健康检查与恢复"
date: 2026-09-15 14:02:33
updated: 2026-09-22 20:38:52
description: "用 Colima 和 kind 在 Mac 上运行小程序，观察 CPU 节流、内存 OOM、探针与 Pod 补建，并沿执行过程理解 K8S 架构。"
categories: ["容器管理"]
tags: ["K8S", "容器", "本地实验"]
---

程序运行起来以后，我们还需要限制它能用多少 CPU 和内存，并在它异常退出时重新启动。如果只在一台机器上运行，用 Docker 启动容器、设置资源限制和重启策略，就能处理这些基本需求。[Docker 的重启策略](https://docs.docker.com/engine/containers/start-containers-automatically/)和[资源限制](https://docs.docker.com/engine/containers/resource_constraints/)。

如果程序分布在多台机器上，每台机器仍然可以用 Docker 管理本机的容器。但假设我们希望一个程序始终运行三个副本，就还要决定这三个副本放在哪里；其中一台机器坏了以后，也要知道少了几个副本、其他机器有没有空间，以及在哪里重新启动。各台机器分别运行容器，并不会自动完成这些跨机器的协调工作。

这时就需要一层统一管理：记录整个集群应该运行哪些程序、各有几个副本，再根据各台机器的状态安排和调整。Kubernetes，也就是 K8S，提供的就是这类容器编排能力。我们向它描述目标，它协调节点上的容器运行时去执行，并持续检查实际状态与目标之间的差距。它可以在单机使用；这里从多机引入，是为了说明相比直接运行容器，为什么还需要集群管理。[K8S 组件与职责](https://kubernetes.io/docs/concepts/overview/components/)。

想要更直观地理解这套机制，我们可以借助现成的开源工具 [kind](https://kind.sigs.k8s.io/)，快速在 Mac 上搭建一个本地 K8S 集群。kind 用 Docker 容器充当 K8S 节点，并自动准备节点所需的组件，本实验创建一个节点。

那么，同样在本机运行，它与直接用 Docker 启动程序有什么区别？我们仍然可以向 K8S 声明程序应保持几个副本、使用哪个镜像，并让它持续维护这个目标。例如，通过 Deployment 声明一个副本后，即使手动删除运行程序的 Pod，所管理的 ReplicaSet 也会补建一个；修改镜像版本时，Deployment 还会按更新策略组织新旧副本的替换。这些管理机制在单节点上同样工作。[Deployment 的作用](https://kubernetes.io/docs/concepts/workloads/controllers/deployment/)。

接下来，我们用三个很小的程序做实验：一个持续计算，一个不断申请内存，一个通过文件模拟健康状态。先看资源限制怎样影响程序，再观察容器重启和副本补建，沿着执行过程理解各个组件。

## 在本机准备实验环境

实验源码在 [GitHub 的 k8s-local-lab 目录](https://github.com/OceanCT/blog/tree/master/examples/k8s-local-lab)。克隆仓库后进入该目录，即可跟着下面的步骤运行。按本文脚本搭建时，Colima 使用 VZ 虚拟化后端；[该后端要求 macOS 13 或更新版本](https://lima-vm.io/docs/config/vmtype/vz/)。Python 3 用来运行初始化和验证脚本，Homebrew 用来安装下面的命令行工具；已经安装好这些工具时，可以跳过 `brew install`。Apple Silicon 使用原生 ARM64 Homebrew（通常位于 `/opt/homebrew/bin/brew`）。如果当前使用的是 `/usr/local/bin/brew`，先确认它是否为 Intel 版；本实验的 VZ 后端需要原生 ARM64 Colima/Lima，Intel 版 Lima 会报 `limactl is running under rosetta`。实验只建一个节点，几个小程序顺序运行，以控制资源用量。

```bash
git clone --depth 1 https://github.com/OceanCT/blog.git
cd blog/examples/k8s-local-lab
brew install colima docker
source ./init.sh
kubectl get nodes
```

> 这里为什么安装 Colima？Mac 没有 Linux 内核，运行本实验的 Linux 容器需要一套 Linux 环境。`brew install docker` 只安装发送命令的客户端；Colima 则负责启动 Linux 虚拟机和其中实际运行容器的 Docker Engine，让客户端能连接过去。底层由 Lima 管理虚拟机，本实验使用 macOS 的虚拟化框架来启动它。Docker Desktop 也能准备这样的环境；这里选择 Colima，是为了通过命令行管理，K8S 本身并不要求使用它。[Docker 架构](https://docs.docker.com/get-started/docker-overview/#docker-architecture)、[Colima 与 Lima](https://colima.run/docs/faq/#how-does-colima-compare-to-lima)。

执行 `source ./init.sh` 时，我们通过 `init.sh` 调用 `setup.py` 来准备集群，完成后再设置当前终端的连接变量。我们顺着 `setup.py` 看一下环境是怎样搭起来的。

`setup.py` 先下载本实验使用的 kind 和 kubectl 到 `bin` 目录，并核对下载文件的 SHA-256。kind 负责搭建集群；kubectl 是我们之后向集群发命令的客户端。

接着，脚本检查名为 `learning-lab` 的 Colima 环境是否已经启动。如果没有，就运行下面这段代码：

```python
status = run(['colima', 'status', '--profile', 'learning-lab'],
             capture=True, check=False)
if status.returncode:
    start = ['colima', 'start', '--profile', 'learning-lab',
             '--runtime', 'docker', '--vm-type', 'vz',
             '--cpu', '2', '--memory', '2', '--activate=false']
    colima_home = Path(ENV.get('COLIMA_HOME', str(Path.home()/'.colima')))
    if not (colima_home/'learning-lab/colima.yaml').exists():
        start += ['--disk', '10']
    run(start)
```

这里的 `run` 是对 Python `subprocess.run` 的封装，用来调用命令行工具。`--profile learning-lab` 给这套虚拟机环境取名，`--runtime docker` 要求在里面运行 Docker Engine，`--cpu 2 --memory 2` 分配 2 核 CPU 和 2 GiB 内存。新环境的数据盘容量设为 10 GiB；这是容量设置，实际占用随镜像和数据增长。已有环境会保留原来的磁盘。

Linux 环境准备好以后，kind 才能在其中创建 K8S 节点。脚本先查询已有集群；如果还没有 `resource-lab`，就执行：

```python
run(['kind', 'create', 'cluster', '--name', 'resource-lab',
     '--config', str(ROOT/'kind.yaml'),
     '--kubeconfig', str(ROOT/'kubeconfig'),
     '--image', NODE, '--wait', '120s'])
```

`ROOT` 是实验目录，`NODE` 是脚本中固定版本和镜像摘要的 K8S 节点镜像。`kind.yaml` 告诉 kind 创建一个节点，并把 API 的本机监听地址设为 `127.0.0.1`。kind 启动节点容器、配置 K8S 组件后，将访问集群所需的信息写进实验目录的 `kubeconfig`。已有集群则直接恢复节点容器，并重新导出这份连接配置。[kind 使用说明](https://kind.sigs.k8s.io/docs/user/quick-start/)。

最后，`setup.py` 等待节点就绪，创建名为 `resource-lab` 的 Namespace，并将它设为后续操作的默认命名空间。Namespace 可以先理解成集群内的一组资源名称空间，我们把实验程序集中放在这里。脚本还会准备 `python:3.12-alpine` 镜像并导入节点，后面就能用它运行 Python 程序。

集群准备好后，执行过程回到 `init.sh`。它通过下面两条设置，让当前终端找到 kubectl，并连接刚创建的集群。`lab_root` 是脚本所在的实验目录：

```bash
export PATH="$lab_root/bin:$lab_root/runtime/bin:$PATH"
export KUBECONFIG="$lab_root/kubeconfig"
```

`PATH` 告诉终端去哪些目录找命令。把 `bin` 加进去后，我们输入 `kubectl`，终端就能找到刚下载的可执行文件。`runtime/bin` 则供项目内安装的运行工具使用；通过 Homebrew 安装时，工具仍从原有 PATH 中查找。

但找到客户端还不够，它还需要知道连接哪个集群、用什么凭据。`KUBECONFIG` 指向刚才 kind 生成的文件，其中记录了 API Server 的地址、访问凭据和当前上下文。上下文把集群、身份和默认命名空间组合在一起。[kubeconfig 的作用](https://kubernetes.io/docs/concepts/configuration/organize-cluster-access-kubeconfig/)。

因此要用 `source ./init.sh`：它在当前终端中执行这些设置，脚本结束后变量仍然有效。如果换成 `bash init.sh`，设置只存在于它启动的子进程中，回到原终端后不会保留。

`init.sh` 还将 `DOCKER_CONTEXT` 设为 `colima-learning-lab`，让 Docker 客户端连接这套环境中的 Docker Engine，并清除可能覆盖该选择的旧连接变量。

这样，我们就可以在同一个终端里查询集群了：

```bash
kubectl config current-context
kubectl get nodes
kubectl get pods
```

第一条应输出 `kind-resource-lab`，说明当前选中了实验集群。第二条向集群请求节点列表，应看到 `resource-lab-control-plane` 的状态为 `Ready`。这里的 Node 就是 kind 创建的节点容器，后面提交的程序会安排到它上面运行。

第三条查看默认命名空间中的 Pod。Pod 是 K8S 安排容器运行的基本单位，本实验每个 Pod 放一个 Python 容器。全新环境此时还没有实验 Pod，看到 `No resources found in resource-lab namespace` 是正常的；复用环境时则可能看到之前留下的程序。

每次执行 `kubectl get ...`，客户端都会读取连接配置，向 API Server 发起查询，再把返回的对象状态显示出来。

```text
当前终端
  kubectl → 读取 kubeconfig → 请求集群的 API Server → 显示资源状态

Colima 的 Linux 虚拟机
  Docker → kind 创建的节点容器
             K8S 接收配置、安排和管理 Pod
             containerd 运行 Pod 里的容器
```

> 如果终端设置了代理，而访问本机 API 报错，先让本机地址绕过代理，再重试上面的查询。下载工具和镜像仍可沿用原来的代理：
>
> ```bash
> export NO_PROXY="localhost,127.0.0.1,::1${NO_PROXY:+,$NO_PROXY}"
> export no_proxy="localhost,127.0.0.1,::1${no_proxy:+,$no_proxy}"
> ```

另开终端时，进入实验目录重新 `source ./init.sh`，就能恢复这些连接设置。

## 先把一个 Python 程序交给 K8S

环境已经能接收命令，接下来让它运行一个程序。仓库里的 `workload.py` 根据 `MODE` 选择工作：`cpu` 模式持续计算约 12 秒，`memory` 模式不断申请内存。我们先用 CPU 模式，观察限制为四分之一核后，它实际能得到多少 CPU 时间。

为了把本地代码交给容器，先创建一个 ConfigMap：

```bash
kubectl create configmap workload --from-file=workload.py \
  --dry-run=client -o yaml | kubectl apply -f -
```

ConfigMap 是 K8S 保存配置数据的对象。这里借它保存这个很小的 Python 文件，稍后把内容挂载到容器中。`--from-file` 读取本地文件；`--dry-run=client -o yaml` 先生成对象描述，管道右侧的 `apply -f -` 再从标准输入读取并提交给集群。这样首次运行会创建对象，重复运行则更新它。[ConfigMap 与文件挂载](https://kubernetes.io/docs/concepts/configuration/configmap/)。

有了代码，还要告诉 K8S 用哪个镜像、执行什么命令、限制多少资源。在实验目录新建 `cpu-demo.yaml`，写入：

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: cpu-demo
spec:
  restartPolicy: Never
  containers:
    - name: worker
      image: python:3.12-alpine
      command: [python, -u, /lab/workload.py]
      env:
        - name: MODE
          value: cpu
      resources:
        requests: {cpu: 100m, memory: 32Mi}
        limits: {cpu: 250m, memory: 64Mi}
      volumeMounts:
        - name: code
          mountPath: /lab
          readOnly: true
  volumes:
    - name: code
      configMap:
        name: workload
```

这份 YAML 描述名为 `cpu-demo` 的 Pod。`image` 提供 Python 运行环境，`volumes` 引用刚才的 ConfigMap，`volumeMounts` 把里面的文件放到容器的 `/lab` 目录。于是 `command` 中的 `/lab/workload.py` 就有了来源；`MODE=cpu` 让它进入计算分支。`-u` 让 Python 及时输出日志。

`restartPolicy: Never` 表示这次短任务结束后不再重启，便于查看退出结果。`limits.cpu: 250m` 设置四分之一 CPU 的时间额度；`1000m` 等于一个 CPU。

现在把配置交给 K8S：

```bash
kubectl apply -f cpu-demo.yaml
kubectl get pod cpu-demo -w
```

`apply` 会提交这个 Pod 的配置。`get ... -w` 持续显示状态变化，可能看到 Pending、ContainerCreating、Running，最后是 Completed；变化快时，中间状态未必都能看到。看到 Completed 后按 Ctrl-C 结束观察，再读取程序输出：

```bash
kubectl logs cpu-demo
kubectl describe pod cpu-demo
```

`logs` 显示程序打印的内容，`describe` 显示 Pod 的配置、容器状态和事件。如果迟迟没有运行起来，就先看 `describe` 末尾的 Events，确认是在拉镜像、挂载文件还是启动程序时遇到问题。

## CPU 限制怎样影响刚才的程序

`workload.py` 的计算分支持续约 12 秒，并记录实际消耗的 CPU 时间。日志中的 `wall_seconds` 是外面等了多久，`cpu_seconds` 是进程真正占用 CPU 执行了多久；`average_cpu_cores` 是两者之比。限制为 `250m` 时，可以观察这个比值是否接近 0.25。

这里同时写了 `requests` 和 `limits`，因为“能安排到哪里”和“运行时最多能用多少”是两件事。调度器 Scheduler 用 `requests` 等条件判断节点能否接收 Pod；选定节点后，`limits` 再约束容器的资源使用。Linux 的 cgroup 机制可以为一组进程记账并限制资源，CPU limit 通常落实为每个周期允许使用的 CPU 时间。忙循环用完额度后会被节流，等额度恢复再继续。

因此程序可以一直尝试计算，但用完当前周期的 CPU 额度后就要等待。12 秒经过以后，它实际获得的 CPU 时间可能只有约 3 秒，日志中的平均值也就接近 0.25。

程序还输出 `/sys/fs/cgroup/cpu.max` 和 `cpu.stat`。前者中的配额与周期之比应为 0.25 或 1；后者的 `nr_throttled` 可以帮助确认是否发生过节流。机器负载会影响测量值，因此要把时间、配额和节流计数一起看，不能只凭“程序似乎慢了”判断限制生效。[K8S 资源配置与执行机制](https://kubernetes.io/docs/concepts/configuration/manage-resources-containers/)。

理解一组实验后，可以运行仓库的批量验证脚本：

```bash
python3 verify.py
kubectl get pods
kubectl logs cpu-250m
kubectl logs cpu-1000m
```

`verify.py` 用同样的方式提交 ConfigMap 和 Pod，只是用 Python 生成配置，再调用 `kubectl apply`。它依次运行四组实验：CPU 配额 250m 和 1 核，以及内存配额 64Mi 和 256Mi。每组结束后，它读取状态和日志，保存到 `results`，再运行下一组。CPU 两组使用同一个程序，可以对照 `average_cpu_cores` 看配额变化带来的影响。

## 内存限制：为什么 64Mi 会 OOM

后两个 Pod 逐次申请 8 MiB 内存并实际写入，最终希望保留 192 MiB。一个容器 limit 为 `64Mi`，另一个为 `256Mi`：

```bash
kubectl logs memory-64mi
kubectl describe pod memory-64mi
kubectl logs memory-256mi
```

程序保留已经申请的内存，不断向 192MiB 增长，而第一组容器总配额只有 64Mi。因此它无法在这个配额内完成目标；加上 Python 解释器等开销，业务缓冲区还没到 64Mi 就可能触及限制。本次记录显示该容器以 `OOMKilled` 结束，256Mi 组则完成了分配。判断时查看终止原因，不能只凭退出码 137 就断定发生了 OOM，因为其他 SIGKILL 也可能产生这个退出码。

CPU 可以暂停一会儿再继续，已经占用的内存却不能靠“晚一点执行”自动归还。这个例子触及 cgroup 内存限制后，内核 OOM 机制终止进程。限制真正落在 Linux 内核中；K8S 保存配置，kubelet 和容器运行时负责把配置落实到容器。

这四个实验直接创建 Pod，没有为它们配置维持副本数的控制器，并设置 `restartPolicy: Never` 保留退出结果。所以这一组 OOM 后会停下来，留下退出原因供我们查看。

## 这次运行的结果

2026 年 9 月 20 日，在 Apple Silicon Mac 上把 Colima 虚拟机缩小到 2 CPU、2 GiB 内存后，重新运行资源实验。环境仍为 kind 0.33.0，Kubernetes 1.37.0，Python 3.12。

| 容器配置 | 实测结果 |
| --- | --- |
| CPU 250m | 约 12 秒墙钟时间，2.999 秒 CPU 时间，平均 0.250 核 |
| CPU 1 | 约 12 秒墙钟时间，11.957 秒 CPU 时间，平均 0.996 核 |
| 内存 64Mi | OOMKilled；最后一条业务分配日志为 56MiB |
| 内存 256Mi | 完成 192MiB 分配，正常退出 |

CPU 配额与两组配置一致，250m 组的节流计数增加。可以将你运行得到的 CPU 时间、配额和节流计数与上表对照。自己的运行记录在 `results/summary.json`，可以对照日志复核。

## 用两个文件区分“活着”和“可以接工作”

资源限制解决了程序占用多少资源的问题，接着看它还能不能正常工作。进程退出比较容易被发现，但程序也可能还活着，却暂时无法接新任务，或者已经卡死，需要重启。若把这两种情况都当成“删除再重建”，就会把暂时不可用也变成一次重启。

K8S 用 readiness 表示是否可以接收服务流量，用 liveness 判断是否需要触发容器重启。我们先用文件模拟这两个状态，再分别观察它们的后果。

先看这次准备运行的 `health/worker.py`。它启动时创建两个文件，随后每秒打印一次文件是否存在：

```python
"""A running process with independently controllable live/ready state."""
import time
from pathlib import Path

# /tmp is reset here on each process start so injected faults clear on restart.
for name in ['live', 'ready']:
    Path('/tmp/' + name).touch()
while True:
    print('live={} ready={}'.format(Path('/tmp/live').exists(), Path('/tmp/ready').exists()), flush=True)
    time.sleep(1)
```

两个文件是我们手动控制的状态开关：删掉 `/tmp/ready` 表示暂时不接工作，删掉 `/tmp/live` 表示需要重启。程序会继续循环，因此我们能观察 K8S 如何处理“进程还在，但检查失败”的情况。

和刚才一样，先把代码保存为 ConfigMap，再提交运行配置：

```bash
kubectl create configmap health-code --from-file=worker.py=health/worker.py \
  --dry-run=client -o yaml | kubectl apply -f -
kubectl apply -f health/deployment.yaml
kubectl rollout status deployment/health-demo --timeout=120s
kubectl get deployment,replicaset,pods
```

这里改用 **Deployment** 来提交程序。刚才的 Pod 是一次性任务；现在希望程序持续运行，所以要保存“使用这份配置，保持一个副本”的目标。`health/deployment.yaml` 的关键结构如下，完整文件已在仓库中，直接使用上面的命令即可：

```yaml
kind: Deployment
metadata:
  name: health-demo
spec:
  replicas: 1
  selector:
    matchLabels: {app: health-demo}
  template:
    metadata:
      labels: {app: health-demo}
    spec:
      containers:
        - name: worker
          image: python:3.12-alpine
          command: [python, -u, /lab/worker.py]
          # 文件挂载、资源限制和探针配置见同一文件
```

`replicas: 1` 是目标数量，`template` 是创建 Pod 时使用的模板。模板中指定了镜像、命令，也像前一个实验一样挂载了代码文件。`app: health-demo` 是用来识别这组 Pod 的标签。提交后，Deployment 会管理一个 ReplicaSet，再由它创建 Pod；稍后我们通过删除 Pod 来观察这层管理的作用。

`rollout status` 等待 Deployment 的部署完成；`get deployment,replicaset,pods` 则把这些对象一起列出来。输出中会出现 `health-demo` Deployment、它管理的 ReplicaSet 和对应的 Pod，分别描述部署目标、副本管理和实际承载容器的对象。前面资源实验留下的 Pod 也可能出现在列表里，可以按名称区分。

文件存在与否怎样变成 K8S 能理解的状态？同一份 YAML 还在容器下配置了两个探针：

```yaml
readinessProbe:
  exec:
    command: ["test", "-f", "/tmp/ready"]
  periodSeconds: 2
  failureThreshold: 2
livenessProbe:
  exec:
    command: ["test", "-f", "/tmp/live"]
  initialDelaySeconds: 3
  periodSeconds: 2
  failureThreshold: 3
```

节点上的管理进程 **kubelet** 会在容器中执行 `test -f`。文件存在时，命令返回 0，探针成功；不存在时返回非零，探针失败。程序的打印只是方便我们看日志，K8S 实际使用的是检查命令的退出码。

readiness 每两秒检查一次，连续失败两次才触发这里的失败处理；liveness 在启动后先等三秒，再每两秒检查一次，连续失败三次才触发处理。状态变化需要等待探测和上报，因此执行故障命令后不一定马上看到变化。探针也可以使用 HTTP、TCP 或 gRPC，这里用 exec 直接运行检查命令，省去应用网络接口。真实程序需要根据自己的工作状态设计探针，文件只是我们可控的故障开关。

接下来亲手移除一个文件。先按标签找到刚创建的 Pod，把名称保存在终端变量 `POD` 中，然后进入它的容器执行删除命令：

```bash
POD=$(kubectl get pod -l app=health-demo -o jsonpath='{.items[0].metadata.name}')
kubectl exec "$POD" -- rm /tmp/ready
kubectl get pods -w
```

`exec` 后面的命令在容器中执行，因此删掉的是容器里的文件。等待 READY 变为 `0/1` 后，按 Ctrl-C 结束观察，再查看对应的服务端点：

```bash
kubectl get endpointslices -l kubernetes.io/service-name=health-demo -o yaml
```

readiness 连续失败达到阈值后，这个单容器 Pod 的 READY 从 `1/1` 变成 `0/1`，但容器继续运行，RESTARTS 不增加。为了观察这个状态如何影响服务端点，刚才提交的 `health/deployment.yaml` 还定义了 **Service**：它通过标签选择一组 Pod，为调用方提供稳定入口；**EndpointSlice** 则记录这组后端端点及其就绪状态。这里对应端点的 `ready` 会随之变为 `false`。

这表示系统不再把它视为通常应接收 Service 流量的就绪端点。这里借助 Service 查看端点是否就绪，关注的是 EndpointSlice 中 `ready` 字段的变化。

恢复文件，等待 READY 回到 `1/1`，再制造 liveness 故障：

```bash
kubectl exec "$POD" -- touch /tmp/ready
kubectl wait --for=condition=Ready pod/"$POD" --timeout=60s
kubectl exec "$POD" -- rm /tmp/live
kubectl get pods -w
```

这一次，kubelet 在 liveness 连续失败达到阈值后终止容器，并按这个 Deployment 的 `Always` 重启策略重新启动它。新进程执行初始化代码，重新创建两个文件，因此探针能再次通过。观察时留意 **Pod 名称保持不变，RESTARTS 增加**。后面的自动验证还会比较 Pod 的 UID；UID 是对象的唯一标识，UID 不变而重启次数增加，说明重启发生在原 Pod 内。[探针的执行与失败处理](https://kubernetes.io/docs/concepts/workloads/pods/probes/)。

健康判断也不止这两个探针。启动较慢的应用可以配置 startupProbe，让启动阶段完成后再启用 liveness/readiness。kubelet 还通过容器运行时获取进程退出情况；节点会报告状态和心跳，控制面也会处理节点不可用。打印一行 `Healthy` 本身不会自动成为 K8S 的健康信号，需要探针或其他明确配置把应用状态接入管理过程。

## Pod 被删掉后，谁记得还需要一个副本

按 Ctrl-C 结束持续观察，再删除刚才的 Pod：

```bash
kubectl delete pod "$POD"
kubectl get pods -w
```

等新 Pod 的 READY 变为 `1/1` 后，按 Ctrl-C 结束观察。你会看到新的 Pod 名称；K8S 也会为新对象分配新的 UID。容器重启策略只能处理已有 Pod 内的容器；整个 Pod 对象删除以后，还需要有地方保存“这个程序应该运行一个副本”的目标，并据此补建。

这里由 **ReplicaSet** 对象保存期望副本数、创建 Pod 的模板和标签选择条件，**ReplicaSet 控制器**负责检查并执行增删。删除前目标是一个、受管理的有效 Pod 也是一个；删除后目标没变，原 Pod 已不再计入有效副本，控制器便按模板创建替代对象。标签和归属关系限定了它管理的范围。新对象还要经过调度和容器启动，才能成为可用副本。

维持同一份模板的副本数量，可以交给 ReplicaSet。但发布新版本时，还需要组织新旧模板的交接：例如先启动一部分新副本，再逐步减少旧副本。**Deployment** 管理这层更新过程，通过调整新旧 ReplicaSet 的目标数量推进替换。本实验提交 Deployment 后，由它创建并管理当前 ReplicaSet，再由 ReplicaSet 维持副本数量。

```text
Deployment health-demo：描述模板与期望副本数
  └─ ReplicaSet：按这一版模板维持 1 个 Pod
      └─ Pod：承载 Python 容器
```

把目标改成三个，会看到同一 ReplicaSet 下多出两个 Pod：

```bash
kubectl scale deployment health-demo --replicas=3
kubectl rollout status deployment/health-demo --timeout=120s
kubectl get deployment,replicaset,pods
kubectl scale deployment health-demo --replicas=1
```

ReplicaSet 数的是受管理的有效 Pod，并不把所有“不健康”都解释成“缺少一个副本”。readiness 失败但 Pod 还在时，通常不会额外补一个。容器异常退出后，Deployment 使用的 Pod 重启策略由 kubelet 在原 Pod 内处理。真正删除了 Pod，才会触发这里演示的补建。[ReplicaSet 的职责](https://kubernetes.io/docs/concepts/workloads/controllers/replicaset/)与 [Deployment 的更新机制](https://kubernetes.io/docs/concepts/workloads/controllers/deployment/)。

| 实验中的故障 | 观察到的变化 | 主要执行者 |
| --- | --- | --- |
| readiness 连续失败 | Ready=false，端点未就绪，容器不因此重启 | kubelet 与端点控制过程 |
| liveness 连续失败 | 原 Pod 内容器重启，RESTARTS 增加 | kubelet、容器运行时 |
| Pod 被删除 | 创建新 UID 的 Pod | ReplicaSet 控制器，再由调度与节点组件执行 |

亲手操作过这些变化后，可以用脚本自动重复检查：

```bash
python3 health/verify.py
```

它依次制造 readiness 失败、恢复就绪、制造 liveness 失败，再删除 Pod，并检查每一步的 UID、重启次数和状态。输出的三条 `PASS` 对应上表中的三种行为，原始对象记录保存在 `results/health-summary.json`。

## 从一条 kubectl 命令看完整架构

[![K8S 架构：kubectl 经 API Server 保存对象，控制器维持目标，Scheduler 分配节点，kubelet 启动容器](/images/container-management/k8s-architecture.svg)](/blog/images/container-management/k8s-architecture.svg)

图可以点击放大。现在回看我们刚才执行的 `kubectl apply -f health/deployment.yaml`，就能把命令、配置和这些组件对应起来。

kubectl 先读取 YAML，并依据 kubeconfig 找到 **API Server**。它通过 Kubernetes 的 HTTPS API 查询或创建、更新资源；`kubectl get pods` 也是一次 API 读取，不是直接扫描本机进程。API Server 负责认证、授权、准入和校验等处理，并通过存储层把对象写入 **etcd**。

etcd 确实是数据库，具体是分布式键值存储。在这里保存 Deployment、Pod、配置和上报状态等集群数据；它不执行 Python 程序，也不负责把失败容器重启。让期望状态持久化，是为了控制组件重启后仍能读取目标，继续工作。常规组件通过 API Server 访问对象，而不是各自直接修改 etcd。[Kubernetes 组件职责](https://kubernetes.io/docs/concepts/overview/components/)。

Deployment 控制器观察到目标后，创建或调整 ReplicaSet；ReplicaSet 控制器再创建 Pod 对象。此时创建成功只表示对象已经登记，不等于容器已经开始运行。**Scheduler** 观察到尚未分配节点的 Pod，根据资源请求和放置约束选一个 Node，将绑定结果写回 API。

节点上的 **kubelet** 看到分配给自己的 Pod，通过 CRI（容器运行时接口）要求 containerd 等运行时准备镜像和启动容器。网络、卷和资源限制也要在这个过程中落实。进程真正开始运行后，kubelet 持续上报状态并执行探针；后续控制器根据新的对象状态继续动作。

这些动作通过 API 中的对象状态衔接：控制器创建对象，调度器写入节点分配，kubelet 再执行并上报。每个组件都可以在变化或重试时继续处理，而不要求最初那条 kubectl 命令一直等待。反复比较目标与实际状态、执行修正的过程叫调谐。终端中的 Pending、Running、Ready 分别描述不同阶段或条件，创建请求成功后，还需要观察它们才能知道程序是否已经可用。[控制器与调谐](https://kubernetes.io/docs/concepts/architecture/controller/)。

## 暂停与恢复实验环境

实验结束后可以暂停环境，保留数据：

```bash
colima stop --profile learning-lab
```

下次重新 `source ./init.sh` 即可恢复。若要理解在这些运行环境之上怎样分发函数、保留计算状态并取回结果，可以继续看[下一篇 Ray 的 Task 与 Actor](/blog/2026/09/18/ray-tasks-actors-and-kubernetes/)，实验代码也包含对应程序。
