# Changelog

Semantic versioning is not used here; versions track **structural** changes to the deliverable, and each entry states what was wrong rather than what was added. Full narrative history, with the reasoning and the real cases behind each change, lives at the end of [`SKILL.md`](./SKILL.md#七版本记录).

> **关于 6.2 的一个说明。** 公开仓库的 6.2 版曾带一项 `changes` 台账，把每处改动渲染成
> 「改前 → 改后」对照卡。主线 6.3–6.7 没有采纳这个做法：迭代仍然只靠
> `data-chg` + `data-draft` 标注，改动总览由渲染器从原型反推。
>
> 两条路各有代价。台账能把「原来是什么」说清楚，代价是同一件事要写两遍，写漏了就会
> 静默少一张卡。反推省掉这份重复，代价是改前的样子不再保留。
>
> **6.7 起以主线为准。** 6.2 那份示例用的是「活动报名」域，属于换域换到一半：
> 词换了一半、行业轮廓还在，读起来两边不靠。6.8 重新做了一遍，见下条。

## v6.8 — 示例整体换域，判据从「敏感不敏感」改成「还有没有残留」

原来只清标识（公司名、真实单据、内部代号、厂商），行业轮廓留着。理由写在当时：看出这是个什么行业的后台，不等于知道是哪一家。

这个理由本身没错，但它撑不起一份公开示例。**示例是门面**，读者第一眼看到的是它，不是那句免责声明。所以这一版把整个示例搬到另一个行业：在线教育机构后台的「学员档案字段」。三端变成平台后台 / 机构端 / 学员端，字段集从「地区 × 课程类型」算出来——结构和原来一一对得上，业务一条都不重叠。

换域真正的难点不是词，是**判据**。上一版试过换域，失败在半途：字面换了，同一句里的配套名词还在（上半句把产品名换成了「班次」，下半句还在讲支付网络），读起来像两个人写的。

这一版换了判据：

- 旧判据：「这个词敏不敏感」——永远有争议，永远有人觉得过度或不够
- 新判据：「它属于哪个域」——可以机械复核。示例统一成教育域之后，旧域的词应当**一个都没有**

后者能直接做成门禁。`p1.txt` 从「行业词黑名单」改成「旧域词表」，命中的解释只有一个：替换表漏了。零争议，也零误报。

代价是这份表跟示例绑死——哪天示例再换域，它要跟着重写。这个代价是应该付的。

顺带修了两个东西：

1. **一个真公司名漏了。** 上一轮 17 处泄露复盘里没有它，因为它不是自家的名字，是一份「不要查哪些户」的排除名单里带的。这次换域才翻出来。
2. **G5 的粘连告警会误报。** 它的判据是「中文替换目标词后面紧跟大写英文」，用来抓「英文单词被切成两半、后半截粘在中文后面」这种残留。换域后「通道 + 字母编号」这类**虚构通道代号**也符合这个形态，一次报三条。没有关掉告警，而是给 `allow.txt` 加了这条路径——豁免必须写理由，评审时能看到，比默默放宽判据好。

README 也一起重写了。旧版从「AI 写不出真 PRD」讲起，讲的是为什么存在；新版从**你现在的处境**讲起，讲的是三个能力在什么场景下用、怎么串成一条循环。

## v6.7 — 复杂逻辑允许画出来，文案按条核对

原来只有一条「原型只画界面」，判据是「这句话会不会出现在系统截图上」。遇到复杂逻辑只能堆文字，而实际文档里早就有 PNG 原理图、SVG 流程、界面化说明页三种生成图在承担这件事。

`prototype.frames[]` 增加可选字段 `kind`（`ui` / `flow` / `diagram` / `explain`，缺省 `ui`）。三处检查跟着分家：「图上没有说明条」只扫 ui 帧；「长解释没混进界面」对生成图放宽；「原型有实拍快照」只统计 ui 帧，并列出具体帧号。

同时补了一条文案约束：说明文字一句一件事，能拆就拆。废话词早就不多了，累人的是信息全挤一行——单句超 50 字、四个顿号挤一句、有编号却挤在一段里。

## v6.6 — 签字改成「一个人封板」

签字不需要两个人确认。它的性质是**封板**——「这一版我认了，可以往研发走」——签的人就是产品经理本人。「业务 + 技术双签」取消。

理由不是省事，是那套在真实团队里没人执行：硬要求双签的结果不是更严谨，是每轮检查都挂红叉，红叉挂久了就不再传递信息，门等于不存在。

老数据照旧能读：`{"business": {...}, "tech": {...}}` 取先签的那个人，不要求重封。

## v6.5 — 签字认内容，不认名字

原来两处签字都只判断「有没有签名」：模块级双签从不比对稿次，推了新稿也不失效；文档级确认在没跑过 `plan_iteration` 时两边都是空，`None == None` 永远相等。

后果一样：**签完字之后改内容，签字不会失效。** 签字是这套流程里唯一的「人确认过」凭据，它不失效，等于签一次管到底。

改成签字时记一份内容指纹（JSON 规范化后取 sha256，忽略缩进与键序），验收时逐份比对：内容变了就失效，不管稿次动没动。格式变化不误伤，不逼人重签。

三处判断都补了，不只是验收：`check_delivery`、`merge_modules` 的合并门禁、`gate.py status`。否则签字失效了照样能合，或者状态屏显示一个已经作废的 ✓。

## v6.4 — 来源身份证：把「我基于哪一版」写下来

v6.3 的同源校验靠指纹：拿 B 里没改过的模块和全量比，一致就推断同源。这是间接证据，两个盲区——`scope` 覆盖全部模块时没有指纹可用，只能报「未验证」；全量只在 `scope` 内改过时，指纹看不出。

改成直接证据：`merge_modules.py` 每出一次全量，在工作台根目录写 `origin.json`，记下这一版由哪几个模块、各自什么 sha256 构成。迭代副本是整目录复制的，这文件跟着走。合回前比对它和当前全量，就知道「出证之后 A 有没有动过」。

关键设计：身份证查全部模块，不跳过 `scope`。它回答的是「A 变没变」，与本次要改哪几个模块无关。

## v6.3 — 合并先验来源，再验范围

合并的模型澄清了：**全量是只读基线，迭代是补丁**，只有两个版本。A 就是分叉点本身，所以不存在「谁改过」的判定，也不需要三方合并。

需要守的只有一条：**B 确实是从当前这版 A 复制出来的**。

原来只查「范围外动没动」，拦不住另一种事故——拿一份从旧版本复制的副本合回，会静默用旧内容覆盖新内容。范围校验只问「动了哪些模块」，不问「基于哪一版」。

`check_untouched.py` 加 `--same-origin`：`--base` 给迭代副本、`--work` 给当前全量，用 B 里没改过的模块当指纹验证同源。三档结论：同源 / 不同源（停）/ 全量新增（不阻塞）。

## v6.2 — every change now shows what it replaced

原型里的粉色块只能说明「这里改了」，答不了「原来是什么」——而评审第一个问的就是这句。
所以给改动加了 `changes` 台账（`id / title / where / before / after / why`），渲染成右侧的
**改前 → 改后** 对照卡：点原型里那块粉，卡片亮起来；点卡片，原型滚回去。

数据是新增的，不是从 HTML 反推的——原型只留改后的样子，改前那一版已经不在 DOM 里了。
`schema.py` 同时加了门禁：原型标了而台账没有的编号，直接报错。漏一条不会白屏，
只会少一张卡，读者以为这处没改过，这种静默缺失比报错难查得多。

顺带修掉一个真实隐患：`FieldController → FormFieldController` 这类替换，
目标串里含源串（`FormFieldController` 里有 `FieldController`），第二遍会套成
`FormFormFormFieldController`。现在类名规则带负向断言，并加了一条自愈正则把已套娃的压回去。

## v6.1 — four lanes, filled in

Defined "four lanes, one reader each" in v6.0 but never said how to fill them. This version adds the test-case lane (three-step cleanup from an xmind tree, every case pinned to a rule), the code lane (plain-language Q&A on top, front-end/back-end mapping below), and entity relations (5–7 top-level entities, each with "who creates it").

Also fixes anchor jumps landing at the top of the document, and adds URL deep links (`?m=cases`, `?m=code`, `?m=facts`, `?chg=C5`).

## v6.0 — one document, three audiences

Business owners, QA and developers were reading the same paragraph, so all three read it badly. Split into four lanes; technical detail **moves** (to the code lane or Appendix B) rather than being deleted, enforced by a gate.

## v5.3 — the section skeleton

Eight sections existed, but what goes **inside** each was unspecified, so the same document had eight sections with eight different shapes. Fixed slot lists per section, plus a gate that fails when section 1 declares "N changes" and section 4 only contains N-2 blocks.

## v5.0 — one signature instead of twelve

Module-level dual signatures meant 12 signatures for a 6-module project. Small teams do not work that way; the result was a permanent red X that stopped carrying information. Default is now a single document-level sign-off, bound to the draft number so it expires on edit.

## v4.4 — same-draft revisions

Added `Draft N (revision M)` for changes that only touch wording and evidence. One criterion: **did a business conclusion change?** If not, it is a revision — pushing a new draft makes readers think requirements changed and go diff-hunting for nothing.

## v4.2 — gates on gates

A single gate proves itself with its own data. Split into a process gate (human, signed) and a delivery gate (machine, reverse-checking the artifact). The second layer must approach from a different direction, otherwise it is duplicated labour.

## v4.0 — two delivery modes

Separated "record how it works today" from "design the next version". Mixing them produces a document where nobody can tell which sentence is current behaviour and which is a proposal.

Earlier iterations (v2.2–v3.x) are recorded in `SKILL.md`; most of them are CSS and capture bugs found by pointing the tool at real pages, each one now either a template fix or a gate.
