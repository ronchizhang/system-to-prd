# Install & run

> Works with any agent that reads `SKILL.md` — Claude Code, WorkBuddy, Cursor rules, or a plain Python shell.
> The scripts are the engine; the agent is just the driver. You can run every step by hand.

## English quick start

```bash
git clone https://github.com/<you>/system-to-prd.git
cp -r system-to-prd ~/.claude/skills/            # Claude Code
# or: unzip system-to-prd.zip -d ~/.workbuddy/skills/
python3 ~/.claude/skills/system-to-prd/scripts/doctor.py
```

Three things to connect before the first run (all optional — each missing one costs you a source, not the whole run):

| Need | Why | If missing |
|:--|:--|:--|
| Browser control (Chrome with a debug port) | click through the test environment, capture real pages | prototypes can only be drawn from memory |
| A test-case source (any searchable knowledge base, or an exported xmind) | check "does the case actually say that" | one source marked unverified |
| A code host CLI or a local clone | read front-end / back-end truth | code sources marked unverified |

Credentials are asked for on **every** run, never stored. `doctor.py` tells you exactly which of the above works.

---

## 装这个包：三步，十分钟

> **当前版本 v6.1**（2026-11-03）。这一版是结构性的：一份 PRD 拆成**四栏，一栏一个读者**。
> 以前正文里同时有业务规则、接口地址、字段名、用例编号，三拨人读同一段，谁都读不顺。
> 现在业务方只看「原型 + 文档」，测试只看「测试用例」，研发只看「代码逻辑」。
> 装完想知道这版改了什么，看包内 `SKILL.md` 末尾的版本记录。

这个 skill 做的事：**进测试环境，按五源核查，产出带原型的 PRD**。两种交付：

- **现状 PRD** —— 系统现在怎么跑，照实记录，不标改动；
- **迭代 PRD** —— 在上一稿基础上设计下一版，本次改动用粉色标注 + 锚点跳转，开工先确认终端/产品版本/稿次/改动范围。

产出一个 HTML，顶栏**四栏，一栏一个读者**：

| 栏 | 给谁看 | 里面是什么 |
|:--|:--|:--|
| **原型 + 文档** | 业务方 / 产品 / 审批人 | 业务规则、交互规范、状态机、实体关系、异常边界；**不放接口地址和字段名** |
| **测试用例** | 测试 | 用例按功能点分组，每条挂到它守的那条规则上 |
| **代码逻辑** | 研发（上半段业务方也能看） | 上半段大白话问答，下半段前端 / 后端对照 |
| **核查** | 所有人 | 五源事实清单，每条追得到来源 |

> `?m=cases` / `?m=code` / `?m=facts` 可以直接打开某一栏，发链接时能指到具体那栏。

---

## 一、装

### 方式 A · 拖 zip（推荐，最省事）

1. 打开 WorkBuddy，左侧点「**技能**」
2. 右上角「**添加技能**」→「**上传技能**」
3. 把这个 zip **不要解压**，直接拖进去
4. 弹确认框点允许
5. **新开一个对话**（技能是启动时扫描的，旧对话认不出新装的）

### 方式 B · 解压到目录（拖 zip 失败时用）

```bash
# 用户级：所有项目都能用
unzip system-to-prd-v6.1.zip -d ~/.workbuddy/skills/

# 或项目级：只在这个项目里用，跟着项目走
unzip system-to-prd-v6.1.zip -d <项目目录>/.workbuddy/skills/
```

解压后路径必须是这样，**不能多套一层**：

```
~/.workbuddy/skills/system-to-prd/SKILL.md   ✅
~/.workbuddy/skills/system-to-prd/system-to-prd/SKILL.md   ❌ 多套了一层，认不出
```

装完新开对话。

---

## 一·五、先记住这一条：命令怎么写

本文所有命令都写 `python`。对着自己的系统换：

| 你的系统 | 用哪个 | 说明 |
|:--|:--|:--|
| **Windows** | `python` | 装 python.org 版自带；也可以 `py -3` |
| **macOS** | `python3` | 系统里没有 `python` 这个命令（早年被移除了） |
| **Linux** | `python3` | 同上 |

也就是说：**Windows 上照抄本文，mac / Linux 上把每个 `python` 换成 `python3`。**

路径写法同理，Windows 用反斜杠也行、正斜杠也行（Python 两种都认），
但**路径里有空格一定要加引号**：`python "D:\我的 项目\run.py"`。

---

## 二、自检：装完先跑这一条

```bash
python ~/.workbuddy/skills/system-to-prd/scripts/doctor.py
```

（项目级就把路径换成 `<项目目录>/.workbuddy/skills/system-to-prd/scripts/doctor.py`）

看到这样就算好了：

```
 ✓ Python           3.13.12（需要 ≥ 3.8）
 ✓ 文件完整性          21 项齐全
 ✓ CDP 客户端         包内 vendor_cdp
 ✓ Chrome 调试端口     9222 已就绪
 ✓ Chrome 可执行文件    /Applications/Google Chrome.app/...
 ✓ 代码仓库命令行         1.18.25
 ✓ 模板可渲染          样例构建成功 151 KB

结论：全绿。
```

**有 `!` 提醒不用慌**——缺的只是截图 / 读后端码这类增强能力，PRD 正文照样能写。
`Chrome 调试端口` 那一项要截图时再开：

```bash
python ~/.workbuddy/skills/system-to-prd/scripts/launch_chrome.py
```

---

## 三、开工前要准备的四样（不绑定任何产品）

| 要什么 | 首选 | 没有就用 | 都没有会怎样 |
|:--|:--|:--|:--|
| **用例来源** | 知识库连接器（Notion / 飞书 / 语雀 / Confluence / 任意可搜的知识库） | 导出 `.xmind` / `.md` / `.csv` / `.xlsx` 丢进工作目录 | 少一个源，`sources` 里标 `未核` 并写原因 |
| **代码来源** | 托管平台 CLI 或连接器（GitHub / GitLab / 自建 Git） | 本地 `git clone` 后 `harvest.py be --local <路径>` | 代码两源标 `未核`，交付说明写明未核代码 |
| **浏览器控制** | Chrome 调试端口（`launch_chrome.py` 一条命令） | Playwright / 手动截图放进 `snapshot/` | 原型只能凭印象，必须标「非实拍」 |
| **测试环境账号** | 后台 / 主办方端 / 报名者端 三套 | 有几套给几套，缺的端标「未核」 | 那一端什么都做不了 |

**关键一点：这四样没有「必须先装好」的门槛。** 连接器能连就连，不能连就找导出文件，再不行让人把内容贴进对话——
缺哪个源就在 `sources` 里如实标哪个，交付照样能出，只是强度不同。

降级规则（写进硬约束，门禁会查）：

- ≥4 源：正常出稿
- 2–3 源：顶部标「本稿 N 源核查，缺 xx」
- 1 源：出**单源稿**，版本号后加「（单源稿）」
- 0 源：不许开工

完整的换源对照表、三种接入方式（文件投放 / CLI / MCP）、最小验收标准见 `references/sources-adapters.md`。

浏览器控制在 WorkBuddy 的「设置 → Agent → 浏览器控制」；连接器在「连接器」页里加。
账号密码**每次开工现要**，skill 不会存。

---

## 三·五、原型怎么来的（这是这个包最关键的一条）

**原型图不是画出来的，是从真实页面抓出来的。** 全自动，两步：

```bash
# ① 起一个带调试端口的浏览器 —— 必须加 --headed，因为要你亲手登录
python ~/.workbuddy/skills/system-to-prd/scripts/launch_chrome.py --headed
#    它会弹出一个新窗口。这个窗口用的是**全新配置目录**，里面没有你的登录态，
#    所以你还要在这个窗口里把测试环境登录一遍。登录一次就够，后面都复用。
#    脚本本身不碰你的密码。

# ② 抓页面骨架 → 结构化快照（同时存实拍截图）
python ~/.workbuddy/skills/system-to-prd/scripts/snapshot_page.py \
    --base https://test1x.example.com --url /a/b --key <模块key> --page p1 --name 列表

# ③ 快照 → 原型帧，写进模块数据
python ~/.workbuddy/skills/system-to-prd/scripts/proto_from_snapshot.py \
    --snapshot snapshot/<模块key>.json --data modules/<模块key>.json --write
```

抓的是**结构**：标题、描述、面包屑、页签、顶栏与侧栏菜单（连层级）、
表单分组与字段（类型/必填/选项）、表格（列/首几行/状态标签）、按钮、分页。
所以生成的原型和真实页面同构 —— 真实 8 列就 8 列，真实有「可填写/隐藏」就上标签。

弹窗用 `--open "按钮文案"`，页签用 `--tab "页签名"`。

**为什么非要这么干**：手画必漏。漏掉的列、漏掉的字段，看图的人根本发现不了，
等到研发按图写代码才暴雷。脚本抓的每一帧都带 `from` 字段指向快照，
验收会去查这个文件在不在 —— **编不出来**。

---

## 三·六、叙事按六段骨架写（v5.3 起，不用背，写了歪门禁会报）

**判据先分清**：迭代 PRD 只写改动点；现状 PRD（system-to-PRD）才写全量功能。

| 段 | 必填槽 | 最常见的写错 |
|:--|:--|:--|
| **1 定位** | 数据范围 / 访问路径 / 功能权限（穷举，含「本页没有哪些动作」）/ 数据权限 / 归属字段；外加「本次改什么」「**不改什么**」两张表 | 写成「本页面用于管理 XX」——五个槽全空 |
| **2 业务背景** | 三段：现状怎么做 → 错在哪 → 方案与本文边界；末尾典型场景表（场景 / 前提 / 页面显示 / 看的人据此做什么） | 把四五个场景揉成散文，读者翻三屏才看到要改什么 |
| **3 主流程** | 步骤 × 改造前 × 改造后 × 差异，四列对照 | 用 `<ol>` 讲一遍流程，看不出哪步变了 |
| **4 字段** | **两块分开**：①字段约束表（控件 / 值域 / 校验时机 / 越界处理 / 取数来源 / 本次变化）②改动点清单 | 字段说明和改动叙述混在一段，24 张表里夹 12 个「改①」 |
| **7 异常边界** | 情形 / 触发条件 / 系统行为 / 禁止做法·兜底，四列 | 十来条 `<ul>` 要点，「两条同时不满足先弹哪个」答不出来 |
| **8 待确认** | 由 `questions` 渲染，**一行都不手写** | 手抄一遍，改数据后必脱节 |

两条位置规则：

- **改动点只放第 4 段末**，按页面区域分组（列表页 / 详情页 / 弹窗各一组）。散到主流程、异常段里，想统计「这稿改了几处」只能全文 grep。
- **第 1 段说「共 N 处改动」，第 4 段就得有 N 个改动块**。这一条现在机器会查——少写一条正文，`check_delivery.py` 直接 FAIL 并点名是哪个编号。

模板与反例见包内 `references/narrative.md`（每段给了可照抄的 HTML 片段）。

---

## 三·七、用例栏与代码栏怎么填（v6.1 起，这两栏最容易写成空壳）

**用例栏（`testcases`）**：从 用例库取回后不是直接粘。xmind 是「想到哪写到哪」的分支树，要做三件事：

1. **按功能点归并**：同一个功能点的几个分支合成一条，输入差异写进步骤；不要一个分支一条。
2. **砍掉不可判定的**：预期写「正常显示」「符合预期」的，要么补成可判定的（看到什么字、变成什么状态），要么删。
3. **挂规则**：每条标它守的是哪条 `R-xxx`。筛选、分页、导出这类页面通用行为**确实没有规则**，`rules` 留空，
   但要在 `norule` 里写一句为什么（「页面通用行为：筛选与分页」）。**空着不写，门禁当成漏挂**。

用例库与现状对不上的地方写在 `gap` 里：「用例仍按 A 判，本次改为 B，需重写」。这条比用例本身有用——它标出了重测范围。

**代码栏（`code`）**：两段，缺一不可。

- 上半段 `plain`：问答体。问的是**业务方真会问的那句**（「这个金额是谁算的」「为什么编辑停用字段它会变回启用」），
  答的是**系统实际做法**，句式是「谁 + 什么时候 + 算出什么 + 算不出来怎么办」。不许出现「视情况而定」。
- 下半段 `fe` / `be`：三列——位置 / 做什么（数据从哪来、什么条件下拒绝）/ 代码位置。代码位置可以写「—」，但不能瞎填。
- 末尾 `notes`：并发、超时、精度、第三方字段漂移，一条一句说清「现在怎么兜、兜不住会怎样」。

**技术细节不是删掉，是搬家**：正文里删掉的接口地址、字段名、常量名，必须能在代码栏或附录 B 查到。
两处都空，`check_delivery.py` 直接 FAIL——因为研发没法动手。

**实体关系（`entities`）**：只写 5–7 个一级实体，每个三行——一句话是什么 / **谁生成** / 关键点。
「谁生成」必填，出问题时第一个要问的就是「这条数据谁造的」。不要写字段清单（那是代码栏的事）。

---

## 三·八、验收怎么算过

```bash
# 单模块交付验收（--strict 才是门禁，不加只是体检）
python scripts/check_delivery.py --root . --module <key> --strict

# 措辞体检：禁用词（友好提示 / 视情况而定 / 类似 / 同上 …）
python scripts/scan_wording.py --path modules/
```

`check_delivery --strict` 查三层：过程留痕、交付物反查、合并一致性。其中「叙事骨架」组会查 S1 声明数与第 4 段块数是否一致、索引里的编号正文有没有、S3/S7 是不是真写成了表格。

**文档级确认**（小团队用这个，不用凑 12 个签名）：

```bash
python scripts/gate.py doc --root . --by 你的名字 --note "整份看过，可以发"
```

签完 `run.json` 里留痕（含稿次），总览页顶部那条灰条变绿。**改稿后自动失效**，需要重签。

---

## 四、第一次用：直接说这句话

> 用 system-to-prd 给「报名管理 / 报名字段配置」跑一份 PRD，测试环境地址 xxx，账号 xxx

它会走七步：环境自检 → 圈边界 → 五源采集 → 闸门 1 事实清单 → 闸门 2 骨架确认 → 填数据 → 构建实拍 → 验收。

**中间会停下来问你两次**：

- **闸门 1**：把核查出的事实清单给你过，P0 的逐条问「这条实际是什么、要不要按这个改」
- **闸门 2**：把骨架和待确认问题给你过

这两次不要嫌烦。跳过闸门直接写，出来的东西一定返工。

---

## 五、团队分工怎么用

你是团队里被分了模块的那个人，你只需要做三件事：

**1. 建自己的工作台**

```bash
python ~/.workbuddy/skills/system-to-prd/scripts/init_run.py \
  --root ./prd-run --project "示例后台 全量 PRD" \
  --module "管理后台|报名管理 / 报名字段配置|ops-person-field|你的名字"
```

`--module` 格式：`系统|一级 / 二级 / 三级|全局唯一 key|负责人`。
**key 不能和别人撞**，命名建议 `系统-模块`，如 `demo-form-field`、`demo-partner-config`。

**2. 填两个文件，别碰第三个**

| 填这个 | 里面是什么 |
|:--|:--|
| `prd-run/facts/<key>.facts.json` | 五源核查发现的事实清单（唯一事实源） |
| `prd-run/modules/<key>.json` | ①原型帧 ②叙事 8 段 ③AI 读 ④事实镜像 |

`prd-run/out/<key>.html` 是自动生成的，**手改会被下次构建覆盖**。

**3. 构建 + 验收**

```bash
cd 你的工作台

# 构建（--facts 会把台账同步进模块数据，你不用抄两遍）
python ~/.workbuddy/skills/system-to-prd/scripts/build_module_prd.py \
  --data modules/<key>.json --facts facts/<key>.facts.json \
  --out out/<key>.html --strict

# 验收：全绿才算交了
python ~/.workbuddy/skills/system-to-prd/scripts/check_delivery.py \
  --root . --module <key> --strict
```

---

## 六、三条红线（不遵守，合并时一定出问题）

1. **不改模板**。`assets/module_prd.html` 是所有人的渲染引擎，改了就合并不了。
2. **原型不许写 `style=`**。只用 `px-` 组件 class（清单见 `references/prototype-kit.md`），
   写了契约会直接拒。十个人十种样式，包成全量后必散。
3. **拿不准的写进「要你定」，不许编**。编一个看起来合理的答案，比留白的危害大得多。

---

## 七、包里都有什么

```
system-to-prd/
├── SKILL.md                      AI 读的入口：什么时候触发、怎么跑
├── INSTALL.md                    你正在看的这份
├── assets/
│   ├── module_prd.html           四栏模板（原型+文档 / 用例 / 代码 / 核查，勿改）
│   ├── module.schema.json        数据契约可读版
│   └── example_module.json       完整样例：9 帧原型 + 15 条用例 + 代码栏 + 5 个实体，照着填
├── references/                   17 份参考，按需查不必通读
│   ├── narrative.md              **叙事六段骨架 + 用例栏 / 代码栏 / 实体关系写法** + 可抄的 HTML + 反例
│   ├── team-runbook.md           **同事操作卡**：六步 + 三红线 + 常见错误表
│   ├── prototype-kit.md          原型组件清单：px- 全组件 + 页型配方
│   ├── doc-8sections.md          四块结构、8 段逐段要求、事实清单字段
│   ├── five-sources.md           五源各自通路、证据强度分档、冲突处理
│   ├── css-pitfalls.md           样式坑 16 条（含 code 溢出、.warnbar 误用、编号跳转被索引标签抢走）
│   ├── gates.md / naming.md / change-ledger.md   门禁、稿次命名、改动台账
│   └── capture.md / redraw-spec.md / interaction.md / deliver-modes.md …
└── scripts/                      24 个，零第三方依赖
    ├── doctor.py                 环境自检（装完先跑）
    ├── init_run.py               建工作台 + 骨架 + 看进度
    ├── launch_chrome.py          起带调试端口的 Chrome
    ├── snapshot_page.py          抓页面骨架 → 结构化快照（含实拍）
    ├── proto_from_snapshot.py    快照 → 原型帧
    ├── harvest.py                四源采集：枚举 / 接口 / 前端 chunk / 后端码
    ├── build_module_prd.py       数据 → 单文件四视图 PRD
    ├── check_delivery.py         交付验收（含叙事骨架检查）
    ├── scan_wording.py           措辞体检：禁用词
    ├── gate.py                   闸门：模块级签名 / 文档级确认
    ├── merge_modules.py          多模块 → 全量 PRD
    ├── shot_verify.py            实拍核对 + 结构诊断
    └── vendor_cdp.py             内嵌的 CDP 客户端（所以不装别的 skill 也能截图）
```

零第三方依赖，只要 Python ≥ 3.8。

---

## 八、卡住了

| 现象 | 原因 | 怎么办 |
|:--|:--|:--|
| 对话里说触发词没反应 | 装在旧对话里 / 目录多套了一层 | 新开对话；检查路径是不是 `.../system-to-prd/SKILL.md` |
| `doctor.py` 说找不到模板 | 解压时目录结构错了 | 重新解压，确认没有多套一层 |
| 截图全黑或超时 | Chrome 没开调试端口 | `python scripts/launch_chrome.py` |
| `连不上 CDP` | 9222 被别的程序占了 | `--port 9333` 换端口，同时给 `shot_verify.py --port 9333` |
| 读后端代码失败 | 代码仓库 没连，或 `cnb` 不在 PATH | 先连代码仓库连接器；或 `harvest.py be --local <本地仓库路径>` |
| 验收报「有 N 处 TODO」 | 骨架没填完 | 正常，说明还没做完 |
| 验收报「规则没挂依据」 | 规则的 `facts` 字段空着 | 填上真实存在的 `F-xx`，正文才能点回核查 |
| 合并时报「规则编号重复」 | 和别人撞号了 | 改编号段，如 `R-OPS-FIELD-` / `R-OPS-CUST-` |

还不行就把 `doctor.py` 的输出贴给负责人。
