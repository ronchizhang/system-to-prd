#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""快照 → 原型帧。把 snapshot_page.py 扒下来的真实 DOM 结构，转成 px- 组件的原型 HTML。

这是「原型图不许凭印象画」的第二半：
  snapshot_page.py  真实页面 → 结构化快照
  proto_from_snapshot.py  快照 → 原型帧 HTML（本文件）

转出来的帧只保留结构（几列、哪些字段、什么按钮、什么状态标签），
文案与示例数据全部取自快照本身，所以画出来的东西和真实页面同构。

用法：
    # 把快照写进模块数据（推荐）
    python3 proto_from_snapshot.py --snapshot snapshot/ops-field.json \\
        --data modules/ops-field.json --write

    # 先看会生成什么，不动文件
    python3 proto_from_snapshot.py --snapshot snapshot/ops-field.json
    python3 proto_from_snapshot.py --snapshot snapshot/ops-field.json --frame p1 --dump

    # 已有帧只补缺失的（默认行为是覆盖同名帧）
    python3 proto_from_snapshot.py --snapshot s.json --data m.json --write --keep-existing

外壳（顶栏 logo、顶栏菜单、侧栏菜单）不在页面 DOM 里稳定可得，从 --shell 读；
不给就用 crumb 反推，推不出来就留占位并在 note 里说明。

--shell 文件形如：
    {"logo": "DEMO <i>ADMIN</i>",
     "tmenu": [{"t": "客户"}, {"t": "报名者", "on": true}],
     "side": [{"t": "报名管理"}, {"t": "报名字段配置", "sub": true, "on": true}],
     "user": "运", "tenant": "示例客户"}

退出码：0 成功 / 2 参数错误 / 3 快照没有可用帧
"""
import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import schema as S  # noqa: E402

# 强制视口画布（--viewport）。默认长页面自动用整页画布，见 frame_html()。
VIEWPORT_MODE = False

# ---------------------------------------------------------------- 工具

TAG_COLOR = {
    "启用": "green", "已启用": "green", "正常": "green", "通过": "green",
    "成功": "green", "已完成": "green", "生效": "green", "已生效": "green",
    "停用": "red", "已停用": "red", "拒绝": "red", "失败": "red",
    "禁用": "red", "已删除": "red", "已终止": "red", "驳回": "red",
    "草稿": "amber", "待审核": "amber", "待处理": "amber", "审批中": "amber",
    "处理中": "amber", "待提交": "amber", "进行中": "blue",
}


def esc(s):
    return (str(s if s is not None else "")
            .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


def tag(text, color=None):
    c = color or TAG_COLOR.get(str(text).strip(), "")
    return '<span class="px-tag%s">%s</span>' % ((" " + c) if c else "", esc(text))


def wcls(i, n, name):
    """按列位置和列名给宽度 class，避免写 style。"""
    nm = str(name)
    if "操作" in nm or "动作" in nm:
        return "w-m"
    if i == 0:
        return "w-xl"
    if n >= 6:
        return "w-s"
    if n >= 4:
        return "w-m"
    return "w-l"


# ---------------------------------------------------------------- 外壳

DEFAULT_SHELL = {"logo": "DEMO <i>ADMIN</i>", "tmenu": [], "side": [], "user": "运"}


def load_shell(path=None):
    if not path:
        return dict(DEFAULT_SHELL)
    try:
        s = json.load(open(path, encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        sys.exit("✗ 读不了 --shell：%s" % exc)
    out = dict(DEFAULT_SHELL)
    out.update(s or {})
    return out


def shell_from_crumb(crumb):
    """没给 shell 时，从面包屑推一个最简侧栏。

    面包屑要能用：每段都得短、不能带冒号（带了说明抓到的是正文）。
    抓歪了宁可不要——空侧栏比错侧栏可信。
    """
    crumb = [c for c in (crumb or []) if c and len(c) <= 12 and "：" not in c and ":" not in c]
    if not crumb:
        return []
    items = []
    for i, c in enumerate(crumb):
        items.append({"t": c, "sub": i > 0, "on": i == len(crumb) - 1})
    return items


def render_top(shell, d=None):
    """顶栏：优先用数据里从真实页面抽到的菜单，其次用 --shell 给的。"""
    tm_items = None
    if d and d.get("topNav"):
        tm_items = d["topNav"]
    elif shell.get("tmenu"):
        tm_items = shell["tmenu"]
    tm = "".join('<span%s>%s</span>' % (' class="on"' if m.get("on") else "", esc(m.get("t")))
                 for m in (tm_items or []) if m.get("t"))
    tr = ""
    if shell.get("tenant"):
        tr += "<span>%s</span>" % esc(shell["tenant"])
    if shell.get("user"):
        tr += '<div class="px-av">%s</div>' % esc(shell["user"][:1])
    return ('<div class="px-top"><div class="px-logo">%s</div>'
            '<div class="px-tmenu">%s</div><div class="px-tright">%s</div></div>'
            % (shell.get("logo") or DEFAULT_SHELL["logo"], tm, tr))


def render_side(side):
    if not side:
        return ""
    h = ['<div class="px-side">']
    for m in side:
        cls = "px-mi"
        if m.get("sub"):
            cls += " sub"
        if m.get("on"):
            cls += " on"
        h.append('<div class="%s">%s</div>' % (cls, esc(m.get("t"))))
    h.append("</div>")
    return "".join(h)


def pick_side(shell, d):
    """侧栏来源优先级：快照抽到的真实菜单 > --shell 指定 > 面包屑反推。"""
    if d.get("sideNav") and len(d["sideNav"]) >= 2:
        return d["sideNav"]
    if shell.get("side"):
        return shell["side"]
    return shell_from_crumb(d.get("crumb") or [])


# ---------------------------------------------------------------- 表单

def ctrl_of(f):
    """字段 → 控件 HTML（只用 px- class）。"""
    ph = f.get("placeholder") or ""
    val = f.get("value") or ""
    ty = f.get("type") or "text"
    if ty in ("select", "date"):
        txt = esc(val or ph or "请选择")
        return '<div class="px-fctrl sel%s">%s</div>' % ("" if val else " ph", txt)
    if ty == "textarea":
        return '<div class="px-fctrl area ph">%s</div>' % esc(val or ph or "请输入")
    if ty in ("radio", "checkbox"):
        opts = f.get("options") or []
        if opts:
            on = (val == opts[0]) or ty == "checkbox"
            inner = "".join('<span class="px-chk%s">%s</span>'
                            % (" on" if (on and i == 0) else "", esc(o))
                            for i, o in enumerate(opts[:4]))
            return '<div class="px-fctrl">%s</div>' % inner
        return '<div class="px-fctrl ph">请选择</div>'
    if ty == "upload":
        return '<div class="px-fctrl ph">上传附件</div>'
    return '<div class="px-fctrl%s">%s</div>' % ("" if val else " ph",
                                                esc(val or ph or "请输入"))


def render_form(groups, cols=3, max_fields=0):
    """把 groups 渲染成若干段表单。cols=2 用于弹窗。"""
    h = []
    total = 0
    for g in groups:
        fields = [f for f in (g.get("fields") or []) if f.get("name")]
        if not fields:
            continue
        if g.get("name"):
            h.append('<div class="px-fhint"><b>%s</b></div>' % esc(g["name"]))
        h.append('<div class="px-form%s">' % (" c2" if cols == 2 else ""))
        for i, f in enumerate(fields):
            if max_fields and total >= max_fields:
                break
            total += 1
            star = "<em>*</em>" if f.get("required") else ""
            # 每段最后一个 + 单数余项 收整行
            left = len(fields) - i
            full = " full" if (left == 1 and (i % cols) != 0) else ""
            dis = " dis" if f.get("disabled") else ""
            h.append('<div class="px-frow%s"><div class="px-flabel">%s%s</div>%s</div>'
                     % (full, star, esc(f["name"]), ctrl_of(f)))
        h.append("</div>")
        for f in fields[:max_fields or len(fields)]:
            if f.get("hint"):
                h.append('<div class="px-fhint">%s —— %s</div>'
                         % (esc(f["name"]), esc(f["hint"])))
                break
    return "".join(h)


# ---------------------------------------------------------------- 表格

def col_widths(th, rows):
    """按「表头要几个字」和「内容平均多长」里大的那个挑宽度 class。

    只用 w-s/w-m/w-l/w-xl 四个固定档，不许写 style —— 这样十个人画出来一致。
    四档对应大约：84 / 132 / 24% / 30%（1440 画布下约 84/132/345/432 px）。
    """
    out = []
    n = len(th)
    # 列多（≥6）时表头普遍是 8-12 个汉字，硬按需求分档会互相挤压，
    # 不如交给 table-layout:fixed 均分，每列约 1440/n，刚好放得下
    if n >= 6:
        out = ["" for _ in th]
        # 列一多，均分宽度就两头不够用，各给一档：
        # 首列是单据编号（CBSQK2026… 这种 18 位），截断了就认不出是哪张单；
        # 末列是行操作，真实后台这里有「查看用款申请单 / 查看业务用款申请审批」两个链接，
        # 挤掉一个等于把入口画没了。
        if th:
            out[0] = "w-n"
        for i, name in enumerate(th):
            if "操作" in str(name) or "动作" in str(name):
                out[i] = "w-m"
        return out
    for i, name in enumerate(th):
        nm = str(name)
        if n == 1:
            out.append("")            # 单列撑满，不套宽度档
            continue
        if "操作" in nm or "动作" in nm:
            out.append("w-m")
            continue
        if i == 0:
            out.append("w-xl")
            continue
        need = len(nm) * 13 + 20              # 表头本身要放得下
        vals = []
        for r in rows or []:
            if i < len(r):
                c = r[i]
                vals.append(c.get("text") if isinstance(c, dict) else str(c))
        if vals:
            avg = sum(len(v or "") for v in vals) / float(len(vals))
            need = max(need, min(avg * 9, 330))   # 内容再长也不超过 330
        if need <= 84:
            out.append("w-s")
        elif need <= 132:
            out.append("w-m")
        else:
            out.append("w-l")
    return out


# 状态词的关键词 → 颜色。真实系统的状态是「业务用款申请审批中」这种复合词，
# 精确匹配对不上，只能按关键词归类
TAG_RULES = [
    (("已结算", "已完成", "已通过", "成功", "已生效", "启用", "通过"), "green"),
    (("退回", "驳回", "失败", "拒绝", "终止", "禁用", "停用", "异常"), "red"),
    (("审批中", "待审核", "待处理", "处理中", "待结算", "待确认"), "amber"),
    (("草稿", "待提交", "未开始"), "amber"),
    (("进行中", "部分", "发放中"), "blue"),
]


def tag_color_of(text):
    t = str(text or "").strip()
    if t in TAG_COLOR:
        return TAG_COLOR[t]
    for words, color in TAG_RULES:
        if any(w in t for w in words):
            return color
    return None


def cell_html(c):
    if isinstance(c, dict):
        t = c.get("text") or ""
        if c.get("tag"):
            return tag(c["tag"])
        col = tag_color_of(t)
        if col:
            # 真实系统常把「状态 + 月份」放同一格，只给状态上色，后面跟原文
            seg = t.strip().split(None, 1)
            out = tag(seg[0], col)
            if len(seg) > 1:
                out += " " + esc(seg[1])
            return out
        return esc(t)
    return esc(c)


def _split_selection(th, rows):
    """把 ant-table 的勾选列认出来。

    带行选择的表格，表头那一格是个空的 selection th（抓表头时因为没文字被过滤掉），
    但行里那一格还在。结果就是「行比表头多一格」：原型第一列画成空，后面所有数据
    整体左移一格——结算工作台列表就成了「费用类型那格写着用款申请编号」这种鬼样子。

    这里不是把多出来的那格丢掉，而是把选择列补回来（表头补一个空 th、行首补一个勾选框），
    因为真实页面那一列确实在。
    """
    if not th or not rows:
        return th, rows, False
    n = len(th)
    lens = {len(r) for r in rows if r}
    if lens != {n + 1}:
        return th, rows, False

    def _txt(c):
        return (c.get("text") if isinstance(c, dict) else (c or "")) or ""

    if not all(not _txt(r[0]).strip() for r in rows if r):
        return th, rows, False
    return th, [r[1:] for r in rows], True


def render_table(th, rows, row_btns=None):
    if not th:
        return '<div class="px-empty">这一帧没有抓到表格</div>'
    th, rows, sel = _split_selection(th, rows)
    n = len(th)
    ws = col_widths(th, rows)
    # 最后一列是操作列时标记出来：真实后台它固定在右侧（fixed right），
    # 横向滚动时不动。不钉住的话，宽表一滚操作列就没了——恰恰是最该看见的那列。
    act_last = bool(th) and ("操作" in str(th[-1]) or "动作" in str(th[-1]))
    head = ('<th class="w-c"><span class="px-chk"></span></th>' if sel else "") + \
           "".join('<th class="%s%s">%s</th>'
                   % (ws[i] if i < len(ws) else "w-m",
                      " actr" if (act_last and i == n - 1) else "", esc(t))
                   for i, t in enumerate(th))
    body = []
    for r in rows or []:
        tds = []
        for i, c in enumerate(r[:n]):
            nm = th[i] if i < n else ""
            if "操作" in str(nm) or "动作" in str(nm):
                # 优先拆实拍到的操作文案（如「查看用款申请单 查看业务用款申请审批」），
                # 抓不到才退回通用按钮
                raw = (isinstance(c, dict) and c.get("text")) or ""
                parts = [x for x in str(raw).split() if x] or \
                        [b["text"] for b in (row_btns or [])[:3]]
                links = "".join('<span class="px-btn link%s">%s</span>'
                                % (" d" if ("删除" in p or "终止" in p) else "", esc(p))
                                for p in parts[:3])
                tds.append('<td%s>%s</td>'
                           % (' class="actr"' if (act_last and i == n - 1) else "", links))
            else:
                tds.append("<td>%s</td>" % cell_html(c))
        if sel:
            tds.insert(0, '<td class="c"><span class="px-chk"></span></td>')
        body.append("<tr>%s</tr>" % "".join(tds))
    if not body:
        body.append('<tr><td colspan="%d">%s</td></tr>'
                    % (n + (1 if sel else 0), '<div class="px-empty">暂无数据</div>'))
    # 列数一多（结算工作台 9 列 + 勾选列），固定布局会把每列压到 110px，
    # 每格都只剩省略号。真实页面这里本来就是横向可滚动的，所以按内容撑开、
    # 由外层容器滚，跟后台表现一致。
    wide = " wide" if n >= 9 else ""
    return ('<div class="px-tw%s"><table class="px-table">%s%s</table></div>'
            % (wide, "<tr>%s</tr>" % head, "".join(body)))


# ---------------------------------------------------------------- 工具条

def render_toolbar(fields, buttons):
    """搜索区字段 ≤3 个进工具条，其余当表单；按钮取主次各一。"""
    h = ['<div class="px-toolbar">']
    for f in fields[:3]:
        if f.get("type") in ("select", "date"):
            h.append('<div class="px-sel">%s</div>'
                     % esc(f.get("placeholder") or f["name"]))
        else:
            h.append('<div class="px-in ph">%s</div>'
                     % esc(f.get("placeholder") or f["name"]))
    h.append('<span class="sp"></span>')
    used = 0
    seen = set()
    for b in buttons or []:
        if b.get("link") or b.get("disabled"):
            continue
        # 筛选栏只放筛选语义的按钮。页面级主操作（批量结算、新建…）不属于这里，
        # 它们画在列表底栏左边；两处都放，页面上就会出现两个「批量结算」。
        if (b.get("text") or "").strip() not in BTN_WORDS:
            continue
        if used >= 3:
            break
        # 真实页面会把工具条渲两遍（一版可见、一版给吸顶/测量用），DOM 里就能抓到
        # 两组「查询/重置」。不过滤的话原型上会出现两个查询按钮。
        key = (b.get("text") or "").replace(" ", "")
        if key in seen:
            continue
        seen.add(key)
        cls = "px-btn" + (" pri" if b.get("primary") else "")
        h.append('<button class="%s">%s</button>' % (cls, esc(b["text"])))
        used += 1
    h.append("</div>")
    return "".join(h)


# ---------------------------------------------------------------- 主渲染

def render_dialog_body(d, groups):
    """弹窗体：优先表单，其次自定义列表，最后把表格缩进弹窗。"""
    if any(g.get("fields") for g in groups):
        return render_form(groups, cols=2)
    items = d.get("listItems") or []
    if items:
        more = max(0, len(items) - 8)
        rows = [[{"text": it}] for it in items[:8]]
        if more:
            rows.append([{"text": "（另有 %d 条未画）" % more}])
        return render_table(["条目（实拍顺序）"], rows)
    tbs = d.get("tables") or []
    if tbs:
        return render_table(tbs[0].get("th"), tbs[0].get("rows"))
    return ""



# ---------------------------------------------------------------- 详情页布局

# ---------------------------------------------------------------- 详情页：有序块
#
# 详情页的排版是「内联样式 + 绝对位置」，没有语义 class。要画得像，
# 唯一的办法是还原「谁在谁上面、谁在谁右边」。所以这里不看 HTML 结构，
# 只看坐标：把每个文字块的 (x, y, 字号, 字重) 摊平，按 y 切行、按 x 配对，
# 生成一串有序的块，再依次渲染。顺序对了，图就对了。

_INLINE_RE = re.compile(r"^([^：:\s]{1,18})[：:]\s*(\S.*)$")
_NUM_RE = re.compile(r"^[\d,.\s%+\-]+$")
_UPLOAD_RE = re.compile(r"^\d+\s*/\s*\d+$")

# 这些是操作控件，不是字段
SKIP_TEXT = {
    "查询", "查 询", "重置", "重 置", "导出", "导 出", "搜索", "确定", "取消",
    "保存", "提交", "返回", "关闭", "更多", "展开", "收起", "请选择", "全部",
    "新增", "编辑", "删除", "查看", "下载", "上传",
}


def _is_section(e):
    """顶层分块标题：字号 16 以上、加粗、无冒号、短。"""
    t = e.get("t") or ""
    return (bool(t) and "：" not in t and ":" not in t and len(t) <= 16
            and e.get("fs", 0) >= 16 and e.get("fw", 400) >= 600
            and not _NUM_RE.match(t))


def _is_sub(e):
    """块内小标题：14 号加粗。"""
    t = e.get("t") or ""
    return (bool(t) and "：" not in t and ":" not in t and len(t) <= 16
            and 13 <= e.get("fs", 0) < 16 and e.get("fw", 400) >= 600
            and not _NUM_RE.match(t))


def _inline_pair(e):
    m = _INLINE_RE.match(e.get("t") or "")
    if not m:
        return None
    k, v = m.group(1).strip(), m.group(2).strip()
    if not k or not v:
        return None
    return {"k": k, "v": v}


def _pair_by_x(labels, values):
    """按 x 区间把值配给标签。

    真实页面一行可能有 2-3 个标签，下一行对应数量的值，靠 x 落在哪个区间判断归属。
    多出来的值（单选组、时区后缀）挂到同一个字段上：第一个当值，其余当选项/后缀。
    """
    pairs = []
    for i, lb in enumerate(labels):
        lo = lb["x"] - 8
        hi = (labels[i + 1]["x"] - 8) if i + 1 < len(labels) else 10 ** 6
        got = [v for v in values if lo <= v["x"] < hi]
        sel = next((g["t"] for g in got if g.get("chk")), "")
        kname = (lb.get("t") or "").strip()
        is_radio = any(g.get("chk") or g.get("dis") for g in got)
        # 编辑态的自定义单选抓不到 ant-radio 的类名，按字段名兜底
        if not is_radio and len(got) >= 2 and kname.endswith("状态"):
            is_radio = True
        pairs.append({
            "k": (lb.get("t") or "").strip().rstrip("：:").strip(),
            "v": got[0]["t"] if got else "",
            "opts": [g["t"] for g in got[1:]],
            "sel": sel,
            "radio": is_radio,
            "dis": [g["t"] for g in got if g.get("dis")],
            "box": bool(got and got[0].get("box")),
        })
    # 没被任何标签认领的值：贴到前一个字段后面（如「UTC+8」）
    if pairs:
        lo_all = labels[0]["x"] - 8
        hi_all = (labels[-1]["x"] - 8) if len(labels) > 1 else lo_all
        for v in values:
            if v["x"] < lo_all:
                continue
            if hi_all != 10 ** 6 and v["x"] >= hi_all:
                if v["t"] not in pairs[-1]["opts"] and v["t"] != pairs[-1]["v"]:
                    pairs[-1]["opts"].append(v["t"])
    return [p for p in pairs if p["k"]]


def _group_rows(items):
    """按 y 聚行，行内按 x 排。"""
    items = sorted(items, key=lambda e: (e["y"], e["x"]))
    rows, cur, ly = [], [], None
    for it in items:
        if ly is None or abs(it["y"] - ly) <= 6:
            cur.append(it)
            if ly is None:
                ly = it["y"]
        else:
            rows.append(cur)
            cur = [it]
            ly = it["y"]
    if cur:
        rows.append(cur)
    for r in rows:
        r.sort(key=lambda e: e["x"])
    return rows


def _split_columns(items):
    """块内两列布局：同一行出现两个小标题且 x 相差很大时切开。"""
    for r in _group_rows(items):
        subs = [e for e in r if _is_sub(e)]
        if len(subs) >= 2 and subs[-1]["x"] - subs[0]["x"] > 300:
            cut = (subs[0]["x"] + subs[1]["x"]) // 2
            left = [e for e in items if e["x"] < cut]
            right = [e for e in items if e["x"] >= cut]
            if left and right:
                return [left, right]
    return None


BTN_WORDS = {"查询", "查 询", "重置", "重 置", "导出", "导 出", "搜索"}


def _labelish(e):
    """像不像一个字段标签（不带冒号的那种）。"""
    t = (e.get("t") or "").strip()
    if not t:
        return False
    if t.endswith(("：", ":")):
        return len(t) <= 24
    if len(t) > 14 or e.get("fs", 0) >= 16 or _NUM_RE.match(t) or t in SKIP_TEXT:
        return False
    return True


def _row_pairs(row):
    """同一行里「标签：值 标签：值」这种并排的拆开。"""
    out, i, n = [], 0, len(row)
    while i < n:
        e = row[i]
        t = (e.get("t") or "").strip()
        if t in BTN_WORDS:
            i += 1
            continue
        p = _inline_pair(e)
        if p:
            p["inline"] = True
            out.append(p)
            i += 1
            continue
        if t.endswith(("：", ":")):
            k = t.rstrip("：:").strip()
            v, j = "", i + 1
            if j < n and not (row[j]["t"] or "").strip().endswith(("：", ":")):
                v = (row[j]["t"] or "").strip()
                j += 1
            if k:
                out.append({"k": k, "v": v, "opts": [], "inline": True})
            i = j
            continue
        i += 1
    return out


def _is_stats_row(r):
    """这一行是不是「标签：数字」连排的统计行。"""
    cnt, k = 0, 0
    while k + 1 < len(r):
        lt = (r[k].get("t") or "").strip()
        vt = (r[k + 1].get("t") or "").strip()
        if lt.endswith(("：", ":")) and _NUM_RE.match(vt):
            cnt += 1
            k += 2
        else:
            k += 1
    return cnt >= 3


def _is_fcard_head(row):
    """这一行是不是「流程卡片」的头部（以流程编号开头的那种豆腐块）。"""
    for e in row:
        t = (e.get("t") or "").strip().rstrip("：:")
        if t == "流程编号":
            return True
    return False


def _parse_fcard(events, i, right_edge=1400):
    """解析一块「流程卡片」（财务用款申请申请那种一格一格的豆腐块）。

    真实形态：
        ● 流程编号：HWZF20260401150001                      [审批中]
          申请类型  海外支付用款申请   发起时间  2026.04.01 15:28   审批结束时间  -
          申请金额  31.00 CNY

    一张卡 = 一条财务用款申请。一个业务用款申请被财务拆成 N 条，这里就有 N 张，
    所以切分规则是「再遇到流程编号就另起一张」，不是「只抓一张」。

    这些行既不是 ant-form-item 也没有冒号，按普通字段解析只会把三列的
    标签和值揉成一串，所以必须单独认。
    """
    rows, j = [], i
    while j < len(events):
        y, kind, payload = events[j]
        if kind != "row":
            break
        row = payload
        texts = [(e.get("t") or "").strip() for e in row if (e.get("t") or "").strip()]
        if not texts:
            j += 1
            continue
        if any(t in BTN_WORDS for t in texts):
            break
        if any(_is_section(e) or _is_sub(e) for e in row):
            break
        if j > i:
            # 换卡了，交给外层重新起一张
            if _is_fcard_head(row):
                break
            # 和上一行隔太远，说明已经出了这张卡
            if y - events[j - 1][0] > 60:
                break
        rows.append(row)
        j += 1
    if not rows:
        return None

    head = rows[0]
    code, state = "", ""
    for e in head:
        t = (e.get("t") or "").strip()
        if not t or t.rstrip("：:") == "流程编号":
            continue
        if e.get("box"):
            state = t
        elif not code and not t.endswith(("：", ":")):
            code = t

    body = []
    for row in rows[1:]:
        pair, k = [], 0
        while k + 1 < len(row):
            kk = (row[k].get("t") or "").strip().rstrip("：:")
            vv = (row[k + 1].get("t") or "").strip()
            if kk:
                pair.append({"k": kk, "v": vv})
            k += 2
        if pair:
            body.append(pair)

    return {"t": "fcard", "code": code, "state": state, "rows": body, "next": j}


def _parse_column(items, tables, right_edge=1400):
    """一列内容 → 有序块序列。"""
    rows = _group_rows(items)
    events = [(t.get("y") or 0, "table", t) for t in tables]
    events += [(r[0]["y"], "row", r) for r in rows]
    events.sort(key=lambda e: e[0])

    blocks = []

    def next_row(idx):
        j = idx + 1
        while j < len(events) and events[j][1] != "row":
            j += 1
        return (j, events[j][2]) if j < len(events) else (None, None)

    i = 0
    while i < len(events):
        y, kind, payload = events[i]
        if kind == "table":
            blocks.append({"t": "table", "th": payload.get("th") or [],
                           "rows": payload.get("rows") or []})
            i += 1
            continue

        row = payload
        texts = [(e["t"] or "").strip() for e in row]
        texts = [t for t in texts if t]
        if not texts:
            i += 1
            continue

        # ① 上传区
        if len(row) == 1 and _UPLOAD_RE.match(texts[0]):
            blocks.append({"t": "upload", "note": texts[0]})
            i += 1
            continue

        # ② 筛选操作栏
        if any(t in BTN_WORDS for t in texts):
            filters = []
            for e in row:
                t = (e["t"] or "").strip()
                if t in BTN_WORDS:
                    continue
                p = _inline_pair(e)
                if p:
                    filters.append(p)
                elif t.endswith(("：", ":")):
                    filters.append({"k": t.rstrip("：:"), "v": ""})
                elif _labelish(e):
                    filters.append({"k": t, "v": ""})
            blocks.append({"t": "toolbar", "filters": filters,
                           "buttons": [t for t in texts if t in BTN_WORDS]})
            i += 1
            continue

        j, nxt = next_row(i)

        # ③-a 统计卡（同一行版）：一行里连着出现「标签：数字」，可带行首标题
        if len(row) >= 4:
            start, k = None, 0
            while k + 1 < len(row):
                lt = (row[k].get("t") or "").strip()
                vt = (row[k + 1].get("t") or "").strip()
                if lt.endswith(("：", ":")) and _NUM_RE.match(vt):
                    start = k
                    break
                k += 1
            stats = []
            if start is not None:
                k = start
                while k + 1 < len(row):
                    lt = (row[k].get("t") or "").strip()
                    vt = (row[k + 1].get("t") or "").strip()
                    if lt.endswith(("：", ":")) and _NUM_RE.match(vt):
                        stats.append({"k": lt.rstrip("：:"), "v": vt, "opts": []})
                        k += 2
                    else:
                        break
            if len(stats) >= 3:
                if start > 0:
                    blocks.append({"t": "sub", "extra": [],
                                   "title": (row[0].get("t") or "").strip()})
                blocks.append({"t": "stats", "items": stats})
                i += 1
                continue

        # ③-b 统计卡（跨行版）：本行纯数字，下一行等量标签
        if (nxt and len(row) >= 2
                and all(_NUM_RE.match(t) for t in texts)
                and len(nxt) == len(row)
                and all((e["t"] or "").strip().endswith(("：", ":")) for e in nxt)):
            blocks.append({"t": "stats", "items": _pair_by_x(nxt, row)})
            i = j + 1
            continue

        # ③-c 合计行：最左边是「XX：」，右边是金额（可能带币种、加号）
        if (texts[0].endswith(("：", ":")) and len(row) >= 3
                and any(_NUM_RE.match(t) for t in texts[1:])):
            blocks.append({"t": "total", "k": texts[0].rstrip("：:"),
                           "v": " ".join(texts[1:])})
            i += 1
            continue

        # ③-d 大字号单行：主体名 / 详情页大标题
        if (len(row) == 1 and row[0].get("fs", 0) >= 20
                and 2 <= len(texts[0]) <= 40):
            blocks.append({"t": "h2", "text": texts[0]})
            i += 1
            continue

        # ④ 头像 + 姓名 + 部门
        if len(row) == 1 and len(texts[0]) == 1 and row[0]["fs"] >= 24:
            name, dept = "", ""
            j2, nrow = next_row(i)
            if nrow and len(nrow) == 1:
                name = (nrow[0]["t"] or "").strip()
                j3, crow = next_row(j2)
                if crow and len(crow) == 1 and len((crow[0]["t"] or "").strip()) <= 24 \
                        and not (crow[0]["t"] or "").strip().endswith(("：", ":")):
                    dept = (crow[0]["t"] or "").strip()
                    j2 = j3
                blocks.append({"t": "person", "avatar": texts[0], "name": name, "dept": dept})
                i = j2 + 1
                continue

        # ⑤ 小标题（可以和状态标签同行）
        subs = [e for e in row if _is_sub(e)]
        if subs:
            # 附加文字：紧跟在小标题右边的（同栏），或贴在整行最右边的状态标签
            extra = [e["t"] for e in row
                     if e not in subs
                     and (e["x"] < subs[0]["x"] + 300 or e["x"] > right_edge - 120)]
            blocks.append({"t": "sub", "title": subs[0]["t"], "extra": extra})
            i += 1
            continue

        # ⑤-b 上传区：标签 + 「支持扩展名：...」
        up = [e for e in row if "支持扩展名" in (e.get("t") or "")]
        if up:
            label = next(((e.get("t") or "").strip() for e in row
                          if "支持扩展名" not in (e.get("t") or "")), "")
            blocks.append({"t": "upload", "note": label, "ext": (up[0].get("t") or "").strip()})
            i += 1
            continue

        # ⑤-c 流程卡片（豆腐块）：一张卡 = 一条财务用款申请，可能有多张
        if _is_fcard_head(row):
            card = _parse_fcard(events, i, right_edge)
            if card:
                blocks.append({k: v for k, v in card.items() if k != "next"})
                i = card["next"]
                continue

        # ⑥ 同一行并排的「标签：值」
        if any(t.endswith(("：", ":")) for t in texts) or any(_inline_pair(e) for e in row):
            pairs = _row_pairs(row)
            if pairs:
                blocks.append({"t": "fields", "rows": [pairs]})
                i += 1
                continue

        # ⑥-b 同一行里标签和值挨着（间距小），值可能带后缀（时区、单位）
        if (len(row) >= 2 and _labelish(row[0])
                and not (row[0].get("t") or "").strip().endswith(("：", ":"))
                and (row[1]["x"] - row[0]["x"]) < 220):
            vals = [(e.get("t") or "").strip() for e in row[1:]]
            blocks.append({"t": "fields", "rows": [[{
                "k": texts[0], "v": " ".join(v for v in vals if v),
                "opts": [], "inline": True}]]})
            i += 1
            continue

        # ⑦ 标签行 + 下一行值（标签不带冒号也算，如「打款方式」）
        if (nxt is not None and all(_labelish(e) for e in row)
                and not _is_stats_row(nxt)
                and not _UPLOAD_RE.match((nxt[0].get("t") or "").strip())
                and not all(_NUM_RE.match((e["t"] or "").strip()) for e in nxt)):
            # 「标签」+ 下一行「支持扩展名…」= 上传区，不是字段值
            ext = next(((g.get("t") or "").strip() for g in nxt
                        if "支持扩展名" in (g.get("t") or "")), "")
            if ext:
                blocks.append({"t": "upload", "note": texts[0], "ext": ext})
                i = j + 1
                continue
            blocks.append({"t": "fields", "rows": [_pair_by_x(row, nxt)]})
            i = j + 1
            continue

        # ⑨ 单行短文本 + 下一行单值
        if (len(row) == 1 and nxt is not None and len(nxt) == 1
                and len(texts[0]) <= 16
                and not _UPLOAD_RE.match((nxt[0].get("t") or "").strip())
                and "支持扩展名" not in (nxt[0].get("t") or "")):
            blocks.append({"t": "fields", "rows": [[{
                "k": texts[0].rstrip("：:"),
                "v": (nxt[0]["t"] or "").strip(), "opts": []}]]})
            i = j + 1
            continue

        # ⑩ 其余当一段文字
        keep = [t for t in texts if t not in SKIP_TEXT]
        if keep:
            blocks.append({"t": "para", "text": " ".join(keep)})
        i += 1

    # 相邻的字段网格合并成一张
    merged = []
    for b in blocks:
        if b["t"] == "fields" and merged and merged[-1]["t"] == "fields":
            merged[-1]["rows"].extend(b["rows"])
        else:
            merged.append(b)
    return merged


def _build_body(items, tables, right_edge=1400):
    """一个分块内的内容。

    真实详情页里，「发起人信息 / 流程状态信息 / 用款申请信息」是三个**独立的带框小卡片**，
    左窄右宽并排。所以这里按 x 把整块内容分到左右两栏，每栏里的小标题画成子卡片。
    """
    if not items:
        return [{"t": "table", "th": tb.get("th") or [], "rows": tb.get("rows") or []}
                for tb in tables]

    rows = _group_rows(items)
    dual = None
    for r in rows:
        subs = [e for e in r if _is_sub(e)]
        if len(subs) >= 2 and subs[-1]["x"] - subs[0]["x"] > 300:
            dual = (subs[0]["x"], subs[1]["x"])
            break
    if not dual:
        return _parse_column(items, tables, right_edge)

    xl, xr = dual
    cut = (xl + xr) // 2
    left = [e for e in items if e["x"] < cut]
    right = [e for e in items if e["x"] >= cut]
    # 右栏宽度 = 内容区右边界 - 右栏起点。不能用文字右边缘算，
    # 右栏文字短的时候会把右栏算得比实际窄很多。
    widths = [max(160, xr - xl - 20), max(160, right_edge - xr)]
    mw = max(1, min(widths))
    flex = [max(1, min(3, int(round(w / mw)))) for w in widths]

    return [{"t": "cols", "flex": flex,
             "cols": [_parse_column(left, tables, right_edge),
                      _parse_column(right, [], right_edge)]}]


def build_blocks(d):
    """一帧详情页快照 → 顶层分块列表（每个分块内含有序的 body 块）。"""
    items = []
    for r in (d.get("layoutRows") or []):
        for e in r:
            t = (e.get("t") or "").strip()
            if not t:
                continue
            items.append({"t": t, "x": int(e.get("x") or 0), "y": int(e.get("y") or 0),
                          "w": int(e.get("w") or 0), "box": bool(e.get("box")),
                          "chk": bool(e.get("chk")), "dis": bool(e.get("dis")),
                          "fs": e.get("fs") or 0, "fw": e.get("fw") or 400,
                          "idx": e.get("idx", -1)})
    if not items:
        return []

    tables = [t for t in (d.get("tables") or []) if t.get("th")]
    buttons = d.get("buttons") or []

    # 按钮自己的文字节点也会被当成普通文本抓进来（「流程干预」「收起明细」这种）。
    # 它们已经作为块头操作了，别再当字段画一遍。用文档序相邻来判定，
    # 这样「查询/重置/导出」这类还留在文本里，能拼出筛选栏。
    def _is_btn_text(e):
        # 查询/重置/导出 是筛选栏的按钮，文字要留着，才能拼出整条筛选栏
        if e["t"] in BTN_WORDS:
            return False
        for b in buttons:
            bt = (b.get("text") or "").strip()
            if not bt or bt != e["t"]:
                continue
            if abs((b.get("y") or 0) - e["y"]) <= 60 and abs((b.get("x") or 0) - e["x"]) <= 90:
                return True
        return False

    items = [e for e in items if not _is_btn_text(e)]
    if not items:
        return []

    # 分块标题：必须贴着内容左边界。正文里也有 16 号加粗（主体名、部门名），
    # 靠 x 位置区分——标题永远在左侧最外面。
    left = min(e["x"] for e in items)
    secs, seen = [], set()
    for it in sorted(items, key=lambda e: e["y"]):
        if not _is_section(it):
            continue
        if it["x"] > left + 45:
            # 例外：和已识别的标题同一行、且明显靠右的，是并排的第二张卡
            # （打款信息 | 报名者收款账户信息（银行卡））。
            # 但要真是一张卡的标题——它下面得有自己的内容，
            # 否则「业务用款申请审批中」这种右上角状态标签会被误判成分块。
            twin = any(abs(sec["y"] - it["y"]) <= 12 and it["x"] - sec["x"] > 300
                       for sec in secs)
            if not twin:
                continue
            own = [e for e in items
                   if e["x"] >= it["x"] - 60 and it["y"] + 8 < e["y"] < it["y"] + 800]
            if len(own) < 2:
                continue
        key = (it["t"], it["y"] // 24)
        if key in seen:
            continue
        seen.add(key)
        secs.append({"y": it["y"], "x": it["x"], "title": it["t"], "idx": it.get("idx", -1),
                     "items": [], "tables": [], "actions": [], "head_extra": "",
                     "head_inline": ""})
    if not secs:
        # 列表页也没有 16 号加粗分块标题（只有 h1 + 筛选栏 + 表格），
        # 所以这条兜底必须先认出「这是列表页」，把它原样交回给 frame_html 的
        # 列表分支（那边会先画筛选栏、再画表格、最后画分页）。
        # 抢过来当正文解析的后果：整张表 30 行被拆成「标签 / 值」乱配，
        # 侧边栏菜单的文字也会被当成字段——结算工作台就是这么被画坏的。
        if any((t.get("rowCount") or 0) > 3 for t in tables) or d.get("pager"):
            return []

        # 剩下的才是「没有分块标题的详情/页签内容」（页签里的「财务用款申请申请」：
        # 整屏只有几块流程卡片）。以前这里直接返回空，于是退回通用的
        # 「字段 / 值」两列表，卡片结构就没了。有内容就按一个隐形体走。
        #
        # 但少了分块标题这道「挡板」，顶栏的返回链接、头像、页签名会被当成正文。
        # 所以先找到第一处真正的内容锚点，把上面的页面外壳切掉。
        anchor = None
        for r in _group_rows(items):
            if _is_fcard_head(r) or any(
                    (e.get("t") or "").strip().endswith(("：", ":")) for e in r):
                anchor = r[0]["y"]
                break
        if anchor is None and tables:
            anchor = min(t.get("y") or 0 for t in tables)
        if anchor is not None:
            items = [e for e in items if e["y"] >= anchor - 24]
        if len(items) >= 3 or tables:
            return _build_body(items, tables)
        return []

    titles = {(s["title"], s["y"]) for s in secs}

    # 同一 y 上的分块 = 一行里的几张并排卡
    sec_rows = []
    for s in secs:
        if sec_rows and abs(sec_rows[-1][0]["y"] - s["y"]) <= 12:
            sec_rows[-1].append(s)
        else:
            sec_rows.append([s])

    def owner(y, x=0):
        cur_row = None
        for row in sec_rows:
            if row[0]["y"] - 8 <= y:
                cur_row = row
            else:
                break
        if not cur_row:
            return None
        if len(cur_row) == 1:
            return cur_row[0]
        best = cur_row[0]
        for s2 in cur_row[1:]:
            if x >= s2["x"] - 60:
                best = s2
        return best

    for it in items:
        if (it["t"], it["y"]) in titles:
            continue
        s = owner(it["y"], it["x"])
        if not s:
            continue
        # 标题同一行：靠右的是块头状态（用款申请状态：审批中），靠左的是紧随标题的说明
        # （审批信息 流程编号：(CBSQK...)）——真实页面这两者都在标题同一行
        if abs(it["y"] - s["y"]) <= 10:
            if it["x"] > s["x"] + 600:
                s["head_extra"] += it["t"]
            else:
                s["head_inline"] += it["t"]
            continue
        s["items"].append(it)

    for tb in tables:
        s = owner(tb.get("y") or 0, tb.get("x") or 0)
        if s:
            s["tables"].append(tb)

    # 按钮归属分块：按文档顺序找它前面最近的一个分块标题。
    # 不用坐标——固定底栏/吸顶操作条里的按钮，坐标会飘到页面中段。
    float_acts = []
    for b in buttons:
        t = (b.get("text") or "").strip()
        if not t or t in SKIP_TEXT:
            continue
        if b.get("float"):
            if t not in float_acts:
                float_acts.append(t)
            continue
        bidx = b.get("idx", -1)
        target = None
        if bidx >= 0:
            for s in secs:
                if s.get("idx", -1) >= 0 and s["idx"] < bidx:
                    target = s
                else:
                    break
        if target is None:
            for s in secs:
                if abs((b.get("y") or 0) - s["y"]) <= 22:
                    target = s
                    break
        if target is not None and t not in target["actions"]:
            target["actions"].append(t)

    # 块头右侧文字如果和按钮重名，只留按钮（文字是按钮的文字节点）
    for s in secs:
        for a in s["actions"]:
            s["head_extra"] = s["head_extra"].replace(a, "")

    right_edge = max((e["x"] + (e.get("w") or 0) for e in items), default=1400)
    def sec_block(s):
        body = _build_body(s["items"], s["tables"], right_edge)
        acts = list(s["actions"])
        if any(b["t"] == "upload" for b in body) and "上传文件" in acts:
            acts.remove("上传文件")
        return {"t": "sec", "title": s["title"], "actions": acts,
                "head_extra": s["head_extra"],
                "head_inline": s.get("head_inline") or "", "body": body}

    out = []
    used = set()
    for row in sec_rows:
        if len(row) > 1:
            row_sorted = sorted(row, key=lambda z: z["x"])
            blocks, flex = [], []
            for s2 in row_sorted:
                blocks.append([sec_block(s2)])
                flex.append(1)
            out.append({"t": "cols", "flex": flex, "cols": blocks})
            for s2 in row_sorted:
                used.add(id(s2))
            continue
        s = row[0]
        body = _build_body(s["items"], s["tables"], right_edge)
        acts = list(s["actions"])
        # 上传区已经画成虚线框了，别再在块头放一个「上传文件」
        if any(b["t"] == "upload" for b in body) and "上传文件" in acts:
            acts.remove("上传文件")
        out.append({"t": "sec", "title": s["title"], "actions": acts,
                    "head_extra": s["head_extra"],
                    "head_inline": s.get("head_inline") or "", "body": body})
    if float_acts:
        out.append({"t": "foot", "actions": float_acts})
    return out


def _render_one(b):
    t = b["t"]
    if t == "fields":
        h = ['<div class="px-kv">']
        for row in b["rows"]:
            h.append('<div class="px-kvrow">')
            for f in row:
                inl = " inl" if f.get("inline") else ""
                h.append('<div class="px-kvi%s">' % inl)
                if f.get("inline"):
                    h.append('<span class="px-k">%s</span>' % esc(f["k"]))
                else:
                    h.append('<div class="px-k">%s</div>' % esc(f["k"]))
                if f.get("opts") and not f.get("radio"):
                    h.append('<div class="px-v">%s</div>'
                             % esc(" ".join([f["v"]] + f["opts"])))
                elif f.get("opts"):
                    sel = f.get("sel") or ""
                    dis = set(f.get("dis") or [])
                    h.append('<div class="px-seg">')
                    for o in [f["v"]] + f["opts"]:
                        if not o:
                            continue
                        cls = ""
                        if sel:
                            cls = " on" if o == sel else ""
                        else:
                            cls = " on" if o == f["v"] else ""
                        # 只读详情页里所有单选框都是 disabled，选中的那个要按选中画
                        if o in dis and o != sel:
                            cls += " dis"
                        h.append('<span class="px-segi%s">%s</span>'
                                 % (cls, esc(o)))
                    h.append("</div>")
                elif f.get("inline"):
                    h.append('<span class="px-v">%s</span>' % (esc(f["v"]) or "&nbsp;"))
                elif f.get("box"):
                    h.append('<div class="px-vbox">%s</div>'
                             % (esc(f["v"]) or "&nbsp;"))
                else:
                    h.append('<div class="px-v">%s</div>' % (esc(f["v"]) or "&nbsp;"))
                h.append("</div>")
            h.append("</div>")
        h.append("</div>")
        return "".join(h)
    if t == "fcard":
        # 流程卡片：一条财务用款申请一格。拆单后会有多格，所以这张卡要能被复用。
        h = ['<div class="px-fcard"><div class="px-fc-hd">'
             '<i class="px-fc-dot"></i>'
             '<span class="px-fc-k">流程编号：</span>'
             '<span class="px-fc-code">%s</span>' % esc(b.get("code") or "")]
        if (b.get("state") or "").strip():
            h.append('<span class="px-tag %s">%s</span>'
                     % (tag_color_of(b["state"]), esc(b["state"])))
        h.append("</div>")
        for row in b.get("rows") or []:
            h.append('<div class="px-fc-row">')
            for f in row:
                h.append('<div class="px-fc-i"><span class="px-fc-l">%s</span>'
                         '<span class="px-fc-v">%s</span></div>'
                         % (esc(f["k"]), esc(f.get("v") or "-")))
            h.append("</div>")
        h.append("</div>")
        return "".join(h)
    if t == "person":
        return ('<div class="px-person"><div class="px-pav">%s</div>'
                '<div><div class="px-pname">%s</div>'
                '<div class="px-pdept">%s</div></div></div>'
                % (esc(b.get("avatar") or ""), esc(b.get("name") or ""),
                   esc(b.get("dept") or "")))
    if t == "table":
        return '<div class="px-tbwrap">%s</div>' % render_table(b["th"], b["rows"])
    if t == "stats":
        h = ['<div class="px-stats">']
        for it in b["items"]:
            h.append('<div class="px-stat"><div class="px-stat-n">%s</div>'
                     '<div class="px-stat-l">%s</div></div>'
                     % (esc(it["v"]), esc(it["k"])))
        h.append("</div>")
        return "".join(h)
    if t == "h2":
        return '<div class="px-th">%s</div>' % esc(b["text"])
    if t == "total":
        return ('<div class="px-total"><span>%s：</span><b>%s</b></div>'
                % (esc(b["k"]), esc(b["v"])))
    if t == "upload":
        note = b.get("note") or ""
        ext = b.get("ext") or ""
        if note:
            return ('<div class="px-upwrap"><div class="px-uplabel">%s</div>'
                    '<div class="px-upload"><span class="px-upbtn">上传文件</span>'
                    '<span class="px-upnote">%s</span></div>'
                    '<div class="px-upext">%s</div></div>'
                    % (esc(note), esc(b.get("count") or "0 / 1000"), esc(ext)))
        return ('<div class="px-upload"><span class="px-upbtn">上传文件</span>'
                '<span class="px-upnote">%s</span></div>' % esc(ext or note))
    if t == "toolbar":
        h = ['<div class="px-tbar">']
        for f in b.get("filters") or []:
            h.append('<span class="px-tf"><i>%s</i><b>%s</b></span>'
                     % (esc(f["k"]), esc(f.get("v") or "请选择")))
        h.append('<span class="px-sp"></span>')
        for bt in b.get("buttons") or []:
            h.append('<span class="px-btn%s sm">%s</span>'
                     % (" pri" if bt in ("查询", "查 询") else "", esc(bt)))
        h.append("</div>")
        return "".join(h)
    if t == "cols":
        h = ['<div class="px-cols">']
        flex = b.get("flex") or []
        for ci, col in enumerate(b["cols"]):
            fx = flex[ci] if ci < len(flex) else 1
            h.append('<div class="px-col f%d">%s</div>' % (fx, render_blocks(col)))
        h.append("</div>")
        return "".join(h)
    if t == "foot":
        return ('<div class="px-foot">%s</div>'
                % "".join('<span class="px-btn">%s</span>' % esc(a) for a in b["actions"]))
    return '<div class="px-para">%s</div>' % esc(b.get("text") or "")


def render_blocks(blocks):
    """渲染块序列。小标题后面的内容会被收进同一个子卡里。"""
    h = []
    i = 0
    while i < len(blocks):
        b = blocks[i]
        if b["t"] == "sec":
            h.append('<div class="px-card"><div class="px-card-hd">'
                     '<span class="px-sec">%s</span>' % esc(b["title"]))
            if (b.get("head_inline") or "").strip():
                h.append('<span class="px-hx">%s</span>' % esc(b["head_inline"].strip()))
            if (b.get("head_extra") or "").strip():
                h.append('<span class="px-headx">%s</span>' % esc(b["head_extra"].strip()))
            if b.get("actions"):
                h.append('<span class="px-sp"></span>')
                for a in b["actions"]:
                    h.append('<span class="px-btn sm">%s</span>' % esc(a))
            h.append("</div>")
            h.append('<div class="px-card-bd">%s</div>'
                     % render_blocks(b.get("body") or []))
            h.append("</div>")
            i += 1
            continue

        if b["t"] == "sub":
            j = i + 1
            while j < len(blocks) and blocks[j]["t"] not in ("sub", "sec", "cols", "foot"):
                j += 1
            inner = render_blocks(blocks[i + 1:j])
            tags = "".join('<span class="px-tag blue">%s</span>' % esc(x)
                           for x in (b.get("extra") or []) if x)
            h.append('<div class="px-subcard"><div class="px-sub">%s%s</div>%s</div>'
                     % (esc(b["title"]), tags, inner))
            i = j
            continue

        h.append(_render_one(b))
        i += 1
    return "".join(h)


def frame_html(d, shell, as_dialog=None):
    """把一帧快照渲染成 .px 整屏 HTML。"""
    crumb = d.get("crumb") or []
    title = d.get("title") or d.get("name") or ""
    groups = d.get("groups") or []
    all_fields = [f for g in groups for f in (g.get("fields") or [])]
    in_modal = as_dialog if as_dialog is not None else d.get("inModal")

    body = []
    # 面包屑
    if crumb:
        body.append('<div class="px-crumb">%s</div>'
                    % " <i>/</i> ".join(esc(c) for c in crumb))
    if title:
        body.append('<div class="px-h1">%s</div>' % esc(title))
    if d.get("desc"):
        body.append('<div class="px-fhint">%s</div>' % esc(d["desc"]))

    # 页签
    if d.get("tabs"):
        body.append('<div class="px-tabs">%s</div>'
                    % "".join('<div class="px-tab%s">%s</div>'
                              % (" on" if t.get("on") else "", esc(t.get("t")))
                              for t in d["tabs"]))

    details = d.get("details") or []

    # ① 详情页：按坐标还原成有序块（分块 / 表格 / 统计 / 上传 交错，和真实页面同序）
    blocks = [] if in_modal else build_blocks(d)
    is_detail = False
    if blocks:
        big = [t for t in (d.get("tables") or []) if (t.get("rowCount") or 0) > 3]
        # 有 2 个以上分块 = 详情/抽屉页，一律按坐标块渲染。
        # 不能因为「抽到了表单字段」就退回通用表单——结算抽屉就是编辑态表单，
        # 一退回就丢了结算状态单选和上传区。
        is_detail = len(blocks) >= 2 or (not big and not all_fields)
    if is_detail:
        body.append(render_blocks(blocks))
    elif details and not all_fields:
        rows = [[{"text": x.get("k") or ""}, {"text": x.get("v") or ""}]
                for x in details if x.get("k")]
        body.append('<div class="px-card"><div class="px-card-bd">%s</div></div>'
                    % render_table(["字段", "值（实拍）"], rows))

    # ② 表格（详情页的表格已经进块序列了，这里只管列表页）
    if d.get("tables") and not is_detail:
        searchish = [f for f in all_fields if f.get("type") in
                     ("text", "select", "date")][:3]
        if searchish:
            body.append(render_toolbar(searchish, d.get("buttons")))
        row_btns = [b for b in (d.get("buttons") or []) if b.get("link")]
        if not row_btns:
            row_btns = [{"text": "查看"}, {"text": "编辑"}]
        for tb in d["tables"]:
            hd = ('<div class="px-card-hd">%s</div>' % esc(tb["caption"])) if tb.get("caption") else ""
            body.append('<div class="px-card">%s<div class="px-card-bd">%s</div></div>'
                        % (hd, render_table(tb.get("th"), tb.get("rows"), row_btns)))
        tot = d.get("total") or ""
        pager = d.get("pager") or ["1"]
        # 列表页底栏左边常有一个批量动作（结算工作台的「批量结算」），
        # 它既不是筛选按钮也不是行内操作，容易被漏掉
        bulk = [b["text"] for b in (d.get("buttons") or [])
                if b.get("primary") and not b.get("link")
                and (b.get("text") or "").strip() not in BTN_WORDS][:2]
        body.append('<div class="px-lfoot">%s<span class="sp"></span>'
                    '<div class="px-pager"><span>%s</span>%s</div></div>'
                    % ("".join('<span class="px-btn pri">%s</span>' % esc(b) for b in bulk),
                       esc(tot or "共 ? 条"),
                       '<b>‹</b>' + "".join('<b%s>%s</b>' % (' class="on"' if i2 == 0 else "",
                                                             esc(p2)) for i2, p2 in enumerate(pager[:5]))
                       + '<b>›</b>'))
    # ③ 表单（详情页已经按块画过了，别再画一遍通用表单）
    elif all_fields and not is_detail:
        body.append('<div class="px-card"><div class="px-card-bd">%s</div></div>'
                    % render_form(groups, cols=3))
    # ④ 弹窗里的自定义列表
    elif not details and d.get("listItems"):
        items = d["listItems"]
        more = ""
        if len(items) > 8:
            more = "（另有 %d 条未画）" % (len(items) - 8)
            items = items[:8]
        rows = [[{"text": it}] for it in items]
        if more:
            rows.append([{"text": more}])
        body.append('<div class="px-card"><div class="px-card-bd">%s</div></div>'
                    % render_table(["条目（实拍顺序）"], rows))
    elif not details and (d.get("empty") or not d.get("buttons")):
        body.append('<div class="px-card"><div class="px-card-bd">'
                    '<div class="px-empty">%s</div></div></div>'
                    % esc(d.get("empty") or "这一帧主要靠业务说明，页面本身是空的"))

    main = '<div class="px-main">%s</div>' % "".join(body)
    side = render_side(pick_side(shell, d))
    # 长页面：一页一帧，画布跟着内容长高。
    # 默认的 .px 是 1440×≥600 的「视口」，超出的内容被 .px-main 内部滚动吃掉，
    # 静态图里只剩半屏——于是有人把一页拆成好几帧，读者就以为那是几个页面。
    # 判据用正文分块数：分块 ≥4（页头 + 表单 + 表格 + 底栏这种量级）一屏放不下。
    long_page = d.get("full") is True or len(body) >= 4
    root_cls = "px" if (as_dialog or VIEWPORT_MODE or not long_page) else "px full"
    h = ['<div class="%s">' % root_cls, render_top(shell, d),
         '<div class="px-body">', side, main, "</div>"]

    # 弹窗叠加
    if in_modal:
        dlg_title = d.get("dialogTitle") or d.get("name") or "弹窗"
        # 底部按钮：弹窗底栏通常是最后两个（取消 / 确定），前面的是弹窗内部工具按钮
        btns = [b for b in (d.get("buttons") or []) if not b.get("link")]
        if len(btns) > 2:
            btns = btns[-2:]
        if btns:
            ft = "".join('<button class="px-btn%s">%s</button>'
                         % (" pri" if b.get("primary") else "", esc(b["text"]))
                         for b in btns)
        else:
            ft = '<button class="px-btn">取消</button><button class="px-btn pri">确定</button>'
        h.append('<div class="px-mask"><div class="px-modal wide">'
                 '<div class="px-modal-hd">%s<span class="x">✕</span></div>'
                 '<div class="px-modal-bd">%s</div>'
                 '<div class="px-modal-ft">%s</div></div></div>'
                 % (esc(dlg_title), render_dialog_body(d, groups), ft))
    h.append("</div>")
    return "".join(h)


def frame_note(d):
    """每帧都要交代可信边界：这图从哪来、哪里是示例、哪里没画。"""
    bits = []
    if d.get("route"):
        bits.append("实拍路由 %s" % d["route"])
    if d.get("openedBy"):
        bits.append("由「%s」打开" % d["openedBy"])
    if d.get("tab"):
        bits.append("页签「%s」" % d["tab"])
    nf = sum(len(g.get("fields") or []) for g in d.get("groups") or [])
    if nf:
        bits.append("%d 个字段取自真实 DOM" % nf)
    tbs = d.get("tables") or []
    if tbs:
        bits.append("%d 张表 / %d 列取自真实 DOM"
                    % (len(tbs), sum(len(t["th"]) for t in tbs)))
        if any(t.get("rows") for t in tbs):
            bits.append("行数据为实拍首几行，已脱敏")
    if d.get("listItems"):
        bits.append("%d 条列表项取自真实 DOM" % len(d["listItems"]))
    if d.get("shot"):
        bits.append("实拍截图 %s" % d["shot"])
    if not nf and not tbs and not d.get("listItems") and not (d.get("layoutRows") or []):
        bits.append("**这一帧没有从 DOM 抽到结构，需人工补**")
    return "；".join(bits) + "。"


def to_frames(snap, shell, only=None):
    out = []
    for i, d in enumerate(snap.get("frames") or []):
        if d.get("error"):
            print("  ! 跳过 %s：%s" % (d.get("page"), d["error"]), flush=True)
            continue
        if only and d.get("page") not in only:
            continue
        pid = d.get("page") or ("p%d" % (i + 1))
        # 顺序很讲究：列表页也有一堆「字段」（筛选条件），按 details 判会把列表
        # 判成详情页；反过来，详情页里的「操作日志」页签只有表格，会被判成列表。
        # 有没有分页才是列表页的硬标志。
        is_list = bool(d.get("total") or d.get("pager"))
        out.append({
            "id": "P%d" % (i + 1),
            "name": d.get("name") or d.get("title") or pid,
            "state": ("弹窗" if d.get("inModal") else
                      ("二级页" if d.get("openedBy") else
                       ("列表" if is_list else "详情"))),
            "route": d.get("route") or "",
            "note": frame_note(d),
            "from": "%s#%s" % (os.path.basename(snap.get("_path", "snapshot.json")), pid),
            "html": frame_html(d, shell),
        })
    return out


def main():
    ap = argparse.ArgumentParser(description="快照 → px- 原型帧")
    ap.add_argument("--snapshot", required=True, help="snapshot_page.py 的产物")
    ap.add_argument("--data", help="模块数据 JSON，给了就写进 prototype.frames")
    ap.add_argument("--shell", help="外壳配置（顶栏菜单、侧栏菜单），见文件头")
    ap.add_argument("--frame", action="append", help="只处理这些快照页（可多次给）")
    ap.add_argument("--write", action="store_true", help="真的写进 --data")
    ap.add_argument("--keep-existing", action="store_true",
                    help="不覆盖 data 里已有的同名帧")
    ap.add_argument("--dump", action="store_true", help="打印生成的 HTML")
    ap.add_argument("--viewport", action="store_true",
                    help="强制用视口画布（1440×≥600，.px-main 内部滚动）。默认长页面自动用整页画布")
    a = ap.parse_args()
    if a.viewport:
        global VIEWPORT_MODE
        VIEWPORT_MODE = True

    if not os.path.exists(a.snapshot):
        sys.exit("✗ 快照不存在：%s" % a.snapshot)
    snap = json.load(open(a.snapshot, encoding="utf-8"))
    snap["_path"] = a.snapshot
    if not snap.get("frames"):
        sys.exit("✗ 快照里没有帧：%s" % a.snapshot)

    shell = load_shell(a.shell)
    frames = to_frames(snap, shell, a.frame)
    if not frames:
        sys.exit("✗ 没有可用的帧（全部抽取失败）")

    print("从 %s 生成 %d 帧：" % (os.path.basename(a.snapshot), len(frames)))
    for f in frames:
        print("  %-4s %-14s %-8s %s" % (f["id"], f["name"], f["state"],
                                        f["from"]))

    if a.dump:
        for f in frames:
            print("\n" + "=" * 72)
            print("%s · %s" % (f["id"], f["name"]))
            print("=" * 72)
            print(f["html"])

    if not a.data:
        if not a.dump:
            print("\n（没给 --data，只做了转换。加 --data modules/<key>.json --write 才会写进去）")
        return 0

    if not os.path.exists(a.data):
        sys.exit("✗ 模块数据不存在：%s" % a.data)
    d = json.load(open(a.data, encoding="utf-8"))
    proto = d.setdefault("prototype", {})
    proto.setdefault("viewport", "1440x900")

    if a.keep_existing:
        have = {f.get("from") for f in proto.get("frames") or [] if f.get("from")}
        frames = [f for f in frames if f["from"] not in have]
        print("\n保留已有帧，新增 %d 帧" % len(frames))

    old = proto.get("frames") or []
    # 同 from 的替换，其余保留，顺序按快照走
    byfrom = {f["from"]: f for f in frames}
    merged = []
    for f in old:
        src = f.get("from")
        if src and src in byfrom:
            merged.append(byfrom.pop(src))
        elif a.keep_existing:
            merged.append(f)
    merged.extend(byfrom.values())

    # 上面那句「顺序按快照走」以前并不成立：替换是原地替换，旧帧在数组里是什么
    # 顺序，新帧就跟着什么顺序（旧帧存的是 p1,p3,p2，新帧出来还是 p1,p3,p2）。
    # 页签一多，导航按钮就成了 P1/P3/P2/P4，看着像抓错了。这里按快照页号重排。
    def _pnum(f):
        tail = (f.get("from") or "").rsplit("#", 1)
        t = tail[1] if len(tail) == 2 else ""
        return (0, int(t[1:])) if t[:1] == "p" and t[1:].isdigit() else (1, 0)

    merged.sort(key=_pnum)
    proto["frames"] = merged

    # 原型帧有实拍来源，顺手把 note 补一句总量
    if not proto.get("note"):
        proto["note"] = ("本组帧由 snapshot_page.py 从测试环境实拍后生成，"
                         "结构（列、字段、按钮、状态标签）取自真实 DOM；"
                         "行数据为实拍首几行并已脱敏。")

    if not a.write:
        print("\n（预览模式，未写入。加 --write 才落盘）")
        return 0

    json.dump(d, open(a.data, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("\n✓ 已写入 %s，prototype.frames 现有 %d 帧" % (a.data, len(merged)))

    e = S.validate(d)
    if e:
        print("⚠ 写入后契约校验有 %d 处问题（原型之外的字段可能还没填）：" % len(e))
        S.print_errors(e)
    else:
        print("  契约校验通过")
    return 0


if __name__ == "__main__":
    import _compat as _c   # 控制台编码兜底（Windows 默认 cp936 编不出 ✓ ✗）
    _c.init()
    sys.exit(main())
