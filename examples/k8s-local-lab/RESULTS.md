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
