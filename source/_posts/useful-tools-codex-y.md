---
title: "Codex Y：给日常使用补上几处小功能"
date: 2026-09-23 05:06:43
description: "给 Codex 加上任务回收站、LaTeX 公式与本地图片显示，并修复安装组件遗漏和空会话恢复问题。"
tags: ["工具", "Codex", "终端"]
categories: ["好用的小工具"]
---

用 Codex 管理多个任务时，我想给删除操作留一个恢复入口；让它讲数学问题时，又希望矩阵、分式和多行方程能像 LaTeX 文档一样显示。于是我们在自己的 Codex 分支上做了几处修改，起名叫 **Codex Y**，启动命令是 `codexy`。

[代码仓库与使用说明](https://github.com/OceanCT/codex/tree/oceanct/agents-recycle-bin)。下面记录的是这次分支上的改动，基于我们当时使用的代码版本。

## 给任务删除加一个回收站

原来的任务管理已经有归档和永久删除。我想要的是：从列表里移走任务以后，还能在一段时间内找回来。为此，我们在归档机制上加了一份回收站记录，保存任务及子任务的状态、这次实际归档的成员和过期时间。

在 Agents 页面按 `Ctrl+K`，任务进入回收站；`Ctrl+B` 打开回收站，选中后按 Enter 恢复。普通归档仍然使用 `Ctrl+E`，不会因为这项修改而过期。

回收站保留 30 天。清理发生在服务端处理任务列表刷新时，包括重新打开 Agents 后的刷新，不需要额外常驻一个定时进程。真正删除前还要核对成员和状态：只要任务被恢复、修改，或者仍然加载着，就取消这条记录的过期删除。核心判断可以写成下面的伪代码：

```text
for entry in expired_entries:
    if same_members(entry) and all_archived_unchanged_and_unloaded(entry):
        permanently_delete(entry.root)
    cancel_expiry(entry)
```

这里省略了错误处理；读取或删除失败时，实际实现会保留记录，等待后续刷新重试。[回收站源码](https://github.com/OceanCT/codex/blob/fe6bd58a8b2f7967c69261714fd2a457db577491/codex-rs/app-server/src/request_processors/thread_trash.rs)中同时处理了恢复时取消过期记录的顺序。

## 让公式经过真正的 LaTeX 编译

原有渲染器已经能把一部分 TeX 表达式转成 Unicode 文字，但复杂公式的排版仍受终端字符网格限制。这次我们接入本地 `pdfLaTeX`，把公式编译成 PDF，再用 Poppler 的 `pdftocairo` 转成透明 PNG。Poppler 在这里负责把 PDF 页面变成终端能显示的图片。

iTerm2 已经有图片显示协议，因此修改集中在 Codex Y：识别公式、调用编译器，再把图片接到终端的布局与输出流程中。**不需要修改 iTerm2 本身。**

只把一整张图片输出到终端还不够，聊天内容会滚动，视口也会裁切。我们的做法是把图片切成一行高的条带，让每条图片先以内部标记参与文字布局，到最终写入终端时，再将标记替换成 iTerm2 的图片输出。下面省略缓存和尺寸检查，只保留这条路径：

```text
image = rasterize(compile_latex(formula))
for stripe in split_into_terminal_rows(image):
    marker = register_image_row(stripe)
    layout_as_text(marker)

# 最终输出时，只有已登记的标记才能产生图片协议指令
write_image_rows_at_layout_positions()
```

本地 Markdown 图片、用户附带的本地图片，以及已经保存到文件的生成图片，也复用这条显示路径。[图片缓存与条带实现](https://github.com/OceanCT/codex/blob/fe6bd58a8b2f7967c69261714fd2a457db577491/codex-rs/tui/src/rich_media.rs)和 [LaTeX 编译脚本](https://github.com/OceanCT/codex/blob/fe6bd58a8b2f7967c69261714fd2a457db577491/scripts/render_codex_y_latex.py)放在仓库里，正文就不展开完整代码了。

现在可以显示矩阵、积分、分式和 `aligned` 多行方程。这里编译的是聊天中的数学片段，预装了 AMS 数学宏包、`mathtools`、`bm` 等支持；任意完整 LaTeX 文档和额外宏包的自动安装不在这次范围内。远程图片 URL 仍然显示为文字标签，也不会自动下载。

为了避免渲染拖累电脑，每个 Codex Y 进程一次只编译一个公式，子进程以低优先级运行，并限制 CPU 时间、执行超时和输出文件大小。图片缓存最多保留 128 个条目、24 MiB 编码数据，重复公式可以复用结果。首次编译仍是同步调用，界面可能短暂停顿；依赖缺失或编译失败时，会回退到原有文字渲染。

## 顺手补上安装和恢复的问题

试运行时还暴露了两个问题。一个出在我们最初的安装脚本：只复制了主程序，遗漏了负责执行 Code Mode 工具调用的 `codex-code-mode-host`。能打开界面，并不能说明工具调用也能运行。现在安装器会检查这两个可执行文件，并做一次协议握手、JavaScript 执行和 shell 回调的冒烟测试。[安装器源码](https://github.com/OceanCT/codex/blob/fe6bd58a8b2f7967c69261714fd2a457db577491/scripts/install_codex_y.py)同时包含了 LaTeX 辅助脚本的安装步骤。

另一个问题出在空会话恢复：任务已经出现在列表里，但保存会话记录的 rollout 文件还没有落盘。当恢复参数变化，需要重建这个空闲会话时，旧流程可能先关闭内存里的实例，随后才发现找不到记录。

修复的关键是调整顺序，先持久化，再关闭和重建。这样持久化失败时，原会话仍然留在内存里，可以重试。对应的伪代码只有几行：

```text
if idle_thread_needs_rebuild:
    persist_thread_or_return_error(thread)
    shutdown(thread)
    resume_from_saved_rollout(thread)
```

[这项修复及回归测试](https://github.com/OceanCT/codex/commit/770532db81)验证了空会话重建，以及持久化失败后保留原实例的行为。

## 使用这个分支

Codex Y 的安装器给它单独设置了 `~/.codex-y` 数据目录和 `codexy` 命令，配置、会话数据库及守护进程与原来的 Codex 分开。安装后，`codexy` 进入对话，`codexy agents` 打开任务管理页面。

从源码构建时，需要同时构建主程序和 Code Mode Host。具体命令、构建依赖暂时不可用时的显式 host 替代方式，都写在仓库的 [CODEX-Y.md](https://github.com/OceanCT/codex/blob/fe6bd58a8b2f7967c69261714fd2a457db577491/CODEX-Y.md) 中。公式图片显示还需要本地安装相应 TeX 宏包与 Poppler；安装脚本不会自动下载这些体积较大的依赖。

本次在 iTerm2 的 Tab 中检查了行内公式、矩阵、积分、多行方程和本地 PNG 的显示效果，34 项相关 TUI 测试、4 项真实 LaTeX 编译测试通过。目前原生图片显示只在直接运行的 iTerm2 中启用；其他终端以及 tmux、Zellij 内保留文字显示。想临时关闭图片渲染，可以用 `CODEXY_RICH_MEDIA=0 codexy` 启动。
