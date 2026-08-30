# 公考选岗筛选工具（job-picker）

一个纯前端静态的公考岗位筛选工具：导入岗位 Excel/CSV，按多轮筛选机制打标晋级/淘汰，并结合 AI 辅助估算收入、评分排序，最终导出目标名单。数据保存在浏览器 IndexedDB，无后端、无账号。

线上地址：<https://promatheus-ltsc.github.io/job-picker/>

## 核心功能

- **数据导入**：支持 `.xlsx` / `.csv`，向导式列映射。
- **多轮筛选**：默认四轮（初筛 → 二次筛选 → 三次筛选 → 最终），每行打「待定 / 晋级 / 淘汰」标记，轮次可增删；后续轮名单 = 上一轮晋级 ∩ 考生画像过滤。
- **考生画像过滤**：按学历 + 考区强筛选，作用于所有轮次。
- **打分与排序**：总分 =（平均收入 + 到手收入 + 收入打分 + 到手收入打分）÷ 报录比（报名人数/录用人数），列可排序。
- **AI 收入分析**（逐岗位）：初筛表每行「初筛标记」后一列提供「AI 分析」按钮（桌面端 sticky 固定在右缘，无需横滚即可点击）。打开对话框后，提示词已注入该岗位的单位/职位，可直接复制或粘贴部门预算文本让 AI 估算收入，再把返回 JSON 校验回填。
  - 收入相关列导入时恒为空（不读源收入列、不自动推导打分），由 AI 回填或手动编辑。
  - 提示词口径：多数预算报表不单列在岗人数，可依据住房公积金/社保缴存反推；「平均收入」含社保/公积金/福利等全部口径；「到手收入」仅指到手工薪（不含公积金/福利）。
- **导出**：导出当前轮次名单为 CSV / 复制文本；导出 Excel 时可选导出 AI 分析记录。

## 技术栈

- Vite 5 + React 18 + TypeScript 5
- Tailwind CSS 4（table / 表单样式基于自定义 CSS + shared-core 基座）
- 共享组件基座 `@shared/core`（`file:` 本地依赖，standard 模式，pin `971b3e6`）
- 持久化：IndexedDB（shared-core `db.ts`）
- 导出：`xlsx` + 原生 Blob/剪贴板
- 部署：GitHub Pages（GitHub Actions 自动构建部署）

## 本地开发与构建

```bash
# 1) 安装共享基座依赖（peer 全声明，npm 7+ 自动安装）
cd ../shared-core && npm install --no-audit --no-fund

# 2) 安装本项目依赖
npm install

# 本地开发（HMR）
npm run dev

# 类型检查 + 生产构建
npm run build

# 本地预览构建产物
npm run preview
```

> 说明：`@shared/core` 通过相对路径 `file:../shared-core` 引用，需与共享基座仓库并置于同一父目录；`vite.config.ts` 已配置 alias 与 `resolve.dedupe`，避免双 React 导致的 hooks 白屏。
> 移动端断点依赖 shared-core 源文件的 Tailwind 采集（`main.css` 的 `@source ../../../shared-core/src`），请勿改动该路径。

## 数据与隐私

- 所有岗位数据、轮次标记、考生画像、AI 回填结果仅保存在本机浏览器 IndexedDB 中，不上传任何服务器。
- 「AI 收入分析」需你把部门预算文本粘贴到对话框后将内容发送给外部大模型，请勿粘贴敏感个人信息。
- 演示数据：未导入文件时可先加载内置演示数据体验完整流程。

## 部署

推送 `main` 后 `.github/workflows/deploy.yml` 自动构建并部署到 GitHub Pages。

## 目录结构

```
src/
├── types/        # 领域类型与 AppState 数据结构
├── core/         # 核心逻辑：映射/打分/筛选/mapping/demoAI/store(IndexedDB)
├── io/           # 导入解析(CSV/XLSX) 与导出
├── ui/           # React 视图：Wizard/MainView/JobTable/各对话框
├── styles/       # 自定义样式与 Tailwind 基线
├── App.tsx       # 路由与状态编排
└── main.tsx      # 入口
```