# system-to-prd

**给已经在跑的系统，补一份能跟着它一起迭代的 PRD。**

`Capture · 采集` ｜ `Iterate · 迭代` ｜ `Merge · 合并`

> 大多数 PRD 是回忆出来的。谁记得住，就写谁记得的那部分。三个月后文档停在半路，系统还在往前走，两者从此不再对账。
> 这个 skill 把顺序倒过来：**先去系统里把事实取回来，再让文档跟上系统。**

**[中文](#zh) ｜ [English](#en)**　·　[▸ 在线看](https://ronchizhang.github.io/system-to-prd/)

[![Version](https://img.shields.io/badge/version-6.8-blue)](./CHANGELOG.md)
[![Python](https://img.shields.io/badge/python-%E2%89%A53.8-blue)](https://www.python.org/)
[![Dependencies](https://img.shields.io/badge/dependencies-zero-brightgreen)](./scripts)
[![License](https://img.shields.io/badge/license-MIT-black)](./LICENSE)
[![Format](https://img.shields.io/badge/agent%20skill-SKILL.md-orange)](./SKILL.md)

![four lanes](docs/shots/hero.png)

*一个文件，四栏：原型 + 叙事 · 测试用例 · 代码逻辑 · 核查。示例模块是「学员档案字段」，全套虚构。*

---

<a id="zh"></a>

## 它默认你已经有系统了

这不是一个「帮你想产品」的工具。它默认你手上已经有一个**跑着的系统**——有测试环境、有代码仓、有用例库，只是 PRD 停在半年前的某一稿。

这个前提决定了它长成什么样。所以它最合适的场景只有一种：

> **系统已经上线，还在迭代。你要的不是重写一遍 PRD，是把现状固定成基线，然后在这个基线上改。**

整条链路就是为这件事设计的：

```text
① 全量跑一遍  →  ② 挑几个模块迭代  →  ③ 合并回全量
   现状基线         改动可指认             口径统一
```

**① 全量。** 对着测试环境把整份 PRD 跑一遍：登录进去，把每个弹窗点开、表单真提交一次、截图；再读前后端代码、比对用例库。两条以上证据支持的才写成事实，单源猜测挂编号进「待确认」，不进正文。这一步产出的是**不标改动的现状稿**——它只写系统现在怎么跑。

**② 局部迭代。** 全量稿往往有几十个模块，但这一版你只改其中三五个。挑出来，对着这份 PRD 跟 AI 说话：「这一版加一列学员端可见」→ 它出下一稿，改动粉色标注、带编号、可锚点跳转。没改的模块一个字不动。

**③ 合回去。** 改完的模块合并回全量，一套编号、一份事实源。合并前会验来源——每次产出全量，都在根目录写一份 `origin.json`，记下这一版由哪几个模块、各自什么内容指纹构成。改错了源头会被拦住，而不是悄悄混进去。

跑完一轮你得到的不是「一份新文档」，是**一个能重复的循环**：下次改，从上一稿接着走，不从零开始。

## 三个能力

| | 什么时候用 | 出来的东西 |
|:--|:--|:--|
| **① Capture 采集** | 系统在跑，但没人说得清它到底怎么跑 | 一份现状稿，每条都能追到来源 |
| **② Iterate 迭代** | 要改几页，改完怕漏、怕说不清 | 下一稿，改动带编号、带稿次、带签字 |
| **③ Merge 合并** | 几个人各管一个模块，最后要收成一份 | 一份全量，一套口径 |

### ① Capture：进去看，不靠回忆

给它一个测试环境地址和账号，它自己登录、点、提交、截图，然后回过头读代码、对用例。

事实的来源有六个，彼此不说话：

- 页面**实际渲染**成什么样（包括那个没人写过的弹窗）
- 接口**实际返回**什么（字典里是 8 个值，不是文档里写的 9 个）
- **前端那条没人测过**的分支
- **后端那条没人记下**的规则
- **测试当初实际验的**是什么
- **业务方确认过**什么，以及还有什么是没人认过的

两条以上证据支持的，写成事实；只有一条的，挂编号进「待确认」。**不知道就写不知道**——待确认清单是交付物的一部分，不是缺陷。

### ② Iterate：你不写文档，你只说话

改一版不需要重写。你说「这一版加一列学员端可见」，它做三件事：

- 改动落在该落的位置，粉色标注、带编号、可跳转
- 编号跨稿累积，稿次绑在每一处标注上——**后面再改，前面那次签字自动失效**，而不是悄悄继续有效
- 没提到的部分一个字不动，所以 diff 是干净的

![iteration](docs/shots/iteration.png)

*迭代态，和上面那张是同一份文档。左侧原型里，改动是一块粉底 + 一个编号（`C1`）；右侧叙事里是同一编号的说明，写着「定位 P1」——点它跳到改动所在的那一帧，点原型的编号再跳回来。两栏之间不是靠人记，是靠编号对上的。*

这一稿改了两处：列表加一个状态筛选（`C1`），停用确认里补一句影响面（`C2`）。顶部那行「本稿改动 2」是从标注里数出来的，不是手写的。

### ③ Merge：多人多模块，收成一份

六个人各写一个模块，合并时最容易出的问题不是格式，是**有人拿着旧稿在改**。

所以合并前先验来源：`merge_modules.py` 每出一版全量，都在根目录写 `origin.json`，记下这一版由哪几个模块、各自什么指纹构成。这是直接证据。早先那套「拿没改过的模块当指纹去推断」只能算间接证据，遇到范围覆盖全部模块就答不出来。

## 一份文件，四栏

产出的不是一份 Word，是一个**离线单文件 HTML**，四栏并排，给四种人看同一样东西。

![prototype and narrative](docs/shots/hero.png)

*原型 + 文档：左边是系统长什么样，右边是它为什么这样、要改成什么样。技术细节在这一栏不出现。*

![prototype frames](docs/shots/proto.png)

*原型单栏：9 个页面态（含全部弹窗、二级页）各一帧。这些帧不是画的，是从真实页面抓的快照转出来的，每帧带 `from` 指回快照——编不出来。*

一帧不一定是一张界面。每帧声明一个 `kind`：`ui`（真实页面，必须有快照撑着）、`flow`（状态机或时序）、`diagram`（这段逻辑为什么这么算）、`explain`（一条绕不开的规则单独做一页讲解）。复杂逻辑画出来，而不是堆成一段话——检查也知道区别对待，不会拿「必须有截图」去卡一张流程图。

![test cases](docs/shots/cases.png)

*测试用例：用例库里的条目按功能点归并，每条挂到它守的那条规则上；规则一改，能反查出要重写哪几条用例。*

![code logic](docs/shots/code.png)

*代码逻辑：上半段给人读（这个数谁算的、什么时候算、算不出来怎么办），下半段才是给研发的对照表。接口地址、字段名、枚举值不是被删了，是被搬到这里。*

![fact ledger](docs/shots/facts.png)

*核查：每条写「原说法 / 实际是什么 / 要不要按这个改」，标 P0 的必须由人裁定才能出定稿。*

| 栏 | 给谁看 |
|:--|:--|
| **原型 + 文档** | 业务方 / 产品 / 审批人 |
| **原型单栏** | 研发照着做，测试照着测 |
| **测试用例** | 测试 |
| **代码逻辑** | 研发（上半段业务也能看） |
| **核查** | 所有人，尤其不想背锅的人 |

## 一句话要过三道检查

写一句结论不难，难的是它一直是真的，而且事后没人能悄悄改掉它。

| 层 | 管什么 | 什么时候红 |
|:--|:--|:--|
| **事实** | 每条规则引的事实编号必须存在；标了「已核」的来源必须写清核到了什么 | 规则引了 `F-999` 这种不存在的编号，构建直接失败 |
| **稿次** | 每处改动都带「它在第几稿引入」，`meta.draft` 要跟标题里的稿次对上 | 标注漏了稿次、或同一处标了两个稿次，构建失败 |
| **签字** | 签字记的是**内容指纹**，不只是名字——之后动一个字，签字就失效 | 验收时发现签名还在、内容已经变了 |

签字只有一道，不是两道。小团队不会真的双签；强求双签的结果不是更严谨，是每轮检查都挂红叉，挂久了就没人看，门等于不存在。签字的人是产品经理本人，签的意思是「这一版我认了，可以往研发走」。

## 空手也能用，只是那不是它的主场

没有系统、只有一个想法，也能跑：让它从零起草一版，然后按同样的方式对话迭代。第 ① 步会因为没东西可采集而降级——这时交付里会明说这次核到了几个源，单源稿在顶部有标记。

所以：

- **有系统**：走全量 → 局部 → 合并，这是设计好的路径
- **没系统**：从零起一稿，靠对话迭代，能用，但少了「事实」这一层保护

## 用例库和代码仓不绑定任何产品

内置的两种取数方式（一个知识库连接器、一个代码托管连接器）是**参考实现，不是前提**。真实项目里这两样东西长什么样，差别很大：

| 你手上是什么 | 它怎么读 |
|:--|:--|
| Notion / 飞书 / 语雀 / Confluence / TestRail / 任何可搜的知识库 | 有连接器就用连接器 |
| 一个 `.xmind`、`.md`、`.csv`、`.xlsx`，放在目录里 | 直接读文件 |
| GitHub / GitLab / 自建 Git / 本机 clone | 托管平台 CLI，或 `harvest.py be --local <路径>` |
| 导出的接口文档、Postman 集合、一份 PDF 需求书 | 说清路径，让它读 |
| 只有一个浏览器，和一个记得住的人 | 问他，并把这一源标成「口述」 |

**它不会装作读过。** 没读到的源会带状态和原因，交付里会写明这次到底核了几个源：**≥4 正常，2–3 顶部标出来，1 出单源稿，0 拒绝开工。**

背后三条铁律：不许空口说核过（标「已核」就必须写清核到什么）；不许把「没连上」写成「没有」（前者是环境问题，后者会让人以为测试压根没写用例）；降级比阻塞好。

## 跑起来需要什么

| | 用什么 | 说明 |
|:--|:--|:--|
| **Agent 平台** | Codex · Claude Code · WorkBuddy，或任何能读 `SKILL.md` 并执行 shell 的 harness | 脚本是引擎，agent 只是司机 |
| **模型** | 推荐 **DeepSeek V4.1 Flash**——性价比最高，也是本项目主要验证的环境 | 更强的模型当然能跑，效果只会更好；这里不绑定任何一家 |
| **浏览器** | Chrome + 调试端口（`launch_chrome.py` 一条命令起） | 抓页面、实拍 |
| **运行环境** | Python ≥ 3.8，零第三方依赖 | 装完 `doctor.py` 一把过 |

## 装

```bash
git clone https://github.com/ronchizhang/system-to-prd.git
cp -r system-to-prd ~/.claude/skills/          # 或 ~/.workbuddy/skills/
python3 ~/.claude/skills/system-to-prd/scripts/doctor.py
```

`doctor.py` 打一屏：什么能用，什么不能用。`!` 开头的是缺一个增强能力（截图、读代码），不是阻塞项——PRD 照样能写。

然后开一个新对话，说一句：

```text
# 1 · 全量：这个模块现在到底怎么跑
> 给「学员管理 / 学员档案字段」跑一份 PRD，测试环境 xxx，账号 xxx

# 2 · 局部迭代：在上一稿基础上出下一版
> 基于第 1 稿，这一版加「学员端可见」列，改动标出来

# 3 · 合并：分模块做完收成一份全量
> 把这 6 个模块合并成全量 PRD
```

中间它会停下来问你**两次**：一次拿事实清单（逐条裁定），一次拿大纲（几段、几条规则、几个状态、哪些不写）。省掉这两次停，就等着返工。

## 它拒绝做的事

- **只碰测试环境。** host 里必须有以 `test` 开头的标签，否则非 0 退出。「没事你直接跑」不能覆盖这条。
- **不落任何凭据。** 每次现要，只写一个 `0600` 的临时文件，交付前再扫一遍。
- **不知道就写不知道。** 待确认清单是交付物的一部分，不是缺陷。
- **不做不可逆动作。** 真实打款、真实发邮件、删别人的数据——验证必须做才能验证的，标「未实做 + 原因」。
- **界面原型上不许写解释。** 判据是「这句话会不会出现在系统截图上」。要解释就去画一张 openly 不是截图的讲解页。
- **不许一句话塞三个分句。** 说明文案一句一件事，能拆就拆。

## 仓库里有什么

```text
SKILL.md                  agent 入口：什么时候触发、怎么跑
INSTALL.md                安装、自检、团队协作流程
assets/
  module_prd.html         四栏渲染器（数据驱动，别改）
  module.schema.json      数据契约，给人读的版本
  example_module.json     一份完整示例：现状稿，教育域，全套虚构
references/               21 份专题文档
scripts/                  25 个零依赖 Python 工具
docs/shots/               上面那几张图
tests/                    冒烟测试，含「门禁必须会红」
```

零第三方依赖，Python ≥ 3.8。

---

<a id="en"></a>

## English

**[中文](#zh) ｜ [English](#en)**

### What this is for

This is not a tool that helps you invent a product. It assumes you already have a **running system** — a test environment, a code repo, a test-case library — and a PRD that stopped at some draft months ago.

That assumption decides everything about its shape. There is really only one scenario it is built for:

> **The system shipped, it is still iterating, and what you need is not a rewrite — it is to pin the present down as a baseline and move forward from there.**

```text
① capture everything  →  ② iterate a few modules  →  ③ merge back
   as-is baseline           every change provable        one set of terms
```

**① Capture.** Log into the test environment, open every dialog, submit the form for real, screenshot the pages; then read the front-end and back-end code and cross-check the test-case library. Two or more sources agreeing makes a fact; a single guess gets an ID and goes to *pending confirmation*, never into the body. What comes out is an **as-is draft** — it says how the system works today, with no change marks.

**② Iterate.** A full pass usually covers dozens of modules, but a given version touches three or five. Pick them, then **talk to the document**: *"this version adds a per-participant visibility column"* → Draft N+1, with the change marked in pink, anchored, numbered, and bound to the draft it belongs to. The modules you did not mention are not touched at all.

![iteration](docs/shots/iteration.png)

*The same document as the screenshot above, one draft further. In the prototype lane a change is a pink block with a number (`C1`); in the narrative lane the same number carries the explanation plus a "locate P1" link — click it to jump to the frame the change lives in, click the number in the prototype to come back. The two lanes are held together by numbering, not by memory.*

This draft changes two things: a status filter on the list (`C1`), and an impact count in the deactivate dialog (`C2`). The "2 changes" badge at the top is counted from the annotations, not typed by hand.

**③ Merge.** Fold the changed modules back into the full document — one numbering scheme, one source of truth. Before copying anything back it checks provenance: every time `merge_modules.py` writes a master, it also writes an `origin.json` recording which module versions that master was built from. Direct evidence. The older approach — fingerprinting the untouched modules — could only infer, and fell apart when the range covered every module.

What you end up with is not "a new document". It is **a loop you can run again**: next time you start from the last draft, not from zero.

### Three capabilities

| | When | What comes out |
|:--|:--|:--|
| **① Capture** | The system runs, but nobody can say exactly how | an as-is draft, every line traceable |
| **② Iterate** | A few pages change, and you cannot afford to miss one | the next draft, changes numbered, drafted, signed |
| **③ Merge** | Several people, several modules, one document | one master, one vocabulary |

### One file, four lanes

The deliverable is not a Word file. It is a **single offline HTML** with four lanes side by side, so four kinds of readers look at the same thing.

A frame is not necessarily a UI. Each one declares a `kind`: `ui` (a real screen, must be backed by a snapshot), `flow` (a state machine or sequence), `diagram` (why the logic works that way), `explain` (a reading page for a rule too tangled to say in prose). Complex logic gets drawn instead of piling up paragraphs — and the checks know the difference, so a diagram is not held to "must be a screenshot".

| Lane | For |
|:--|:--|
| **Prototype + narrative** | business / product / approver |
| **Prototype only** | engineers build from it, QA tests from it |
| **Test cases** | QA |
| **Code logic** | engineers (business can read the top half) |
| **Evidence** | everyone, especially whoever does not want to be blamed |

### A claim has to survive three checks

| Layer | What holds | Where it fails |
|:--|:--|:--|
| **Fact** | every rule cites fact IDs that exist; a source marked "verified" must say what was verified | a rule pointing at `F-999` stops the build |
| **Draft** | every change mark carries the draft it belongs to, and `meta.draft` matches the title | a mark without `data-draft`, or two drafts for one change, stops the build |
| **Sign-off** | signing records a **content fingerprint**, not just a name — edit anything afterwards and the signature expires | the gate shows a stale ✓ until it is re-signed |

One signature, not two. Small teams do not double-sign; requiring it just produced a permanent red X that stopped carrying information. The signer is the product owner, and what they sign is "this draft is closed, it can go to engineering".

### You can also start from nothing

No system, just an idea? It works — draft from zero, then iterate by conversation the same way. Step ① degrades: there is nothing to capture, so the deliverable states how many sources were actually verified, and a single-source draft is flagged at the top.

With a system, the full → partial → merge path is the intended one. Without one, you still get a document, minus the "evidence" layer.

### Bring your own sources

The two built-in ways of reading test cases and code are **reference implementations, not requirements**.

| What you have | How it gets read |
|:--|:--|
| Notion · Feishu · Yuque · Confluence · TestRail · any searchable knowledge base | connector, if one exists |
| an `.xmind` · `.md` · `.csv` · `.xlsx` sitting in a folder | read straight from disk |
| GitHub · GitLab · self-hosted Git · a local clone | code-host CLI, or `harvest.py be --local <path>` |
| exported API docs, a Postman collection, a PDF spec | point at the path, it reads |
| nothing but a browser and a person who remembers | ask them, and label the source as verbal |

What it will **not** do is pretend. A source it could not read is marked with a status and a reason, and the deliverable states how many sources it actually verified: **≥4 is normal, 2–3 gets flagged at the top, 1 produces a single-source draft, 0 refuses to start.**

Three rules behind that: never claim a source was read without saying what was read; never write "not connected" as "does not exist"; degrading beats blocking.

### What it refuses to do

- **Only touches the test environment.** The host must carry a label starting with `test`, otherwise it exits non-zero.
- **Never persists credentials** — asked on every run, written only to a `0600` temp file, audited before delivery.
- **Writes "unknown" instead of guessing.**
- **No irreversible actions** — real transfers, real emails, deleting other people's data. If verification needs it, the row is marked *not performed + why*.
- **Refuses explanatory text drawn onto a UI prototype.** Test: *would this sentence appear in a screenshot of the product?*
- **Refuses one-sentence-three-clauses.** Explanatory copy gets split.

### Setup

```bash
git clone https://github.com/ronchizhang/system-to-prd.git
cp -r system-to-prd ~/.claude/skills/          # or ~/.workbuddy/skills/
python3 ~/.claude/skills/system-to-prd/scripts/doctor.py
```

`doctor.py` prints one screen: what works, what doesn't. A `!` line means a missing enhancement, not a blocker.

| Layer | Works with |
|:--|:--|
| **Agent harness** | Codex · Claude Code · WorkBuddy · any agent that reads `SKILL.md` and can run shell |
| **Model** | **DeepSeek V4.1 Flash** — recommended: best cost/performance, and the environment this project is primarily verified on |
| **Browser** | Chrome with a debug port (`launch_chrome.py` starts one) |
| **Runtime** | Python ≥ 3.8, zero third-party dependencies |

---

## Credits & scope

Built and battle-tested on a real internal back office. The module shape here — a field-configuration screen with per-tenant, per-region, per-product field sets — is the shape of the original work. **Every name, tenant, endpoint, product code and logo has been replaced**, and the whole sample has been moved to a different industry (an online-education back office), so nothing of the original business domain survives. `assets/example_module.json` is a self-consistent fictional sample, as an as-is (Draft 1) PRD.

Use it only on systems you are authorized to access.

## License

MIT — see [LICENSE](./LICENSE).
