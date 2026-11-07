# CSS 与布局坑位清单

以下每一条都**真实发生过**，症状都很像"设计错了"，实际全是样式继承或容器约束的锅。
写完样式先对着这张表自查一遍，能省掉大半返工。

---

## 1. 文字突然变成竖排，一个字一行

**症状**：卡片里的内容区，标签和值上下叠、且每行只有一两个字宽，看起来像被挤成竖条。

**根因**：容器用了 `display:flex`，子项没有 `flex:1` 也没有定宽，
flex 会把子项的宽度压到 `min-content`。中文的 `min-content` 就是**一个字的宽度**。

**典型触发**：把详情页的两栏布局类（如 `.dtl{display:flex}`）误用到卡片正文上。

**修法**：
```css
/* 卡片正文用独立的块级类，不要复用带 flex 的布局类 */
.bd{display:block;}
.bd > * + *{margin-top:12px;}
```
实在需要 flex，就给子项 `flex:1;min-width:0`。

---

## 2. 时间轴/列表被顶栏样式污染

**症状**：某个局部区域的字体、颜色、间距突然和顶部导航一样，边框莫名其妙。

**根因**：**类名撞车**。局部组件用了 `.tb`、`.th`、`.th`、`.alert` 这种两字母短类名，
而全局顶栏/标题也定义了同名类，后写的覆盖前面。

**典型触发**：时间轴里 `.ti .th`（时间轴头部）、`.ti .tb`（时间轴正文）撞上顶栏 `.tb`。

**修法**：局部组件统一加前缀，`.tl .ti .tlh` / `.tl .ti .tlb`。
**排查手法**：怀疑撞车时，用 `getComputedStyle` 打出来看 `font-size`、`color` 是不是继承来的异常值。

---

## 3. 长文本挤成一行，超出容器不换行

**症状**：一段说明文字全部堆在一行里溢出，或者被裁切。

**根因**：容器是 `display:flex`，文本节点成了 flex item，默认不换行（`flex-shrink` 让它在一条线上缩）。

**典型触发**：`.alert{display:flex;align-items:center}` 这种"图标 + 文字"的提示条，
被拿去做单段长文本提示。

**修法**：单段提示不要用 flex 容器，直接写内联块：
```html
<div style="background:#FFFAF2;border:1px solid #F5E3C8;border-radius:8px;padding:12px 14px">
  长文本……
</div>
```

---

## 4. 左侧页面区被挤成一条缝（最严重）

**症状**：主内容区突然只剩 100~200px 宽，右侧文档栏占了整个屏幕。

**根因**：文档栏容器缺 `min-width:0`。flex 子项的默认 `min-width` 是 `auto`，
里面只要有一张宽表格（`white-space:nowrap` 的表头），就会把容器顶宽，反过来挤压兄弟元素。

**诊断**：量一下宽度，正常应该接近视口宽度：
```js
document.querySelector('.main').getBoundingClientRect().width  // 掉到 196 就是中招了
```

**修法**：
```css
.doc{width:524px;flex:0 0 auto;min-width:0;overflow-y:auto;}
/* 表格自己也别硬撑 */
.doc table{width:100%;table-layout:fixed;}
.doc th,.doc td{word-break:break-word;}
```

---

## 5. 内容整体飘到右边

**症状**：一个本该铺满的容器，内容全部靠右贴边，左边一片空。

**根因**：拿带 `justify-content:flex-end` 的类（如底部按钮条 `.fm`）当栅格容器用了。

**修法**：栅格用独立的 grid 类，不要复用按钮条：
```html
<div style="display:grid;grid-template-columns:repeat(2,1fr);gap:8px 18px">
```

---

## 6. 金额条/指标条换行成竖排

**症状**：本来横排三个数字的条，变成上下三行，或者每项被压得很窄。

**根因**：flex 容器里的子项没有定宽，`flex:0 0 auto` 缺失导致被压；或者忘了 `display:flex`。

**修法**：
```css
.amtb{display:flex;align-items:center;gap:0;}
.amtb .ai{flex:0 0 auto;min-width:118px;}   /* 关键：定最小宽度 */
```

---

## 7. 勾选框/状态图标不显示

**症状**：HTML 里明明写了元素，页面上什么都没有。

**根因**：类名拼接错了。比如模板里写 `class="ck%s"` 期望得到 `ck on`，
实际拼成 `ckon`；或者 CSS 定义的是 `.ck.on`（两类的组合），HTML 只给了 `.ck`。

**排查**：直接查 DOM：
```js
document.querySelectorAll('.ck').forEach(e => console.log(e.className, getComputedStyle(e).display))
```

**修法**：类名拼接一律用 `' '.join(["ck"] + extras)` 这种显式方式，不要靠字符串相邻拼接。

---

## 8. Python 生成 CSS 时报 `unsupported format character`

**症状**：
```
ValueError: unsupported format character ';' (0x3b) at index N
```

**根因**：用 `%` 做字符串格式化时，CSS 里的 `width:50%;` 中的 `%;` 被当成格式符。

**修法**：CSS 里的百分号写成 `%%`；或者干脆放弃 `%`，改用 f-string / `.format()` / 字符串拼接。

---

## 9. 改完样式，截图还是旧的

**症状**：代码明明改了，截图和浏览器里看到的完全没变。

**根因**：Chrome 对 `file://` 协议有缓存，`Page.navigate` 会命中缓存。

**修法**（必须做，否则会反复自我怀疑）：
```python
P.navigate("file://" + path + "?v=%d" % int(time.time()))
```
或调用 `Page.reload` 时传 `{"ignoreCache": True}`。
**每次截图脚本都要带这个，这是纪律不是技巧。**

---

## 10. 三张卡片高度不齐

**症状**：并排的卡片，内容少的明显矮一截，底部参差不齐。

**根因**：grid 里子项默认 `align-items:stretch` 会给高度，但卡片内部没有撑满；
或者卡片自己设了 `align-items:flex-start`。

**修法**：
```css
.card{height:100%;display:flex;flex-direction:column;}
.card .foot{margin-top:auto;}   /* 需要贴底的元素推到底 */
```
注意：`margin-top:auto` 会把中间空出来，如果内容少就会显得松散 ——
要么接受，要么用 `gap` 控制、不要用 auto 推底。

---

## 自查顺序（建议）

1. 布局类是不是复用了不该复用的（flex 当块、按钮条当栅格）→ 坑 1/3/5/6
2. 类名有没有和全局撞车 → 坑 2/7
3. 量一下宽度是否异常 → 坑 4
4. 截图确认前先确认缓存已破 → 坑 9
5. 卡片并排看底边 → 坑 10

---

## 11. 改了样式没反应：同一个类被定义了两次

`module_prd.html` 里 **`.px`、`.px-mask` 这类基础类被定义过两次**（多轮迭代叠加的），后一条覆盖前一条。
改样式时改到了前一条，浏览器用的是后一条 —— 看起来「改了没反应」，其实改的是死代码。

真实代价：修弹窗被裁时白折腾一整轮。

**做法**：改任何类的样式前，先数一遍这个类在文件里有几条规则：

```bash
python3 - <<'EOF'
import re
s=open('assets/module_prd.html',encoding='utf-8').read()
for m in re.finditer(r'\.px-mask\{[^}]*\}', s): print(m.group(0))
EOF
```

出现两次以上，就改**最后一条**，或者先把重复的清掉。同理适用于 `.px-table td`（有 `nowrap+ellipsis` 与 `normal` 两套，实际生效的是前者）。

---

## 12. 悬浮层被表格裁掉（hover 全看不见）

两个真凶，同时存在：

1. `.px-table td` 为了做省略号带 `overflow:hidden` —— 绝对定位的浮层被裁在单元格里；
2. `.px-tw`（表容器）带 `overflow-x:auto` —— 又被裁一层。

修法是**只对含浮层的表格放开**，不要把全局的 overflow 都改成 visible（那会让长表格横向溢出撑破画布）：

```css
.px-table td:has(.px-tips){overflow:visible}
.px-tw:has(.px-tips){overflow:visible}
```

---

## 13. 弹窗帧被裁：遮罩层级放错了

`px-mask` 放在 `.px-main` 里 → `.px-main{overflow:auto}` 会把遮罩和弹窗一起裁掉；
`.px-main` 又不是 `position:relative`，`inset:0` 的包含块变成别的，遮罩尺寸跟着内容走，只剩弹窗那么大。

**规矩**：

- `px-mask` 必须是 `.px` 的**直接子级**（画布层级），不能放进 `px-main`；
- 弹窗本身很高时，用画布变体 `.px.tall`（`min-height:680px`），**不要全局改 `.px` 的 min-height** ——
  那会让所有内容少的帧底部多出 200 多 px 空白；
- 宽弹窗用 `.px-dlg.wide`（1104px），顶部留白 56px。

---

## 14. 尺寸别靠眼看：两个可复现的测量手段

**① 量元素真实尺寸**（判断遮罩铺没铺满、弹窗有没有被切）：

```bash
chrome --headless=new --virtual-time-budget=2000 --dump-dom file:///tmp/probe.html
# 页面里注入：
# var r=el.getBoundingClientRect();
# document.title='x='+r.x+'|w='+r.width+'|h='+r.height
# 再用正则抓 <title> 的内容
```

**② 采样像素**（判断遮罩到底盖到哪，比肉眼看截图准）：

```python
from PIL import Image
im = Image.open('shot.png').convert('RGB')
print(im.getpixel((50, 300)), im.getpixel((1000, 300)))   # 暗色遮罩 vs 白色页面
```

截图固定 `--hide-scrollbars`；输出图会被等比缩放，目测坐标要换算。



---

## 15. 叙事正文的两处样式陷阱（2026-11-03 踩过）

**① `.warnbar` 不是强调块，是「缺段警告条」的专用样式。**
`shot_verify.py` 用 `document.querySelectorAll('.warnbar').length` 判断「sections 不足 8 段」——
正文里只要有一个 `.warnbar`，诊断就会误报「页面顶部有缺段警告条」。
正文要强调一条硬约束，用 `.callout`（蓝）或 `.callout.warn`（黄）；`.warnbar` 留给生成器。

**② `.doc code{white-space:nowrap}` 会在表格里溢出到邻列。**
`table-layout:fixed` 下单元格宽度是死的，长标识符（`operateType=view`、`bill_payout_account_config`）
不换行就会横着压到右边那一列，后半截被盖住，读起来像「operateType=vie«」。
模板已加一条兜底规则（只作用于表格内）：

```css
.doc td code,.doc th code,.doc li code{white-space:normal;word-break:break-word;overflow-wrap:anywhere}
```

段落里的 code 仍然 nowrap（保持不拆词），只有表格里允许折。**改模板时别把这条删了**。


---

## 16. 编号跳转与模式切换（2026-11-03 踩过）

**① 点原型上的改①②③，会跳到文档最顶端 —— 因为抓到了索引里的小标签。**
第 1 段的索引里每个编号都是一颗 `<a class="chg-jump" data-chg="C1">`，与正文的
`<div class="dchg" data-chg="C1">` **同编号**，而索引排在前面。原来的 `scrollIntoView(n.doc[0])`
拿到的正是那颗小标签，于是永远滚到顶部。

```js
// 挑滚动目标：正文块 > 附录块 > 非索引，chg-jump 永不参与
function pickDocTarget(list){
  var tiers = [
    function(e){ return e.classList.contains('dchg'); },
    function(e){ return e.closest('.spc') || e.classList.contains('spc'); },
    function(e){ return !e.classList.contains('chg-jump'); }
  ];
  ...
}
```

落到之后加 `.landed` 闪一圈边框（1.6s，尊重 `prefers-reduced-motion`），否则读者不知道「跳的是这一块」
还是「页面自己滚了」。**只看原型时点标注要自动 `goMode("both")`**——右栏藏着，点了什么都不会发生。

**② 顶栏按钮从 5 个收成 4 个，`?m=human` / `?m=proto` 就失效了。**
原来 `goMode()` 靠 `.click()` 一个存在的按钮来切；按钮没了就什么也不做。
模式必须用变量记（`CUR_MODE`），`goMode()` 找不到按钮时直接改变量 + `applyLayout()`。
截图脚本、分享链接都依赖这个。

**③ 模板里跨行字符串拼接漏 `+`，整页白屏但顶栏正常。**
`'第一句'  '第二句'` 是语法错误，整个 `<script>` 不执行，看起来像「数据没渲染」。
改完模板必须 `--dump-dom | grep CONSOLE` 验一遍，别看截图就交付。
