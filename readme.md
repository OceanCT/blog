# OceanCT / Notes

个人学习笔记站。Hexo + 自定义 `ocean` 主题，部署到 https://oceanct.github.io/blog/ 。

首页按主题展示专栏，支持搜索专栏名称与文章标题、摘要。专栏目录与文章页的上一篇、下一篇按阅读顺序排列；归档继续按时间查看。旧内容保存在 `legacy/posts`，不会进入网站。

## 本地预览

```bash
npm ci
npm run clean
npm run build
npm run server
```

浏览 http://localhost:4000/blog/ 。主题位于 `themes/ocean`；`scripts/empty-pages.js` 保证空站也能生成首页和归档。

## 记录笔记

仓库中的 `skills/note` 可复制到 `~/.codex/skills/note`。随后调用：

```text
$note 把我们刚才学习的内容整理成笔记，记录到博客。
```

Skill 会整理实践过程、选择依据、集中讨论的问题和难点，生成文章页面供你审阅。你确认“没问题”后，它自动提交源码、推送 GitHub 并通过 `npm run deploy` 发布到 `gh-pages`，无需再次授权。每篇新笔记默认先审阅，不会自行生成样例内容。

新文章包含 `title`、`date`、`description`、`tags`。保留已有文章文件名和日期，避免改变公开链接。

## 发布

源代码与站点发布分开管理。提交并推送源代码后：

```bash
npm run clean
npm run build
npm run deploy
```

GitHub Pages 应读取 `gh-pages` 分支根目录。仓库历史跟踪了依赖和构建输出，请明确选择提交文件，避免混入缓存变动。

## 专栏与阅读顺序

在 `source/_data/columns.yml` 中维护专栏名称、简介与文章 slug 列表。`posts` 的顺序就是阅读顺序，不依赖发布日期。新增文章后，将它的文件名（去掉 `.md`）加入相应专栏。新增 K8S、推理等主题时增加一个配置项即可，主题会自动生成 `/columns/<id>/` 页面；还没有文章的专栏不展示。

`/tools/` 保留为实用 Skill 目录入口，已有文章链接保持不变。未加入专栏的文章仍可从归档访问。
