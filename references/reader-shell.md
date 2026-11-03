# 双栏阅读器外壳

一页 HTML 里同时装「可点的页面原型」和「规格文档」，配上双层导航。
单文件、无外部依赖、离线可开。

对应的可复制模板：`assets/prd_reader.html`。

---

## 一、整体结构

```
┌──────────────────────────────────────────────────────┐
│ 顶栏  [Logo 标题]        [模块1] [模块2] [模块3]  [工具] │  ← 模块 tab 带页数徽标
├──────────────────────────────────────────────────────┤
│ chip  [页面A] [页面B] [页面C] …                        │  ← 当前模块内的页面；单页模块时隐藏
├───────────────────────────────┬──────────────────────┤
│ 页面区（iframe，可缩放）        │ 文档栏（可关）        │
│                               │                      │
└───────────────────────────────┴──────────────────────┘
```

**为什么是两层**：一层平铺页签，模块一多就撑爆（13 个页签已经放不下，22 个必炸）。
两层之后，加模块只是顶栏多一个 tab，永远不失效。

---

## 二、数据结构（唯一的真源）

外壳只认一个数组，页面、文档、导航都由它驱动：

```python
MODULES = [
    # (模块key, 模块名, [(页面key, 页面名), ...])
    ("ov",   "总览",     [("ov", "总览")]),
    ("person","报名管理", [("p1","报名者列表"), ("p2","新增报名者①"), ("p3","新增报名者②")]),
    ("settle", "账单和用款申请",[("pa1","客户账单"), ("pa2","对账确认")]),
    ("other", "其他模块", [("oth","模块地图")]),
]
```

对应的渲染逻辑：

```js
function renderTabs(){
  tabs.innerHTML = MODULES.map(function(m,i){
    return '<div class="tab'+(i===curMid?' on':'')+'" onclick="go(\\''+m[0]+'\\')">'
         + m[1] + '<i>' + m[2].length + '</i></div>';   // i 是页数徽标
  }).join('');
}

function renderChips(){
  var m = MODULES[curMid];
  // 单页模块不显示 chip 行，避免只显示一个孤零零的标签
  chipBar.className = 'chb' + (m[2].length > 1 ? ' show' : '');
  chips.innerHTML = m[2].map(function(p){
    return '<span class="chip'+(p[0]===curPid?' on':'')+'" onclick="go(\\''+curMid+'\\',\\''+p[0]+'\\')">'
         + p[1] + '</span>';
  }).join('');
}
```

---

## 三、跳转函数：必须有一个按页面 key 直达的入口

```js
// 按 模块+页面 跳转
function go(mid, pid){ ... }

// 按页面 key 直达（不用知道它属于哪个模块）
// 截图脚本、外部深链、文档里互相引用都靠它
function goKey(pid){
  for (var i=0;i<MODULES.length;i++)
    for (var j=0;j<MODULES[i][2].length;j++)
      if (MODULES[i][2][j][0] === pid){ return go(MODULES[i][0], pid); }
  return false;
}
```

**`goKey` 是必须的**。没有它，写截图脚本时要手写"这页属于哪个模块"的映射表，
模块一调整就全错。

---

## 四、页面装进 iframe

页面内容是一段 HTML 字符串。两种装法，按长度选：

```js
// 短内容：直接 srcdoc
frame.srcdoc = pageHtml;

// 长内容（几十 KB，含大量样式）：srcdoc 在部分浏览器有长度限制，
// 改用 blob URL
var blob = new Blob([pageHtml], {type:'text/html'});
frame.src = URL.createObjectURL(blob);
```

**iframe 内部要单独写一份全局样式**（重置 body margin、设定基础字号），
因为它不继承父页面任何 CSS。这是新手最常漏的一步——打开页面一片默认宋体。

---

## 五、三个工具开关

| 开关 | 作用 | 实现要点 |
|:--|:--|:--|
| 文档 | 显示/隐藏右侧文档栏 | 切 `display`，同时要让页面区宽度重算 |
| 适应 | 按宽度缩放页面 | 给 iframe 容器设 `transform:scale(k)`，`k = 容器宽 / 设计宽` |
| 1:1 | 不缩放、可滚动 | 去掉 transform，允许横向滚动 |

缩放后**必须重算**容器高度，否则会出现大片空白或内容被裁：

```js
function fit(){
  var k = box.clientWidth / 1440;          // 1440 是设计稿宽度
  frame.style.transform = 'scale(' + k + ')';
  frame.style.transformOrigin = '0 0';
  frame.style.width = 1440 + 'px';
  frame.style.height = (box.clientHeight / k) + 'px';
}
```

窗口 resize、切换文档、切页之后都要调一次 `fit()`。

---

## 六、文档栏

```js
function DOC(key){
  var el = document.getElementById('doc-' + key);
  return el ? el.innerHTML : '';
}
```

- 每页文档预先渲染进隐藏的 `<div id="doc-p1">`，切页时取值灌进右侧栏。
  不要用 fetch（单文件没有服务端）。
- 文档栏缺 `min-width:0` 时，里面一张宽表格就能把左侧页面区挤成一条缝 ——
  这是最严重的一个坑，见 `css-pitfalls.md` 坑 4。

---

## 七、改样式时的顺序

1. 先改 CSS 变量（颜色、字号），全局生效
2. 再改具体组件类
3. 每次改完跑一遍截图核对（`scripts/shot_verify.py`），**带缓存破坏参数**
4. 类名新增时加业务前缀，避免与顶栏 `.tb`、`.th` 这种短名撞车
