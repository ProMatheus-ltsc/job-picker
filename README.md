# job-picker（选岗 skill）

公务员（国考 / 省考）选岗助手：**官方数据抓取 → 资格审查 → 历史进面分 → 竞争度 → 报告**。

> ⚠️ 与同名 GitHub 仓库 `job-picker`（Web 版）不同：
> 本 skill 是**命令行 + 对话驱动**的版本，无 UI，判定引擎与 Web 版同源。

---

## 一、依赖

| 组件 | 版本 | 用途 |
|---|---|---|
| Python | 3.8+ | 抓取、解析、统计（需 `pandas`、`openpyxl`、`xlrd`、`requests`） |
| Node.js | 18+ | 运行判定引擎（`pick.ts`） |

```bash
# Python 依赖
pip3 install pandas openpyxl xlrd requests

# Node 依赖（在 skill 目录内执行）
cd job-picker && npm i
```

> **为什么必须 `npm i`**：`engine/io/parseXlsx.ts` 用 `await import('xlsx')` 动态加载，
> 而 ESM 动态 import **不认 `NODE_PATH`** —— 没有本地 `node_modules` 会报
> 「文件解析失败：不是有效的 .xlsx/.xls 工作簿（或文件已损坏）」（其实是依赖没装）。

---

## 二、安装位置

把整个 `job-picker/` 目录放到 skills 目录下：

```bash
# 默认位置（按你的客户端可能不同）
~/.codebuddy/skills/job-picker/
```

---

## 三、快速开始

### 1. 抓官方职位表

```bash
cd job-picker
python3 scripts/fetch.py jobs --list                 # 看有哪些资源
python3 scripts/fetch.py jobs --get 招考简章 --out ./raw
```

### 2. 选岗（资格审查 + 竞争度 + 排序）

```bash
npx tsx scripts/pick.ts --jobs ./raw/招考简章.xls \
  --major 法学 --major-class 法学类 \
  --cities 浙江,陕西,广东 \
  --grassroots 5 --political none --degree 本科 \
  --json out.json
```

### 3. 查历史进面分（官方面试名单）

```bash
python3 scripts/sources.py list                      # ★ 先看「去哪下载」
# 下载后（或脚本自动抓）：
python3 scripts/interview_scores.py parse  --dir ./raw --out scores.csv
python3 scripts/interview_scores.py stats  --csv scores.csv --match 西安
python3 scripts/interview_scores.py lookup --csv scores.csv --codes 300110101002
```

---

## 四、数据原则（★ 本 skill 的红线）

1. **只取一手来源**：国家公务员局、各招录机关官网、教育部、国家统计局
2. **禁止第三方汇总**：中公 / 华图 / 粉笔 / 教育宝 / 各类转载 —— 一律不引用
3. **拿不到就写"无法获取"**，不用估算填充
4. **允许推算，但必须给公式 + 输入来源**，并标注 `（推算）`
5. **每条结论附来源**

代码层面由 `scripts/_guard.py` **强制**：非官方域名直接抛错，无绕过开关。

---

## 五、目录结构

```
job-picker/
├── SKILL.md                     使用规范（数据铁律 / 工作流 / 反爬 / 输出规范）
├── package.json                 依赖声明
├── assets/profile.md            考生画像输入模板
├── references/
│   ├── data-sources.md          一手数据源总表（含实测可达性 + 已归档数据集索引）
│   ├── pitfalls.md              33 条踩坑记录
│   ├── interview-scores-2026-tax-yue-zhe-shan.md / .csv   ★ 2026 年度粤/浙/陕税务局进面分（1182 岗）
│   ├── interview-scores-2025-tax-yue-zhe-shan.md / .csv   ★ 2025 年度同上（1229 岗）
│   ├── tax-scores-yoy-2025-2026.md                        ★ 跨年对比（同岗位 +3.6 分/年）
│   └── raw/{2026-tax,2025-tax}/*.xls     ★ 官方原始附件（两年度 × 3 省 × 2 名单 = 12 份）
├── engine/                      ★ 判定引擎（与 Web 版 job-picker 同源）
│   ├── types/index.ts
│   ├── core/{eligibility,competition,salary,report,mapping,filter,scoring}.ts
│   └── io/parseXlsx.ts
└── scripts/
    ├── _guard.py                来源守门（域名白名单硬校验）
    ├── sources.py               官方获取入口清单
    ├── fetch.py                 抓取器（含反爬分级处理 + Cookie 注入）
    ├── interview_scores.py      面试名单 → 进面分（fetch / parse / stats / lookup）
    └── pick.ts                  主流程 CLI
```

### 已归档的一手数据（可直接引用，无需重新抓）

| 数据集 | 年份 | 覆盖 | 岗位数 |
|---|---|---:|---:|
| 税务局进面分（粤/浙/陕） | 2025 年度 | 广东 520 · 浙江 441 · 陕西 268 | **1229** |
| 税务局进面分（粤/浙/陕） | 2026 年度 | 广东 557 · 浙江 388 · 陕西 237 | **1182** |

中位进面线：2026 年度 浙江 **131.9** > 广东 **128.2** > 陕西 **125.7**；
2025 年度 浙江 **128.8** > 广东 **124.9** > 陕西 **123.65**。
**跨年同岗位配对（806 样本）：一年上涨约 3.6 分，70% 岗位在涨。**

均为招录机关官方面试公告附件的原件，已留档并附 SHA256（详见 `references/` 下各说明文档）。



---

## 六、常见问题

**Q：`pick.ts` 报「文件已损坏」？**
A：依赖没装。执行 `npm i`。

**Q：抓取时报 403 / 412 / 连接超时？**
A：站点 WAF 或网络限制。① 用浏览器打开该页复制 Cookie → `fetch.py --cookie "k=v; ..."`；
② 或本机运行；③ 或手动下载后用 `interview_scores.py parse --dir` 解析。

**Q：为什么没有历史报录比？**
A：官方只在**报名期**实时公布报名人数，考后关闭，**不存在一手历史数据**。竞争度用**进面分**作代理。
