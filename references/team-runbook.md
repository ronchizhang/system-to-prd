# 怎么干活

你负责**一个后台模块**，把它变成一页可交付的 PRD。所有模块最后由一个人合并成全量 PRD。
你不需要理解这套系统怎么设计，按下面步骤做，按格式填，就行。
**先做第 0.5 步**：确认这次是「记录现状」还是「设计新版」——弄错这一步，后面全白做。

> 引擎 `system-to-prd@2.0`。格式、样式、交互都锁在引擎里，你改不了——这是故意的。

---

## 零、命令名先对一下

本文命令都写 `python`。**Windows 照抄；mac / Linux 把 `python` 换成 `python3`。**

路径有空格要加引号。其余没差别。

---

## 第 0 步 · 开工前，三件事缺一件就停

| 要什么 | 怎么确认 |
|:--|:--|
| **用例库已连接** | 能搜到 `全功能用例` 这个知识库 |
| **代码仓库已连接** | 能读到仓库 `yourgroup/yourproject/demo/demo-backstage` |
| **测试环境账号** | 后台 / 企业端 / 人员端 三套。**只给测试环境的，生产的一律不要** |

确认测试环境（脚本看域名里有没有环境词：test / uat / sit / dev / staging / pre / qa。**它只是提示，不是门禁**，但看错环境的代价是拿真实数据在跑——地址拿不准就直接问对方）：

```bash
python <skill>/scripts/check_test_env.py https://test1admin.xxx.com
```

登录（账号密码每次现要，不要写进任何文件、不要复用别人的）：

```bash
python <skill>/scripts/login.py --url <登录页> --api <网关> \
  --path /demobackstage/login/loginUser --user <账号> --out <临时目录>/prd_token.json
```

> 有验证码/短信就停，让自己的机器上登一次，再连 9222 复用会话。**别硬试，会触发风控。**
> 登录失败 3 次就停。

---

## 第 0.5 步 · 先问清：这次是「记录现状」还是「设计新版」

**问错这一步，后面全白做。**

| 你听到的是 | 你要做的是 |
|:--|:--|
| 「把这个模块整理成 PRD」「现在是怎么算的」 | **现状 PRD**：照实记录，**一个粉块都不加** |
| 「这版要加 XX」「基于上一稿改」「把这次改动标出来」 | **迭代 PRD**：只做增量，改的地方标粉 + 加锚点 |

做迭代 PRD，开工前必须拿到四个答案，**缺一个就停下来问**：

1. 改哪个终端（管理后台 / 企业端 / 员工端）
2. 这一版的产品版本号（如 `管理后台 V5.0`）
3. 基线是上一稿的哪一份
4. 本次改动范围（哪几个模块、新增还是修改、一句话）

然后登记，不登记就别动手：

```bash
python <skill>/scripts/plan_iteration.py --root <工作台>          # 先看：上次做到第几稿
python <skill>/scripts/plan_iteration.py --root <工作台> \
  --set --mode iterate --terminal 管理后台 --product "管理后台 V5.0" \
  --scope "<模块key>|修改|<一句话>|<C编号，可省>"
```

稿次不用自己数，脚本会数；但**念一遍给对方确认**。稿次写成 `V10.0` 会被三道门禁拦下，要写「第 10 稿」。

标注怎么加、锚点怎么写：`references/deliver-modes.md` 第三、四节。

---

## 第 1 步 · 圈定模块边界

你拿到的可能只是"人员字段配置"这四个字。要把它翻译成：

1. **菜单路径**：`人员管理 / 人员字段配置`（写清层级）
2. **路由**：`/personManage/fieldSetting/list`
3. **依赖参数**：要不要先选客户/项目/服务方？没有参数会不会白屏？
4. **本模块下的二级页与弹窗清单** —— 最容易漏，见下表

**四个地方找，少一个就会漏：**

| 从哪找 | 怎么找 |
|:--|:--|
| 路由表 | 前端 `umi.*.js` 里同前缀的路由，如 `fieldSetting/add`、`fieldSetting/details/:id` |
| 页面按钮 | 「新增 / 编辑 / 查看 / 引用模板」点了会开新页或弹窗 |
| 前端 chunk | 组件名带 `modal` / `dialog` / `drawer` |
| 用例库 | 用例里标了「弹窗」「xx 页面」的节点 |

产出一张表，逐个写：类型（主页面/二级页/弹窗/抽屉）、入口按钮、路由或组件名、这次覆不覆盖。
**没列出来的，PRD 一定缺块。**

---

## 第 2 步 · 五源采集

五个来源，每个都别跳。**「能访问」不等于「核对过」**——没真看到的，状态写 `部分` 或 `未核`，并在说明里写清为什么。

| 源 | 你要拿到什么 | 怎么拿 |
|:--|:--|:--|
| **浏览器渲染** | 页面真实长什么样、什么条件下出现什么 | headless Chrome 进去点一遍，每个页面态截一张 |
| **后端接口** | 枚举真值、字段全量结构、真实数据分布 | 拉 `enum/listEnums` 字典、列表接口、详情接口 |
| **前端代码** | 互斥条件、校验时机、文案、隐藏逻辑 | 读对应的 chunk |
| **后端代码** | 权限映射、状态置位、唯一性规则、跨模块副作用 | 读 Controller 与 ServiceImpl |
| **用例库** | 设计意图、边界 case、历史改名 | 搜关键词，细读核心的几条 |

命令：

```bash
# 字典真值（最硬的证据，别从界面猜枚举）
python <skill>/scripts/harvest.py enums --token-file <临时目录>/prd_token.json \
  --api <网关> --keys demobackstage:fieldTextType,demobackstage:fillParty

# 打单个接口
python <skill>/scripts/harvest.py probe --token-file <临时目录>/prd_token.json \
  --api <网关> --path /demobackstage/field/group/list --body '{"id":"<customerId>"}'

# 从前端 chunk 抽接口（chunk 会把整个 app 的接口表打包进来，必须加 --prefix）
python <skill>/scripts/harvest.py chunks --dir <chunk 目录> --match fieldSetting \
  --prefix /demobackstage/field

# 读后端代码（返回 base64，脚本会自动解码）
python <skill>/scripts/harvest.py be --repo yourgroup/yourproject/demo/demo-backstage \
  --path demo-backstage-app/src/main/java/com/example/geo/backstage/controller/filed/FieldController.java
```

**后端代码这条最容易跳过，但最值钱。** 字段权限落库成哪五个值、状态什么时候被置位、唯一性校验有没有例外——这些界面上永远看不出来，只能读代码。

**采集的时候要动手，不要只看：**

- **长页面一页一帧**，别拆成几个「页签帧」；超长用「同页 1/2」，`from` 写同一个页号
- **能提交就提交**：新增 / 编辑 / 删除 / 提交 / 审批 / 退回都真跑一遍，把提示文案**照抄**下来。校验原文、二次确认、失败路径、状态流转，只有真做才拿得到
- 先记原值、自己造的数据自己清理、一次只改一个变量
- 不碰：真实打款、真实发邮件、真实请款、删别人的数据、改权限。必须做才能验证的，**标「未实做 + 原因」**，不许写「应该会」
- **弹窗 / 抽屉 / 页签 / 二级页尽量都拿到**，页签要确认真的切过去了（抽出来一模一样就是没切）

细则：`references/interaction.md`。

---

## 第 3 步 · 写事实清单（闸门 1）

把五源的发现写成 `facts/<你的模块key>.facts.json`，生成清单，**拿给对方过**。

```bash
python <skill>/scripts/build_facts.py --data facts/<key>.facts.json --out out/<key>-事实清单.html
```

每条事实五个字段：

| 字段 | 写什么 | 举例 |
|:--|:--|:--|
| `old` | 原 PRD / 用例怎么说 | 「特殊命名只不支持 `*`」 |
| `new` | 实际是什么 | 「字段名与特殊命名共用黑名单，也禁 `#`」 |
| `src` | 哪几个源看到的 | `["be","ima"]` |
| `proof` | 具体到接口/文件/用例标题 | 「BAN_STR = ["*","#"] 统一遍历」 |
| `ask` | 要对方定什么（`ok` 类不用填） | 「以代码为准还是改代码？」 |

`cls` 五选一：`fix` 要改 / `add` 缺的 / `conflict` 冲突 / `risk` 风险 / `ask` 待确认。

**闸门规矩：对方回完之前，不许动手写 PRD。** 冲突没裁定的，只能进待确认，不许写进正文。

对方回复后，用命令记账（**别手改 JSON**，署名漏了就白签）：

```bash
python <skill>/scripts/gate.py facts --root <工作台> --module <key> \
  --by <对方姓名> --total 4 --answered 4 --note "F-01/F-02 进正文；F-03 进待确认"
```

`--total` 与 `--answered` 不等会被直接拒——还有没答的，不叫「已裁定」。

---

## 第 4 步 · 填模块数据（闸门 2 在这之后）

**动手写之前，先把骨架念给对方确认并留痕**（这就是闸门 2）：

```bash
python <skill>/scripts/gate.py scope --root <工作台> --module <key> --by <姓名> \
  --what "8 段 / 22 条规则 / 7 态 9 条迁移 / 不写供应商单据"
```

`--what` 写具体数字。只写「已确认」等于没确认。

填 `modules/<key>.json`。**这是唯一要你手工写的文件，格式已经给你搭好了。**

结构见 `assets/example_module.json`（一份完整样例），字段约束见 `assets/module.schema.json`。

这个文件装**四块**内容，出来的 HTML 顶栏能来回切：

| 块 | 写在哪个字段 | 缺了会怎样 |
|:--|:--|:--|
| ① 原型图 | `prototype.frames[]`（**跑脚本生成，别手写**） | 只有文字没有图，研发按自己理解画 |
| ② 叙事 | `sections[]` + `rules[]` + `transitions` | 看不出业务前提，只能照抄字段 |
| ③ AI 读 | `context` / `entities` / `layout` | AI 写代码时自己编，编完还很有信心 |
| ④ 核查 | `facts[]`（由台账同步，见下） | 结论看不出从哪来，讨论时各说各话 |

### 8 段各写什么

| 段 | 标题（**不能改**） | 写什么 | 不写什么 |
|:--|:--|:--|:--|
| 1 | 定位 | 这页解决什么问题、谁在什么场景进来 | 系统权限点（那是后台配的） |
| 2 | 业务背景与典型场景 | **为什么必须这样设计**：业务前提、不能改的约束 | 编场景。不知道就问，别推 |
| 3 | 主流程 | 编号步骤：触发 → 输入 → 系统反应 → 下一步 | 界面长什么样（那是第 4 段） |
| 4 | 字段字典与约束 | 每个可配项的**精确约束**：类型/必填/取值/长度/联动 | 「等等」「若干」——要列全 |
| 5 | 业务规则 | **由 `rules` 数组渲染，html 留空** | — |
| 6 | 状态与流转 | **由 `transitions` 渲染，html 留空** | 手画图 |
| 7 | 异常与边界 | 报错文案、校验在**哪一层**拦、并发、空态 | 笼统写「会报错」 |
| 8 | 待确认 | 挂编号，写明要定什么 | 替对方拍板 |

> 第 5、6 段必须留空 `html`，由数据渲染。手写会跟规则数据打架。

### 规则怎么写

一条规则**只讲一个命题**，不用代词，不写「等」。

```json
{
  "id": "R-OPS-FIELD-03",
  "type": "validation",
  "confidence": "互证",
  "src": ["be", "ima"],
  "statement": "字段名称（中英文）与特殊命名（中英文）四者之间，在当前客户维度不能互相重复",
  "evidence": "be: checkFieldExistsName() 按 custId 查重；ima: 新增字段 step3 提交校验段",
  "cases": [
    {"k": "negative", "g": "已有字段「姓名」", "w": "新建同名字段并提交", "t": "报「字段名称：姓名已存在」，不落库"},
    {"k": "positive", "g": "不同客户都有「姓名」", "w": "各自提交", "t": "都通过——校验是客户维度"},
    {"k": "edge", "g": "两个草稿字段同名", "w": "存草稿", "t": "允许；转正式时才校验"}
  ],
  "note": "可选。写这里没有证据但值得记的推断"
}
```

- `type`：`principle` / `constraint` / `validation` / `transition` / `calculation` / `permission` / `display` / `layout`
- `confidence`：`互证`（≥2 源一致）/ `双证`（2 源）/ `单源`（1 源，不许当结论用）/ `确立`（业务方当面裁定）
- `id`：`R-{系统}-{模块}-{序号}`，系统用 `OPS`/`ENT`/`EMP`，**一个模块内不许重号**
- **cases 至少 1 个，正例/反例/边界都要有**。只有正例的规则，测试写不出反向用例。

### 状态机怎么写

先写迁移表（`transitions.rows`），图由表自动生成。**不要反过来。**

```json
"transitions": {
  "states": ["草稿", "启用", "停用", "删除"],
  "rows": [
    {"id": "T1", "from": "草稿", "to": "启用", "trigger": "提交",
     "guard": "4 项校验通过", "label": "提交·校验过", "kind": "normal"}
  ],
  "confidence": "T2 已由后端代码证实，其余为推论",
  "note": "依据是 /field/save 无条件 setStatus(ENABLE)"
}
```

- `kind`：`normal` 普通 / `back` 可逆回边 / `danger` 不可逆 / `draft` 草稿专属
- `from` / `to` 必须都在 `states` 里，否则图上会画出孤立点
- `label` 是图上显示的字，**控制在 8 字以内**，太长会压线

### 原型怎么来（别手写）

**原型不许照着记忆画**——手写必漏列、漏字段，还没人看得出来。走三步：

```bash
# 0. 起一个带调试端口的浏览器（--headed 不能省，你要在里面亲手登录）
python <skill>/scripts/launch_chrome.py --headed
#    弹出的是全新配置目录的窗口，里面没有你的登录态 —— 在这个窗口里登录一次
#    测试环境，之后所有实拍都复用这份登录。脚本本身不碰你的密码。

# 1. 实拍：真实页面 → 快照（同时存截图，作为「这帧确实来自实拍」的旁证）
python <skill>/scripts/snapshot_page.py --base https://test1x.example.com \
    --url /personManage/fieldSetting/list --key <key> --page p1 --name 字段列表

# 2. 点开弹窗再抓一帧（--open 后面是按钮上的字）
python <skill>/scripts/snapshot_page.py --base https://test1x.example.com \
    --url /personManage/fieldSetting/list --key <key> --page p2 --name 管理分组 --open 管理分组

# 3. 快照 → 原型帧，直接写进模块数据
python <skill>/scripts/proto_from_snapshot.py --snapshot snapshot/<key>.json \
    --data modules/<key>.json --write
```

**抓不到多半是没登录**——`launch_chrome.py` 起的是全新配置目录，第一次必须手动登。
看到「什么都没抽到」就按这个顺序查：没登录 → 页面没加载完（慢网 / 要先选客户）→
这页确实没有表格和表单。

每步都会打印抽到了什么：

```
[1/1] p1  /personManage/fieldSetting/list
        → 6 张表 / 48 列、8 个按钮
```

生成出来的帧会自动带 `from: "<key>.json#p1"`。**这个字段不能删**——验收会拿它去查快照文件和页号对不对，
查不到就判「凭印象画」。手改 `html` 可以，但 `from` 要留着。

脚本抓的是**结构**，不是像素：标题、描述、面包屑、页签、顶栏与侧栏菜单（含层级）、
表单分组与字段（类型/必填/选项/占位符）、表格（列/首几行/状态标签）、按钮、分页。

如果生成的帧要微调，仍**只准用 `px-` 组件 class，不准写 `style=`**——契约会拒。
十个人十种样式，包成全量后必散。组件清单和配方见 **`prototype-kit.md`**。

```json
"prototype": {
  "viewport": "1440x900",
  "frames": [
    {"id": "P1", "name": "字段列表", "state": "默认态", "route": "/personManage/fieldSetting",
     "from": "<key>.json#p1",
     "note": "哪些是示例数据、哪里被裁掉了", "html": "<div class=\"px\">…</div>"}
  ]
}
```

- **P1 固定是主页面**，页签按 P1、P2… 排
- **每个已覆盖的弹窗 / 二级页各占一帧**。清单里 `covered=true` 的都要画，**少画一帧验收直接拦**（差几帧会报出来）
- **一帧一个状态**：默认态 / 空态 / 校验失败分开画，不要在一张图里塞两种
- **`note` 必须写**：看图的人不知道哪些是示例数据就会问

> 按钮点了没反应？脚本已经用真鼠标事件（`Input.dispatchMouseEvent`）而不是 `el.click()`，
> 大部分 React 组件都认。个别按钮确实点不开（依赖前置选择、或被别的层挡住），
> 就换一个按钮，或者直接抓它跳转后的路由。

### 事实清单怎么进 PRD

事实清单**只写一份**，在 `facts/<key>.facts.json`（第 3 步写的那份）。

构建时加 `--facts` 就会自动同步进模块数据并回写，你不用手抄：

```bash
python <skill>/scripts/build_module_prd.py --data modules/<key>.json \
  --facts facts/<key>.facts.json --out out/<key>.html --strict
```

规则想标依据，在规则上加 `"facts": ["F-01","F-07"]`，叙事卡片上就会出「依据 F-01」的可点链接，
点了跳到核查那一块。事实那边写 `"rules": ["R-OPS-FIELD-10"]` 就能反跳回来。
**两边编号必须真实存在**，契约会查。

### 六个源的状态

`已核` / `部分` / `未核` / `不可达`。`detail` 要写**核了什么、拿到什么数字**——只写「已核」不算。
交付要求至少 4 个源 `已核`。

---

## 第 5 步 · 构建 + 实拍

```bash
# 构建（--strict 会拦住不合规的数据；--facts 从台账同步事实清单）
python <skill>/scripts/build_module_prd.py --data modules/<key>.json \
  --facts facts/<key>.facts.json --out out/<key>.html --strict

# 实拍核对：四个视图各截一张 + 结构诊断
python <skill>/scripts/shot_verify.py --html out/<key>.html
```

产物打开后顶栏有五个按钮，**每个都要看过一遍**：

| 视图 | 看什么 |
|:--|:--|
| 原型+叙事 | 默认视图。左边图右边字，是给别人讲的时候用的 |
| 原型 | 单看大图。缩放到 100% 时元素不重叠、文字不溢出 |
| 叙事 | 单看正文。8 段齐、规则卡带编号和 case |
| AI 读 | 条目是否一行一条、编号和叙事对得上 |
| 核查 | 事实条数、P0 数、每条的原说法/实际/要你定是否写清 |

**结构校验只能证明语法没错，证不出页面对了。** 必须看截图：
文字有没有重叠、标签有没有压在线上、表格有没有挤成好几行、原型有没有错位。

第一次构建出来的可能是骨架——没关系，先看看成品长什么样，再往里填。

---

## 第 6 步 · 交付（两层门禁，缺一层不算交）

```bash
python <skill>/scripts/gate.py status --root <工作台> --module <key>   # 先看四道门
python <skill>/scripts/check_delivery.py --root <工作台> --module <key> --strict
```

**交付前封一次板**，你自己签就行（产品经理本人），不用找第二个人：

```bash
# 整份封：一次盖住全部模块（推荐，最省事）
python <skill>/scripts/gate.py doc --root <工作台> --by <你的名字> --note "整份看过，可以发"

# 只封某一个模块（改了几个封几个，更精确）
python <skill>/scripts/gate.py sign --root <工作台> --module <key> \
  --by <你的名字> --note "这一版可以往下走"
```

**封板记的是内容，不是名字。** 封完之后再改这个模块，签会自动失效——`status` 和验收都会提示，重封一次即可，不用手动 `revoke`。所以顺序是：**先改完，最后封**。

**全绿才算交了。** 它会查：

- 闸门 1 过没过（facts 里有没有裁定时间）
- 闸门 2 过没过（待确认是不是全被回答了）
- 数据合不合规（契约 / TODO 残留 / 示例没替换 / 引擎版本）
- 四块齐不齐（原型帧有没有、弹窗都画了吗 / 8 段全不全 / 事实清单有没有 /
  事实清单是否和台账一致 / 规则有没有挂依据 / P0 写没写要定什么）
- **原型有没有实拍依据**（帧上的 `from` 指的快照文件在不在、页号对不对得上）
- 产物对不对（HTML 比 json 新吗 / 页内数据和 json 一模一样吗 / 有外链吗）
- 有没有明文密码
- **（做迭代才有）** 稿次与 run.json 一致 / 范围里的模块真标了改动 / 编号在原型和叙事两边同号 / 锚点目标存在
- **反查（第二层）** 每条规则在产物里找得到 / 每条 P0 事实都被引用 / 已答的答案不是空话 / 标了 covered 的弹窗在帧里找得到
- **封板** 有人签过，且签的是当前内容（改了内容没重封会提示）

交这四样：

```
facts/<key>.facts.json     事实台账（闸门 1 的留痕）
snapshot/<key>.json        实拍快照 + shots/ 下的截图（原型图的依据）
modules/<key>.json         模块数据（唯一要手工写的）
out/<key>.html             渲染产物
```

**`snapshot/` 必须一起交。** 少了它，你交的原型图就只是一张画 ——
合并进全量后，谁也没法核对它跟真实页面对不对得上。

---

## 三条红线

**1. 不改模板。**
HTML 长什么样由引擎决定。你觉得哪里不好看，说一声，别自己改——一改就合并不了。

**1.5 原型不许凭印象画，详情页尤其。**
详情页的块顺序、两栏宽度、单选选中态都靠坐标抓，手画必错。
先 `snapshot_page.py` 实拍，再 `proto_from_snapshot.py` 生成。
生成得不好看可以手改 `html`，但 `from` 必须留着，否则验收判你「凭印象画」。

**2. 不手改 `out/` 里的 HTML。**
它是产物，重新构建就覆盖。要改内容改 json 再构建。验收会对比页内数据和 json，改过会报错。

**3. 拿不准就写进待确认，不许编。**
编一个"看起来合理"的答案，比留白危害大得多——后面所有人都拿它当事实。
待确认不是缺陷，是 PRD 的组成部分。

---

## 常见错误

| 现象 | 原因 | 怎么修 |
|:--|:--|:--|
| 构建报「第 5 段 html 必须留空」 | 手写了规则 HTML | 删掉，让 `rules` 渲染 |
| 构建报「互证但只有 1 个来源」 | 标高了 | 降到 `单源`，或补一个源 |
| 图上有孤立节点 | `from`/`to` 不在 `states` 里 | 补齐 `states` |
| 图上标签叠在一起 | `label` 太长 | 压到 8 字以内 |
| 验收报「产物不一致」 | 改完 json 没重新构建 | 重跑 build |
| 验收报「TODO 残留」 | 骨架没填完 | 搜 `__TODO__` 逐个填 |
| 接口 `field/list` 报 must not be null | 缺 `customerId` | 先从客户列表拿 id |
| 新增页「所属分组」显示一串 ID | 数据还没返回 | 等 2 秒自动好，不是 bug |
| chunk 抽出几百个接口 | chunk 打包了整个 app 的接口表 | 加 `--prefix` 过滤 |
| 改了说法，被问「你这里怎么还写着旧的」 | 口径散在六个地方，只改了正文 | `scan_wording.py --path modules/<key>.json --term "旧=新"` 扫干净（W6） |
| 缺字段的提示画成红色，客户问「是不是付不出去」 | 能提交的用红 = 颜色比约束强 | 改成琥珀 `.px-alert.warn` / `.px-fctrl.warnf`；红只给阻断 |

---

## 卡住了

- 页面进不去 / 白屏 → 多半缺上级参数（客户/项目/服务方 id）
- 账号权限不够 → **找模块负责人开权限**，不要借别人的账号
- 用例库 / 代码仓库 连不上 → 先检查连接，别用手工猜代替
- 同一件事三个源说法不一样 → 这是**最有价值的发现**，不是麻烦。写进事实清单的 `conflict` 类，让对方裁定
