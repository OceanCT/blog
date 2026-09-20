# 实测结果

2026-09-19，Apple Silicon Mac，Colima 0.10.3 / Lima 2.2.0，Linux VM 4 CPU / 6 GiB，Docker Engine 29.5.2，kind 0.33.0，Kubernetes 1.37.0，Python 3.12。Docker Desktop 已退出。

| Pod | 终止原因 | 结果 |
| --- | --- | --- |
| cpu-250m | Completed | 平均 0.2499 CPU；墙钟 12.000s；CPU 时间 2.999s |
| cpu-1000m | Completed | 平均 0.9982 CPU；墙钟 12.000s；CPU 时间 11.978s |
| memory-64mi | OOMKilled | {'allocated_mib': 48} |
| memory-256mi | Completed | {'result': 'allocated 192 MiB successfully'} |

Ray 2.58.0：Task 返回 [2, 3, 1]；Counter Actor 累计 6，重启后新进程状态为 0。容器限制 2 CPU / 2 GiB，Ray 声明 2 个逻辑 CPU。

数值只代表本次短实验，不是生产吞吐或跨节点容灾基准。完整原始输出保存在本地 results/。

健康检查通过：readiness 失败后同 UID、重启数不变、EndpointSlice ready=false；liveness 失败后同 UID、重启数增加；删除 Pod 后出现新 UID 的就绪 Pod。

## 2026-09-20 缩小 K8S 环境复测

Colima 调整为 2 CPU / 2 GiB；复用已有磁盘，未重建或缩盘。四组资源实验通过：CPU 250m 平均 0.24995 核，CPU 1 平均 0.99642 核；64Mi 组 OOMKilled（最后业务分配日志 56MiB），256Mi 组完成 192MiB 分配。此前 4 CPU / 6 GiB 的记录保留在上方。此配置不代表已找到最低需求，也不把旧环境上的 Ray 结果视为本配置复测。

同一 2 CPU / 2 GiB 环境下，readiness、liveness 和删除 Pod 后 ReplicaSet 补建三项检查均通过。新建环境的数据盘默认容量改为 10 GiB；本次复测保留了已有 30 GiB 数据盘，因此并未验证全新 10 GiB 数据盘安装。
