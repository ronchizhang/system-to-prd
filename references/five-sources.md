# 五源核查

对应模式 A 的 A2-A3。目标不是「把页面看一遍」，而是**让每条写进 PRD 的结论都能追到来源，且知道能信到什么程度**。

---

## 一、为什么必须五个

| 只做这个 | 会漏什么 | 真实例子 |
|:--|:--|:--|
| 只看浏览器 | 界面看不见的分支、落库成什么值 | 三档权限各自写入 5 个底层字段，界面只显示 1 个 tag |
| 只看前端代码 | 后端是否真的接受、有没有二次校验 | 前端限制 250 字，后端不校验；前端置灰，后端不管 |
| 只看后端代码 | 用户实际看到什么、条件显示长什么样 | 代码里 `view` 分支不改 `participantHide`，界面上是「报名者端是否可见」两个单选 |
| 只看用例 | 用例经常是旧版 | 用例写 4 个服务类型，线上是 5 个；用例说页面叫 A，线上叫 B |
| 只问业务方 | 记不清细节，且说不出落库口径 | 「字段类型就那几种」——实际有 8 个 key |

**五个都做，才有资格写「实测」。** 少一个必须在交付说明里写清少哪个、为什么。

---

## 二、五源各自的通路

### 源 1 · 浏览器渲染

**启动方式（沙箱环境的关键，照抄）：**

```bash
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
"$CHROME" --headless=new --no-sandbox --disable-setuid-sandbox \
  --disable-gpu --disable-software-rasterizer --in-process-gpu \
  --remote-debugging-port=9222 --user-data-dir=<临时目录>/cdp-hl \
  --no-first-run --window-size=1680,1400 about:blank
```

- `--no-sandbox` 绕开 seatbelt 拦 Chrome 自身的 sandbox 初始化
- `--in-process-gpu` 绕开 GPU 进程崩溃（`GPU process isn't usable. Goodbye.`）
- **必须用后台任务托管进程**，否则命令一结束 Chrome 就被回收
- `CVDisplayLink` 报错是无头环境的正常噪音，不影响

**免登录：把 token 塞进 localStorage**

```python
p.evaluate("localStorage.setItem('geoAdminToken', %s)" % json.dumps(tok))
p.send("Page.navigate", {"url": target})
```

token 的 key 从前端 chunk 里搜 `setItem("xxxToken"` 得到，别猜。

**抓真实请求（登录后页面发出的接口才是真参数）：**

注入 hook 再 reload：

```javascript
window.__reqs = [];
var of = window.fetch;
window.fetch = function(u, o){
  window.__reqs.push({m:(o&&o.method)||"GET", u:String(u), b:o&&o.body?String(o.body).slice(0,600):""});
  return of.apply(this, arguments);
};
var oo = XMLHttpRequest.prototype.open, os = XMLHttpRequest.prototype.send;
XMLHttpRequest.prototype.open = function(m,u){ this.__m=m; this.__u=u; return oo.apply(this,arguments); };
XMLHttpRequest.prototype.send = function(b){
  window.__reqs.push({m:this.__m, u:String(this.__u), b:b?String(b).slice(0,600):""});
  return os.apply(this, arguments);
};
```

**这一步的价值**：能直接看出「哪个接口真正被调、带了什么参数」。实测中 `field/list` 一直报 `must not be null`，hook 之后才发现**列表页根本不调它**，数据在 `group/list` 里——靠猜参数永远猜不到。

**必须实拍的页面态**（少一个就会漏规则）：

- 列表页默认态
- 新增/编辑第 1 步
- 第 2 步（很多规则藏在这里，不在第 1 步）
- 每个「互斥展开」的两个分支各一张（选 A 展开什么、选 B 展开什么）
- 弹窗打开态
- 空态与报错态

**取渲染事实**，别只截图：

```javascript
JSON.stringify({
  rules: document.querySelectorAll('.rule').length,
  pFont: getComputedStyle(document.querySelector('p')).fontSize,
  th: [].map.call(document.querySelectorAll('th'), e => e.innerText.trim())
})
```

---

### 源 2 · 后端接口

```python
req = urllib.request.Request(GATEWAY + path,
    data=json.dumps(body).encode(),
    headers={"Content-Type":"application/json", "authToken": tok, "lang":"zh"})
```

**三个必做动作：**

**(a) 拉枚举字典——这是最快拿到真值的方式**

前端调 `listEnums` 时会带一串 key，直接从 hook 记录里抄：

```json
["demo:fieldStatus","demo:defineFieldType","demo:fieldTextType",
 "demo:permissionConfigType","demo:fillParty", ...]
```

返回形如 `{"text":"文本","number":"数值",...}`。**字典有几个 key 就是几种，不要数界面上的选项。**

**(b) 拉全量结构，不要只拿一条**

列表接口常返回简化对象（10 个属性），详情接口才是全量（24 个属性）。差别里往往藏着整个「其他设置」模块的字段。

**(c) 统计真实数据分布**

```python
Counter(f["fieldType"] for f in all_fields)    # 8 种分布
Counter(f["custPermissionConfig"] for f in all_fields)  # 三档各多少
```

分布能验证「这个取值组合是否真的存在」。比如某档在 110 条里出现 0 次，说明它可能只对特定类型开放——这本身就是一条事实。

**注意必填参数**：报 `must not be null` 时，先回前端代码找调用点看真实 payload，不要逐个试参数名。

---

### 源 3 · 前端代码

**拿到 chunk：**

```python
# umi 的产物：umi.js 里有「chunk 名表 + hash 表」，拼成 {name}.{hash}.async.js
# 下载到 <chunk 目录>/，按业务名筛需要的那几个
```

**三个必查点：**

| 查什么 | 特征 | 为什么重要 |
|:--|:--|:--|
| 互斥/条件显示 | `a === "x" ? {label:"甲"} : {label:"乙"}` | 这是 UI 上「选 A 出现甲、选 B 出现乙」的唯一真源 |
| 校验规则 | `BAN_STR`、`maxLength`、正则 | 界面只显示报错，不显示规则全貌 |
| 接口常量表 | `{fieldList:"/demo/form/list", ...}` | 一次拿到本模块全部接口名，比逐个抓省事 |

**另外必看**：

- 中文文案字面量（`grep '[\u4e00-\u9fa5]'`）——能翻出界面没展示的提示语、确认弹窗文案
- `localStorage` 的 key 名（免登录要用）
- `window.open` / `navigate` 的路径拼接（二级页入口）

---

### 源 4 · 后端代码

**这是最容易跳过、但价值最高的一源。** 三类问题只靠界面永远推不出来。

**通路（代码仓库 CLI）：**

```bash
export PATH="$HOME/.workbuddy/binaries/node/cli-connector-packages/bin:$PATH"
cnb status                                        # 确认已登录

# 仓库完整路径不要猜，从组织仓库列表的 site 字段取
cnb repositories get-group-sub-repos --slug <组织> --page-size 100 -v | grep '"site"'
#   → https://cnb.cool/<组织>/<子组织>/<分组>/<仓库>
#   仓库名 = <组织>/<子组织>/<分组>/<仓库>

cnb git get-content --repo <仓库完整路径> --file-path <文件路径> -v
```

**四个坑（都踩过）：**

1. `data.content` 是 **base64**，必须解码
2. 根目录用 `get-content-without-path`；列子目录用 `get-content --file-path <目录>`
3. **目录名可能拼错**：`controller/filed/`（实际是 filed，不是 field）
4. 单文件可能几千行，先抽方法签名列表再挑关键方法读

**必读的四个位置：**

| 位置 | 拿到什么 |
|:--|:--|
| `*Controller.java` | 全部接口 + **权限注解**（`@XxxAuthPermission(permission = true)` 与裸注解的差别就是权限缺口） |
| `*ServiceImpl.java` 的 `save*/update*` | 状态怎么置位、有没有无条件覆盖 |
| 权限/配置构建方法 | 「界面三档 → 落库五个字段」的真值表 |
| `check*Exists*` / `validate*` | 唯一性、黑名单、系统保留值 |

**实测收益例子：**

- `/save` 与 `/edit` 共用一个方法，第一行 `req.setStatus(ENABLE)` → 编辑已停用字段会自动启用（真缺陷）
- 唯一性校验除了「客户内不重名」，还查「系统占用名」——用例完全没写
- 5 个接口只校验登录、不校验权限点，其中「存草稿」能落库

---

### 源 5 · 用例库

```python
mcp__ima-mcp__search_knowledge(knowledge_base_id="<kb_id>", query="<模块名> 用例")
mcp__ima-mcp__fetch_media_content(media_id="<media_id>")   # 返回 markdown 化的 xmind
```

**怎么读：**

- 先按标题筛（`字段列表` / `新增字段` / `编辑字段` / 各种专题），**别读全库**
- 一次读 2-3 条，xmind 展开后动辄几百行
- 重点看：字段级规则、必填判断、条件显示、报错文案、联动

**用例的三个典型问题：**

| 问题 | 例子 | 处理 |
|:--|:--|:--|
| 名称过期 | 用例叫「报名信息设置」，线上叫「报名字段配置」 | 以线上为准，台账记差异 |
| 枚举过期 | 用例 4 个服务类型，线上 5 个 | 以字典为准 |
| 规则与代码不符 | 用例说「特殊命名只禁 `*`」，代码禁 `*` 和 `#` | 记 `conflict`，让用户裁定 |

**用例不可替代的价值**：它记录了**设计意图**和**边界条件**，这些代码里没有注释、界面上也点不出来。比如「选指定国家但没选国家时，该选项置灰」这种细节。

---

### 源 6（附加）· 业务确认

严格说这不是「核查」，是**补充前提**。但它决定了整页文档的骨架，所以必须有。

**必须问的三个问题：**

1. **这页最初为了解决什么问题？** 谁提的、当时卡在哪
2. **收什么数据是由什么决定的？** （实测中答案是「所属地区 × 票种」，这一个答案解释了整个数据模型为什么按客户独立）
3. **有没有超出设计初衷的用法？** 这条最关键——如果有，说明「能力边界由配置决定，不由场景清单决定」，文档里必须显式声明

**写进文档的方式**：场景卡 + 一条显式声明「以下是已知用法，**不构成能力边界**」。否则读者会把它当成限制。

---

## 三、事实台账

### 字段定义

| 字段 | 必填 | 说明 |
|:--|:--|:--|
| `id` | ✓ | `F-01` 递增；需要用户回答的用 `Q-01` 单独编号，便于他按号回 |
| `cls` | ✓ | `fix` 需改 / `add` 缺失 / `conflict` 冲突 / `risk` 风险 / `ask` 待确认 / `ok` 一致 |
| `sev` | ✓ | `P0` 阻塞写文档 / `P1` 影响准确性 / `P2` 补充即可 |
| `area` | ✓ | 所属话题（字段类型/权限/列表…），会显示成卡片上的小标签 |
| `title` | ✓ | 一句话说清「哪里不对」 |
| `old` | | 原说法（引用原文），没有就写 `——` |
| `new` | ✓ | 实际情况；多行用 `\n`，会自动保留换行 |
| `src` | ✓ | **只写真看到这条的来源**，用 `ui/api/fe/be/ima/biz` |
| `proof` | ✓ | 可复核的指针：接口路径 / `文件:方法名` / 用例标题 |
| `note` | | 我的判断：为什么会这样、有什么影响 |
| `ask` | | 要用户定的问题，一句，可带选项 |

### 证据强度

不能只记「来自哪」，要能派生出强度：

| 强度 | 判据 | 处理 |
|:--|:--|:--|
| **互证** | ≥3 源一致 | 直接进正文，标「实测」 |
| **双证** | 2 源一致（如代码 + 字典） | 进正文，标具体来源 |
| **单源** | 只有 1 源 | 进正文但标该来源；若来源是用例，降为「用例口径」 |
| **孤证** | 只有 1 源且与另一源矛盾 | **不进正文**，只进待确认 |

`src` 里写几个源，强度就自动确定了。**别在 `src` 里塞没核过的源**——这是最容易犯的错，等于给自己发假证。

### 冲突处理

冲突不进正文，只进待确认，并且必须写成结构化的三方对照：

```
A 说法：<原文>（出处）
B 说法：<原文>（出处）
我的判断：<倾向哪个 + 理由>
要你定：<一个具体问题，最好带选项>
```

**裁定之后**：在台账里把 `cls` 改成 `fix` 或 `ok`，`new` 里写上最终结论，备注「已确认，YYYY-MM-DD 由业务方裁定」。这是后续写 PRD 的唯一依据。

---

## 四、采集顺序建议

```
登录 → 定位模块边界（A1 那张表）
  ↓
浏览器：先截图把界面看一遍，建立整体印象
  ↓
接口：拉字典 + 拉全量结构 + 统计分布        ← 半小时内能拿到 80% 的硬事实
  ↓
前端码：读互斥条件 + 校验 + 接口表
  ↓
后端码：读 Controller 权限注解 + Service 关键方法
  ↓
用例：按标题挑 5 条读
  ↓
业务确认：三个问题
  ↓
台账 → 闸门 1
```

**为什么接口排在前端码前面**：字典和全量结构能立刻校准你对「有几种类型、有哪些字段」的认知。先读代码容易被实现细节带偏，先看数据能建立正确框架。

**浏览器排最前**：先建立「用户看到什么」的印象，后面读代码才知道每段逻辑对应界面哪一块。

---

## 附：读代码时的两条纪律

**① 注释可能是旧的，以实现为准。**

真实案例：`RefundSubmitReqDto.participants` 的注释写「结算报名者的 id（**自营**）」，
看起来合作方用款申请不用传报名者。实际实现是：

```java
if (haveEmpTypes.contains(requestOrder.getType()) || corpTicketOrder) {
    AssertUtil.isTrue(!CollectionUtils.isEmpty(req.getParticipants()), "结算报名者不能为空");
```

`corpTicketOrder` 单独成立 —— 合作方用款申请**同样必传**。这条还是「支持单人结算」的实现依据。

**判断方法**：看到 `@NotNull` / 断言 / 白名单，就去找**真正执行校验的那段代码**，不要停在字段注释。

**② 前后端同一份规则，要两边都读。**

真实案例：付款模板白名单，前端是 7 个精确账户名（含 通道B），后端是
`["空中通道C","珊瑚跨境"] + containsIgnoreCase`，而实际账户名是「…-通道C」，**后端永远匹配不上**。

这类「系统内部自己不一致」必须记成 `cls=conflict` 的事实，并写清两边各是什么——
只写一边，看起来完全正常。
