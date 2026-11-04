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

### 2. 选岗（资格审查 + 强度筛查 + 区级薪酬 + 进面概率 + 帕累托）

```bash
# 国考模式（缺省）
npx tsx scripts/pick.ts --jobs ./raw/招考简章.xls \
  --major 法学 --major-class 法学类 \
  --cities 广州,深圳 \
  --grassroots 5 --political none --degree 本科 \
  --json out.json

# 省考模式：多 sheet + 来源表驱动 5 年服务期 + 区级代理线（C 级）
npx tsx scripts/pick.ts --jobs ./raw/广东省考职位表.xlsx \
  --exam-type sk \
  --major 法学 --major-class 法学类 \
  --cities 广州,深圳 --grassroots 5 \
  --mu 67 --sigma 3.5 --cutoff 65,70 \
  --json out.json --report-out report.md --scatter-out scatter.html
```

| 参数 | 作用 |
|---|---|
| `--exam-type gk\|sk` | 国考 / 省考数据链；非法值退出码 2 |
| `--cities 广州,深圳` | 目标城市（模糊匹配），同时触发**范围外提示** |
| `--profile assets/profile.md` | 画像文件：强度偏好 / 排除区 / 最低年薪 / 接受服务期 + 学历专业等硬条件 |
| `--mu` / `--sigma` | 笔试基线与整卷波动（C 级）；不填则不算概率 |
| `--applicants 文件` | 报名人数（一手 A 级，JSON 或 CSV）；回填后概率才可算 |
| `--cutoff 65,70` | 进面线区间（省考为区级代理，C 级） |
| `--keep-heavy` | 保留被判 heavy 的值班/执法/应急岗（默认排除） |
| `--report-out` | Markdown 报告（五段式 + 口径声明 + 范围外提示） |
| `--scatter-out` | 单文件 HTML 散点图（纵轴对数） |

> **强度筛查是硬筛**：职位简介 / 招考职位 / 其他要求任一含「值班 / 夜间 / 执法 / 应急 / 三防 / 消防 /
> 信访 / 一线 / 处突 / 适合男性」即判 heavy 并排除出候选（2026-11-04 实测一次筛掉 433 岗中的 265 个）。

### 2b. 预算反推薪酬（双路径互证）

```bash
# 有 PDF（需 pdfplumber）
python3 scripts/budget_salary.py --pdf 某局2026预算.pdf --unit 某局 --out budget.json

# 无 pdfplumber：手工录入科目，零第三方依赖
python3 scripts/budget_salary.py --json-input subjects.json --out budget.json
```

方法：`工会经费 ÷ 2%`（路径 A）与 `工资福利支出 − 单位缴费`（路径 B）互证，
两路差 < 10% 才采信；人数用「内设机构数 × 每科室 3~4 人 + 局领导」反推。
基本工资占工资福利 > 60% 的单位判为**集中列支**（如区教育局代列全区教师工资），拒绝出个人薪酬。

### 3. 查历史进面分（官方面试名单）

```bash
# 0) 先找公告页（站点被 WAF 拦时尤其有用，含历史年份）
python3 scripts/interview_scores.py discover --site list
python3 scripts/interview_scores.py discover --site 陕西 --year 2025 --kw 面试

# 1) 下载名单附件（公告页 URL 或附件直链都可以）
python3 scripts/interview_scores.py fetch --url <官方公告页> --out ./raw

# 2) 解析 / 统计 / 反查
python3 scripts/interview_scores.py parse  --dir ./raw --out scores.csv
python3 scripts/interview_scores.py stats  --csv scores.csv --province 广东
python3 scripts/interview_scores.py lookup --csv scores.csv --codes 300110101002
```

> 已归档的两年度数据可直接用，无需重新抓：见 `references/interview-scores-202{5,6}-tax-yue-zhe-shan.csv`。


---

## 四、数据原则（★ 本 skill 的红线）

### 四级分级（2026-11 改造；原为「一手 / 禁止第三方」二分）

| 级别 | 定义 | 示例 | 允许用途 |
|---|---|---|---|
| **A 一手** | 官方原件 | 职位表、面试名单、部门预算、合格线公告 | 可直接进结论与**排序** |
| **B 二手·可核验** | 有原始附件或可复算式 | 含行测/申论拆解可自洽验算的进面分 | 可用（标 `（二手·可核验）`），可进**排序** |
| **C 二手·估算** | 无法验证、样本不明 | "广州 74.47"（佛山珠海三项相同 = 单岗样本） | **只读方向，禁止进排序公式** |
| **D 禁用** | 营销模板、明显矛盾 | "2026 区直 80–84 分"（超过去年全市最高分） | 不引用 |

> **为什么改**：省考官方**从不公布逐岗进面分**（面试名单只有姓名+准考证号），
> 严守二分铁律 = 省考无法做任何分数分析。改法不是"放开用二手"，
> 而是**分级 + 用途分离**：放宽只发生在标注层，**守门层不变**。

1. **A 级只认官方**：国家公务员局、各招录机关官网、教育部、财政部/国家统计局、省人事考试局
2. **D 级一律不引用**：中公 / 华图 / 粉笔的营销页、教育宝、各类转载
3. **C 级只读方向**，不进任何排序或加总公式；报告里标 `（二手·估算）`
4. **拿不到就写"无法获取"**，不用估算填充
5. **允许推算，但必须给公式 + 输入来源 + 数据级别**
6. **每条结论附来源**

抓取侧仍由 `scripts/_guard.py` **强制**：非官方域名直接抛错，无绕过开关。
排序侧由 `engine/core/datagrade.ts` 强制：C 级用于 `rank` 用途即抛 `DataGradeError`。

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
│   ├── core/{eligibility,intensity,datagrade,probability,pareto,scope,examMode,salary,report,mapping,filter,scoring}.ts
│   └── io/{parseXlsx,scatter,markdownReport}.ts
├── scripts/
│   ├── _guard.py                来源守门（域名白名单硬校验）
│   ├── sources.py               官方获取入口清单
│   ├── fetch.py                 抓取器（含反爬分级处理 + Cookie 注入）
│   ├── interview_scores.py      面试名单 → 进面分（discover / fetch / parse / stats / lookup）
│   ├── budget_salary.py         部门预算 → 人均应发（双路径互证）
│   └── pick.ts                  主流程 CLI
└── tests/                       测试（fixtures 入库，out 不入库）
    ├── fixtures/                合成样本（不含真实个人信息）
    ├── ts/probe.ts              引擎探针（供 pytest 断言纯函数）
    └── test_*.py                100 个用例，入口 python -m pytest -q
```

### 2026-11 新增能力一览

| 能力 | 模块 | 解决的问题 |
|---|---|---|
| 强度筛查 | `engine/core/intensity.ts` | 值班/执法/应急岗一天筛掉 61%，原先完全没查 |
| 数据分级 | `engine/core/datagrade.ts` | 省考无官方逐岗线，二分铁律导致无法分析 |
| 省考模式 | `engine/core/examMode.ts` | 省考分数列不存在；乡镇机关 5 年服务期 |
| 区级薪酬 | `engine/core/salary.ts` | 荔湾 18–21 vs 南沙 25–27，原先同为「广州 18–25」 |
| 预算反推 | `scripts/budget_salary.py` | 原公式缺分母（人数不披露），实际不可执行 |
| 进面概率 | `engine/core/probability.ts` | 原 `(收入+打分)÷报录比` 量纲混杂，无「落榜」概念 |
| 帕累托前沿 | `engine/core/pareto.ts` | 星级排序看不出"同薪酬但概率低 34 倍" |
| 范围外提示 | `engine/core/scope.ts` | 只扫广深会漏掉中山两个更优岗 |
| 报告模板 | `engine/io/markdownReport.ts` | 输出结构每次不同，缺什么看不出来 |
| 散点图 | `engine/io/scatter.ts` | 纯文本看不出薪酬与概率的权衡形状 |

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
