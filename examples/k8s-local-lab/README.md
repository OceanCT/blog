# 在 Mac 上验证 Kubernetes 与 Ray

这个实验用 Colima 的 Linux 虚拟机运行容器，用 kind 创建单节点 Kubernetes。全程命令行，不安装或启动 Docker Desktop。需要 macOS 13+、Python 3、Homebrew，建议至少 8 GB 可用内存及 15 GB 可用磁盘。初始化给虚拟机分配 4 CPU、6 GiB 内存、30 GiB 虚拟磁盘；实际资源不足时修改 setup.py 中的参数。

## 初始化

```bash
git clone --depth 1 https://github.com/OceanCT/blog.git
cd blog/examples/k8s-local-lab
brew install colima docker
source ./init.sh
kubectl get nodes
kubectl get pods
```

Apple Silicon 请使用原生 ARM64 Homebrew。初始化下载固定版本 kind/kubectl 并核对 SHA-256；创建独立 Colima profile `learning-lab` 和 kind 集群 `resource-lab`，随后加载 Python 镜像。首次需要联网下载，重复执行会复用环境。

`source` 把真实 kubectl 所在目录加入当前终端 PATH，并用 KUBECONFIG 指向本目录生成的凭据。它没有创建 `k` 别名，也没有修改你的 shell 配置。另开终端请重新 source。Docker 命令固定使用 `colima-learning-lab` context；其他终端的默认 context 不变。

## CPU 与内存限制

```bash
python3 verify.py
kubectl get pods
kubectl logs cpu-250m
kubectl logs memory-64mi
kubectl describe pod memory-64mi
```

程序分别运行四个短实验：250m / 1 CPU 下的忙循环，以及 64Mi / 256Mi 内存限制下分配 192MiB 的过程。CPU 实验计算进程 CPU 时间 / 墙钟时间，同时读取 cgroup 配额和节流计数。内存实验逐页写入，避免仅申请虚拟地址而未实际触碰内存。结果在 results/summary.json。生成的 cpu-250m.json 等文件可直接阅读，或修改后用 kubectl apply。

OOM 实验的 Pod 使用 restartPolicy: Never，保留 OOMKilled 状态供观察。Deployment 中容器退出通常会由 kubelet 重启，不能据此推断 Deployment 永远不重启。

## 健康检查与补建

```bash
python3 health/verify.py
kubectl get deployment,replicaset,pods
```

自动验证三个独立变化：readiness 失败后 Pod Ready=false、EndpointSlice ready=false 且不重启；liveness 失败后原 Pod 中的容器重启；删除 Pod 后 ReplicaSet 补建新 UID 的 Pod。该程序只打印状态，通过文件存在与否接受故障注入，没有 HTTP 服务。

手动演示：

```bash
POD=$(kubectl get pod -l app=health-demo -o jsonpath='{.items[0].metadata.name}')
kubectl exec "$POD" -- rm /tmp/ready
kubectl get pods
kubectl get endpointslices -l kubernetes.io/service-name=health-demo -o yaml
kubectl exec "$POD" -- touch /tmp/ready
kubectl exec "$POD" -- rm /tmp/live
kubectl get pods -w
# Ctrl-C 结束观察；等待容器恢复，再执行：
kubectl delete pod "$POD"
kubectl get pods -w
```

Service 只用于观察 EndpointSlice 的就绪标记；程序没有监听 80 端口，因此不要 curl 这个 Service。本实验没有验证实际流量转发或现有连接的中断行为。

## Ray

```bash
bash ray/run.sh
```

脚本在同一个 Colima 环境中构建并运行独立容器，包含 Python 3.12 与 Ray 2.58.0。容器限 2 CPU / 2 GiB，Ray 声明 2 个逻辑 CPU。三项 Task 返回词数 [2, 3, 1]，Counter Actor 累计到 6；重启 Actor 后构造函数重跑，计数回到 0。完整输出保存在 results/ray.log。该实验验证 Ray Core，没有安装 KubeRay 或验证多节点调度。

Ray 的逻辑资源用于调度，不是 cgroup 配额。本实验的硬限制来自 docker run，K8S 实验的硬限制来自 Pod resources.limits 经运行时写入 cgroup。

## 暂停与清理

```bash
# 暂停虚拟机，保留环境；下次 source ./init.sh 恢复
colima stop --profile learning-lab
```

只删除 Kubernetes 实验对象：`kubectl delete namespace resource-lab`。彻底删除这个实验的集群：`kind delete cluster --name resource-lab`，须先加载 init.sh 中的环境。以上操作只针对专用实验环境。

不要分享 kubeconfig、runtime 或完整 results 中的集群元数据。公开仓库只包含程序、配置和文档。单节点本机实验不能证明跨机器容灾或生产性能。
