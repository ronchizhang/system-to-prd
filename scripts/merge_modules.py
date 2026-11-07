#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把多个模块的数据合并成一份全量 PRD。

    # 从工作台的 modules/*.json 合并（推荐：json 是真相）
    python3 merge_modules.py --root ./prd-run --out 全量PRD.html

    # 同事直接丢了几个 html 过来，也能吃（从页内 PRD_DATA 恢复）
    python3 merge_modules.py --from-html a.html b.html c.html --out 全量PRD.html

    # 同时导出给 AI 的两份
    python3 merge_modules.py --root ./prd-run --out 全量PRD.html \
        --md 全量PRD.md --json 全量PRD.json

为什么以 json 为主、html 只是兜底：
HTML 里的数据是渲染前的快照，样式一旦改版就对不齐；json 是同一份真相，
合并时能校验引擎版本、能重排、能生成文本层。html 兜底只是为了兼容「同事只交了 html」。

产出的全量 PRD 不是一个新格式，它复用单模块模板的渲染器，只在外面套一层导航与总览，
所以单模块 PRD 长什么样，全量里就是什么样。
"""

import argparse
import collections
import copy
import datetime as dt
import glob
import hashlib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import schema as S  # noqa: E402

TPL = os.path.join(SKILL, "assets", "module_prd.html")


# ------------------------------------------------------------------ 读取

def extract_prd_data(html):
    m = re.search(r"window\.PRD_DATA = (\{.*?\});\s*\n</script>", html, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(1).replace("<\\/", "</"))
    except json.JSONDecodeError:
        return None


def load_from_root(root):
    """按 run.json 的顺序读模块；没登记的 json 追加在后面并提醒。"""
    runp = os.path.join(root, "run.json")
    order = []
    if os.path.exists(runp):
        run = json.load(open(runp, encoding="utf-8"))
        order = [m["key"] for m in run.get("modules", [])]
    mods, missing = [], []
    seen = set()
    for k in order:
        p = os.path.join(root, "modules", k + ".json")
        if not os.path.exists(p):
            missing.append(k)
            continue
        mods.append((p, json.load(open(p, encoding="utf-8"))))
        seen.add(k)
    for p in sorted(glob.glob(os.path.join(root, "modules", "*.json"))):
        k = os.path.basename(p)[:-5]
        if k not in seen:
            mods.append((p, json.load(open(p, encoding="utf-8"))))
    return mods, missing


def load_from_html(paths):
    out = []
    for p in paths:
        html = open(p, encoding="utf-8").read()
        d = extract_prd_data(html)
        if not d:
            sys.exit("✗ %s 里找不到 window.PRD_DATA，可能不是本引擎生成的" % p)
        out.append((p, d))
    return out, []


# ------------------------------------------------------------------ 总览

def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


CHG_TAG = re.compile(r"<[^>]*\bdata-chg=\"(C\d{1,3})\"[^>]*>")
CHG_TAG_DRAFT = re.compile(r'data-draft="(\d{1,2})"')
# 叙事里的改动块：取编号 + 块内到第一个 </div> 的内容（块内只有 span/b/p，不再嵌 div）
DCHG_BLOCK = re.compile(r'<div class="dchg[^"]*"[^>]*\bdata-chg="(C\d{1,3})"[^>]*>(.*?)</div>', re.S)
DCHG_B = re.compile(r"<b[^>]*>(.*?)</b>", re.S)
DCHG_P = re.compile(r"<p[^>]*>(.*?)</p>", re.S)


def rich(s):
    """总览里的问题描述是作者写的 HTML（<b>/<br>），必须按 HTML 渲染，
    否则页面上会看到一堆 <b> 字面量。只做最小清洗：去 script/style 与事件属性。"""
    s = s or ""
    s = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", s, flags=re.I | re.S)
    s = re.sub(r"\son\w+\s*=\s*\"[^\"]*\"", "", s, flags=re.I)
    s = re.sub(r"\son\w+\s*=\s*'[^']*'", "", s, flags=re.I)
    return s


def plain(s):
    """把作者写的 HTML 压成纯文本：AI 视图里要的是可读命题，不是 <b> 字面量。
    先还原实体再剥标签——合并时数据经过 json.dumps + </ 转义，直接剥会漏。"""
    t = str(s or "")
    t = (t.replace("&lt;", "<").replace("&gt;", ">")
          .replace("&quot;", '"').replace("&#39;", "'").replace("&amp;", "&"))
    t = re.sub(r"<[^>]+>", "", t)
    return re.sub(r"\s+", " ", t).strip()


def change_rows(mod, i):
    """一个模块的改动清单：[{编号, 帧号, 改了什么, 为什么改}]。

    编号来源是 chg_index（叙事 + 原型都扫），细节只从叙事 .dchg 块取：
    原型上只有一条徽标，说不出「为什么改」——那是正文的活。
    """
    mt = mod.get("meta") or {}
    where = {}
    for f in ((mod.get("prototype") or {}).get("frames") or []):
        for code in CHG_TAG.findall(f.get("html") or ""):
            lst = where.setdefault(code, [])
            if f.get("id") not in lst:
                lst.append(f.get("id"))
    detail = {}
    for sec in (mod.get("sections") or []):
        for m in DCHG_BLOCK.finditer(sec.get("html") or ""):
            code = m.group(1)
            if code in detail:
                continue
            body = m.group(2)
            b = DCHG_B.findall(body)
            p = DCHG_P.findall(body)
            detail[code] = {
                "what": plain(b[0]) if b else "",
                "why": plain(p[0]) if p else "",
            }
    out = []
    for code in chg_index(mod):
        d = detail.get(code) or {}
        out.append({
            "code": code,
            "n": int(code[1:]),
            "mod": i,
            "module": mt.get("module", "?"),
            "frames": where.get(code) or [],
            "what": d.get("what") or "",
            "why": d.get("why") or "",
        })
    return out


def _frame_positions(mod, fids):
    """[{帧 id}] → [(下标, 帧 id)]。下标是 showFrame() 要的参数，id 给人看。"""
    order = [f.get("id") for f in ((mod.get("prototype") or {}).get("frames") or [])]
    out = []
    for fid in fids:
        if fid in order:
            out.append((order.index(fid), fid))
    return out


def chg_index(mod):
    """{改动编号: 稿次}。稿次缺失记 0。

    要同时扫叙事和原型：列级改动只写在表头 th 上，正文里根本没有；
    只扫 sections 会漏掉「列表补列」这类改动，总览数字就少算。
    """
    idx = {}
    blobs = [s.get("html") or "" for s in (mod.get("sections") or [])]
    blobs += [f.get("html") or "" for f in ((mod.get("prototype") or {}).get("frames") or [])]
    for b in blobs:
        for tag in CHG_TAG.finditer(b):
            code = tag.group(1)
            dm = CHG_TAG_DRAFT.search(tag.group(0))
            d = int(dm.group(1)) if dm else 0
            if code not in idx:
                idx[code] = d
    return idx


def short_ver(v):
    """总览格子里的版本：短串 + 完整串（当悬停提示）。

    一列 112px 装「管理后台 V5.0 · Demo PayLink 支持对接XPay · 第 13 稿」，
    会被折成 5 行，整张表的行高全被它撑歪——这也是实拍才发现的。
    """
    v = (v or "").strip()
    if not v:
        return "—", ""
    m = re.match(r"^(?:管理后台\s*)?(V\d{1,2}\.\d{1,2})\s*·.*?第\s*(\d{1,2})\s*稿", v)
    if m:
        # 修订号也要露出来，否则「第13稿」这三个字分不出是初版还是修订版。
        # 列只有 104px，写「修订1」会把格子撑成两行，缩成「修1」；完整串进悬停提示。
        rm = re.search(r"（修订 (\d{1,2})）", v)
        tail = "·修%s" % rm.group(1) if rm else ""
        # 短串要能一行放下，实拍量过两次：
        #   「V5.0 · 第13稿」→ 折 2 行；「V5.0·第13稿·修1」→ 还是折（「1」掉到第二行）。
        # 所以去掉「第」「稿」二字里的一个虚词位，写成「V5.0·13稿·修1」。
        # 表格里上下文已经说明这是稿次，少一个「第」不影响读；完整串在 title 悬停里。
        return "%s·%s稿%s" % (m.group(1), m.group(2), tail), v
    return v, v


# ------------------------------------------------- 交叉引用（所有编号都要能点）
# 文档里写「R-DEMO-SELF-17」「T17」「F-03」「自营单据」时，读者得能点过去。
# 三种编号的可见范围不一样，决定了能不能直接定位：
#   规则号 R-XXX-nn → 合并前做过全局消歧，全库唯一，可以直接当锚点
#   迁移号 T17      → 只在模块内唯一（几乎每个模块都有 T1…），跨模块引用必须带上下文
#   事实号 F-03     → 同上，而且渲染成卡片（.fcard[data-id]）不是带 id 的元素
# 所以索引里规则号是全局字典，另两种是 (模块, 编号) 复合键。
XREF_RULE = re.compile(r"\bR-(?:[A-Z0-9]+(?:-[A-Z0-9]+)*-\d{1,3}|\d{1,3})\b")
XREF_PREF = re.compile(r"\bR-[A-Z0-9]+(?:-[A-Z0-9]+)*\b(?!-\d)")
XREF_TRANS = re.compile(r"\bT(\d{1,2})\b")
XREF_FACT = re.compile(r"\bF-(\d{1,3})\b")
XREF_A = re.compile(r"<a\b[^>]*>.*?</a>", re.I | re.S)
XREF_TAG = re.compile(r"(<[^>]+>)")
XREF_PH = "\x01%d\x01"


class Xref:
    """全量文档里的引用索引：编号 → 它属于哪个模块、落在哪个锚点。"""

    def __init__(self, mods):
        self.rule = {}        # R-DEMO-SELF-17 -> mkey
        self.pref = {}        # R-DEMO-SELF -> (mkey, 该前缀第一条规则 id)
        self.facts = set()    # (mkey, F-03)
        self.trans = set()    # (mkey, T17)
        self.mods = {}        # 模块名 -> mkey
        self.self_name = {}   # mkey -> 模块名
        # 简写索引：正文里常写「R-04」「R-FIN-04」这种省略前缀的号（尤其在待确认段）。
        # 这两种只能在**本模块内**解释，所以按 (模块, 号) 建索引，唯一时才敢链。
        self.suffix = {}      # (mkey, 4) -> [R-CBILL-EDIT-04, ...]
        self.tail = {}        # (mkey, ('FIN','04')) -> [R-DEMO-FIN-04, ...]
        for m in mods:
            mt = m.get("meta") or {}
            k = mt.get("key")
            if not k:
                continue
            self.self_name[k] = mt.get("module") or ""
            for r in (m.get("rules") or []):
                rid = r.get("id") or ""
                if not rid:
                    continue
                self.rule[rid] = k
                mm = re.match(r"^(R-[A-Z0-9-]+?)-\d+$", rid)
                if mm:
                    self.pref.setdefault(mm.group(1), (k, rid))
                parts = rid.split("-")
                if len(parts) >= 2 and parts[-1].isdigit():
                    self.suffix.setdefault((k, int(parts[-1])), []).append(rid)
                    self.tail.setdefault((k, tuple(parts[-2:])), []).append(rid)
            for f in (m.get("facts") or []):
                if f.get("id"):
                    self.facts.add((k, f["id"]))
            for t in ((m.get("transitions") or {}).get("rows") or []):
                if t.get("id"):
                    self.trans.add((k, t["id"]))
            if mt.get("module"):
                self.mods[mt["module"]] = k
        # 别名：报告和正文里不会总写全名（写「财务请款」而不是「财务请款管理」）。
        # 只对「去掉『管理』后仍够长」的名字生成，且必须不撞真名、不撞多个模块，
        # 否则「付款账号」会把「付款账号审批」也吃掉。
        alias = collections.defaultdict(set)
        for name, mk in self.mods.items():
            if name.endswith("管理") and len(name) - 2 >= 4:
                a = name[:-2]
                if a not in self.mods:
                    alias[a].add(mk)
        self.alias = {a: next(iter(s)) for a, s in alias.items() if len(s) == 1}
        # 长名优先：不这么做「客户账单」会先吃掉「客户账单认款」的前半截
        self.names = sorted(set(self.mods) | set(self.alias), key=len, reverse=True)

    def target(self, name):
        return self.mods.get(name) or self.alias.get(name)


def _xlink(cls, mk, xt, xa, text, tip=""):
    return ('<a class="xref%s" data-xm="%s" data-xt="%s" data-xa="%s"%s>%s</a>'
            % (cls, esc(mk), xt, esc(xa),
               (' title="%s"' % esc(tip)) if tip else "", text))


def _linkify_text(t, mkey, xr, seen, hold, carry="", whole_only=False):
    """替换一段纯文本（不含标签）里的引用。hold() 把结果存起来换成占位符，
    避免后一轮正则把刚生成的 <a> 属性又当成引用改写一遍。

    carry 是前一个文本节点的尾巴：上下文常被标签切断——报告里写的是
    `<code>R-DEMO-SELF</code> T17、T18`，只看本段的话 T17 前面什么都没有。"""
    if not t or not t.strip():
        return t
    full = carry + t
    off = len(carry)

    # 迁移号必须先做：它要靠前面的 R-XXX 判断属于哪个模块，
    # 而 R-XXX 一旦被替换成占位符，上下文就没了。
    def sub_trans(m):
        tid = "T" + m.group(1)
        pos = off + m.start()
        head = full[max(0, pos - 24):pos]
        mk, pos = None, -1
        # ① 前文提到的模块名（取最靠右的那个）：T 号通常跟在「自营单据（T17」这种括号里
        for name in xr.names:
            p = head.rfind(name)
            if p >= 0 and p + len(name) > pos:
                mk, pos = xr.target(name), p + len(name)
        # ② 紧邻的规则前缀，如「R-DEMO-SELF T17」。必须紧邻：
        #    放宽到整句就会被更早的 R-XXX 带偏（「财务请款（T13）」曾被判给自营单据）。
        tail = XREF_PREF.findall(head[-10:])
        for cand in reversed(tail):
            got = xr.pref.get(cand)
            if got:
                mk = got[0]
                break
        # 两条路都定不了：模块正文里默认归本模块（要真有这个号才链），
        # 报告是跨模块语境，没有默认值，宁可不动
        if not mk:
            mk = mkey
        if not mk or (mk, tid) not in xr.trans:
            return m.group(0)
        return hold(_xlink("", mk, "trans", tid, m.group(0),
                           "%s · 状态迁移 %s" % (xr.self_name.get(mk, ""), tid)))

    t = XREF_TRANS.sub(sub_trans, t)

    def sub_rule(m):
        shown = m.group(0)
        rid = shown
        mk = xr.rule.get(rid)
        if not mk:
            # 完整编号查不到时，才按「本模块内的简写」再试一次：
            #   纯序号 R-04      → 本模块里以 -04 结尾的规则
            #   省略前缀 R-FIN-04 → 本模块里最后两段是 FIN-04 的规则
            # 只有唯一命中才敢链；两条都叫 -04 时宁可不动，也别指错。
            if not mkey:
                return shown
            cand = []
            if re.match(r"^R-\d+$", rid):
                cand = xr.suffix.get((mkey, int(rid[2:]))) or []
            elif rid.count("-") >= 2:
                cand = xr.tail.get((mkey, tuple(rid.split("-")[-2:]))) or []
            if len(cand) != 1:
                return shown
            rid, mk = cand[0], mkey
        # 正文怎么写的就怎么显示（可能只是 R-04），锚点用完整编号
        return hold(_xlink("", mk, "rule", rid, shown,
                           "%s · 规则 %s" % (xr.self_name.get(mk, ""), rid)))

    t = XREF_RULE.sub(sub_rule, t)

    def sub_pref(m):
        pref = m.group(0)
        got = xr.pref.get(pref)
        if not got:
            return pref
        mk, rid = got
        # 只写了前缀（如 R-DEMO-SELF）时定位到该前缀第一条规则，
        # 用户至少能看到这套规则在哪、长什么样；比什么都不给强。
        return hold(_xlink("", mk, "rule", rid, pref,
                           "%s · %s 系列规则" % (xr.self_name.get(mk, ""), pref)))

    t = XREF_PREF.sub(sub_pref, t)

    def sub_fact(m):
        fid = "F-" + m.group(1)
        if (mkey, fid) not in xr.facts:
            return m.group(0)
        return hold(_xlink("", mkey, "fact", fid, m.group(0),
                           "%s · 五源事实 %s" % (xr.self_name.get(mkey, ""), fid)))

    t = XREF_FACT.sub(sub_fact, t)

    # 模块名最后做：它没有边界符，只能整串匹配。
    # seen 用来「每个目标只链第一次」；传 None 表示不限次（表格清单用）。
    own = xr.self_name.get(mkey)
    for name in xr.names:
        if name == own or name not in t:
            continue
        # 表格里只认「整格就是模块名」：菜单路径那列写着「账单和请款 / 客户账单 / 客户账单」，
        # 按子串链会把表格点成一片蓝。
        if whole_only and t.strip() != name:
            continue
        mk = xr.target(name)
        if seen is not None:
            if mk in seen:
                continue
            seen.add(mk)
        t = t.replace(name, hold(_xlink(" mod", mk, "module", mk, name,
                                        "跳到「%s」" % name)), 1)
    return t


def linkify_html(html, mkey, xr, seen=None):
    """把 HTML 里的引用包成可点锚点。只动文本节点，标签与属性原样保留。"""
    if not html or not isinstance(html, str):
        return html
    keep = []

    def hold(s):
        keep.append(s)
        return XREF_PH % (len(keep) - 1)

    # 已有 <a>…</a> 整段保护：嵌 a 是非法 HTML，浏览器会把它拆开
    txt = XREF_A.sub(lambda m: hold(m.group(0)), html)
    out, carry = [], ""
    in_cell = False
    for p in XREF_TAG.split(txt):
        if not p:
            continue
        if p.startswith("<"):
            # 表格单元格里的模块名不限次数：一张表就是一份清单，每一行都该能点，
            # 「只链第一次」在这里会让索引表半数模块点不了。
            low = p.lower()
            if re.match(r"<t[dh]\b", low):
                in_cell = True
            elif re.match(r"</t[dh]>", low):
                in_cell = False
            out.append(p)
            continue
        out.append(_linkify_text(p, mkey, xr, None if in_cell else seen, hold, carry,
                                 whole_only=in_cell))
        # 累计原始文本（不是替换后的）：下一段的推断要用「正文里写过什么」
        carry = (carry + p)[-60:]
    res = "".join(out)
    for i, s in enumerate(keep):
        res = res.replace(XREF_PH % i, s)
    return res


def linkify_mods(mods, xr):
    """给每个模块的正文挂引用。返回副本——JSON 导出要继续保持纯文本，
    否则下游拿到的数据里夹着 <a> 标签，再合并一次就套两层。"""
    out = copy.deepcopy(mods)
    for m in out:
        k = (m.get("meta") or {}).get("key")
        seen = set()      # 每个模块内，同一个目标只链第一次，避免满屏下划线
        for s in (m.get("sections") or []):
            s["html"] = linkify_html(s.get("html"), k, xr, seen)
    return out


# ------------------------------------------------- 核对报告（总览页签用）
# 为什么自带一个极简 Markdown 转换：报告是给人写的（先有 md），页签要的是 HTML。
# skill 不许引第三方库，而这份报告只用得上标题/段落/列表/表格/引用五种语法，
# 引一个 pandoc 或 markdown 库只为了转 150 行，是把部署成本转给使用者。
_MD_CODE = re.compile(r"`([^`]+)`")
_MD_TABLE_SEP = re.compile(r"^:?-{2,}:?$")


def _md_inline(s):
    s = esc(s)
    s = _MD_CODE.sub(lambda m: "<code>%s</code>" % m.group(1), s)
    s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
    return s


def _md_table(lines):
    rows = [[c.strip() for c in ln.strip().strip("|").split("|")] for ln in lines]
    # 第二行是 |:--|:--| 对齐行，不是数据
    if len(rows) > 1 and rows[1] and all(_MD_TABLE_SEP.match(c) for c in rows[1] if c):
        rows.pop(1)
    if not rows:
        return ""
    def tr(cells, tag):
        return "<tr>%s</tr>" % "".join("<%s>%s</%s>" % (tag, _md_inline(c), tag)
                                       for c in cells)
    return ("<table><thead>%s</thead><tbody>%s</tbody></table>"
            % (tr(rows[0], "th"), "".join(tr(r, "td") for r in rows[1:])))


def md_report_html(md):
    """Markdown → 页签里的 HTML 片段。只认这份报告实际用到的语法。"""
    lines = md.splitlines()
    out, i, n = [], 0, len(lines)
    block = re.compile(r"^(#|\||>|[-*] |\d+\. )")
    while i < n:
        s = lines[i].strip()
        if not s:
            i += 1
            continue
        if re.match(r"^-{3,}$", s):
            out.append("<hr>")
            i += 1
            continue
        if s.startswith("# "):
            i += 1                      # 报告标题由页签承担，正文不重复
            continue
        if s.startswith("### "):
            out.append('<h4 class="rep-s2">%s</h4>' % _md_inline(s[4:]))
            i += 1
            continue
        if s.startswith("## "):
            out.append('<h3 class="rep-s">%s</h3>' % _md_inline(s[3:]))
            i += 1
            continue
        if s.startswith(">"):
            buf = []
            while i < n and lines[i].strip().startswith(">"):
                buf.append(lines[i].strip().lstrip(">").strip())
                i += 1
            # 引用块里一行一个 p：报告头部三行（对象/时机/复现）合成一段会糊成一团
            out.append('<div class="rep-note">%s</div>'
                       % "".join("<p>%s</p>" % _md_inline(x) for x in buf if x))
            continue
        if s.startswith("|"):
            buf = []
            while i < n and lines[i].strip().startswith("|"):
                buf.append(lines[i].strip())
                i += 1
            out.append(_md_table(buf))
            continue
        if re.match(r"^[-*] ", s):
            buf = []
            while i < n and re.match(r"^[-*] ", lines[i].strip()):
                buf.append(lines[i].strip()[2:])
                i += 1
            out.append("<ul>%s</ul>"
                       % "".join("<li>%s</li>" % _md_inline(x) for x in buf))
            continue
        if re.match(r"^\d+\. ", s):
            buf = []
            while i < n and re.match(r"^\d+\. ", lines[i].strip()):
                buf.append(re.sub(r"^\d+\.\s*", "", lines[i].strip()))
                i += 1
            out.append("<ol>%s</ol>"
                       % "".join("<li>%s</li>" % _md_inline(x) for x in buf))
            continue
        buf = []
        while i < n and lines[i].strip() and not block.match(lines[i].strip()):
            buf.append(lines[i].strip())
            i += 1
        out.append("<p>%s</p>" % _md_inline(" ".join(buf)))
    return "\n".join(out)


def build_overview(meta, mods, cur_draft=0, cur_rev=0, doc_sign=None, rev_note="",
                   report=None):
    """总览。有跨模块核对报告时，第一屏改成「核对报告 / 模块索引」两个页签。

    为什么要页签而不是把报告接在后面：全量 PRD 一打开就是总览，索引表有 89 行，
    报告要是塞在索引后面，等于没人看得到——而它恰恰是「签名前该先读的那一页」。
    """
    body = _overview_body(meta, mods, cur_draft, cur_rev, doc_sign, rev_note)
    if not report or not report.get("html"):
        return body

    # 切分点：标题之后、说明段之前。找不到就退回数字条之前；两处都没有就不切，
    # 免得把整段总览塞进页签里导致页签空壳（宁可不出页签，也不要出一屏空白）。
    cut = body.find('<p class="ov-lead">')
    if cut < 0:
        cut = body.find('<div class="ov-nums">')
    if cut < 0:
        return body
    head, rest = body[:cut], body[cut:]

    rt = esc(report.get("title") or "跨模块核对")
    rs = report.get("summary") or ""
    tabs = ('<div class="ov-tabs" id="ovTabs">'
            '<button class="ov-tab on" data-ov="rep"><b>%s</b>%s</button>'
            '<button class="ov-tab" data-ov="idx"><b>模块索引</b>'
            '<em>%d 个模块 · 原总览</em></button></div>'
            % (rt, ('<em>%s</em>' % esc(rs)) if rs else "", len(mods)))
    pane_rep = ('<div class="ov-pane" data-ov="rep"><div class="ov-rep">%s</div></div>'
                % report["html"])
    pane_idx = '<div class="ov-pane" data-ov="idx" hidden>%s</div>' % rest
    return head + tabs + pane_rep + pane_idx


def _overview_body(meta, mods, cur_draft=0, cur_rev=0, doc_sign=None, rev_note=""):
    n_rules = sum(len(m.get("rules") or []) for m in mods)
    n_cases = sum(len(r.get("cases") or []) for m in mods
                  for r in (m.get("rules") or []))
    n_q = sum(len(m.get("questions") or []) for m in mods)
    n_open = sum(1 for m in mods for q in (m.get("questions") or [])
                 if q.get("status") != "answered")
    n_dlg = sum(len(m.get("dialogs") or []) for m in mods)
    n_unc = sum(1 for m in mods for x in (m.get("dialogs") or []) if not x.get("covered"))
    # 改动编号是累积的：C1…C23 横跨十几稿。总览只报「累计 20 处」会让读者
    # 以为这一稿改了 20 处，实际本稿只改了 3 处——必须拆成两个数字。
    CHG = [chg_index(m) for m in mods]
    chg_all = sum(len(x) for x in CHG)
    chg_cur = sum(1 for x in CHG for d in x.values() if cur_draft and d == cur_draft)

    h = []
    # 迭代坐标：先讲清这份文档挂在哪条版本线上，再讲有几个模块。
    # 顺序不能反——读者拿到一份迭代 PRD，第一个问题是「这次到底改了什么」
    vers = []
    for m in mods:
        v = (m.get("meta") or {}).get("version")
        if v and v not in vers:
            vers.append(v)
    if vers and not chg_all:
        # 现状 PRD（交付 A）：通篇没有一处 data-chg，就不能挂「迭代坐标 + 粉色改动」——
        # 读者会以为这一版改了什么，实际一个结论都没动。改成中性的版本基线说明。
        h.append('<div class="ov-ver base"><b>版本基线</b>'
                 '<span>%s</span><em>这一版记录系统<b>现在怎么跑</b>，不标改动；'
                 '每一条结论都能追到五源之一（点规则卡上的 F-xx 可跳到核查）。</em></div>'
                 % esc(vers[0] if len(vers) == 1 else "、".join(vers)))
    elif vers:
        pill = ""
        if cur_draft:
            # 修订版要在坐标条上讲明白：这是第 13 稿的修订 1，不是第 14 稿。
            # 两个数字并排出现时最容易被读成「又出新稿了」，所以「修订」二字必须写出来。
            # 修订号是**文档级**的：以 run.json 的 rev 为准。
            # 取第一个模块的 version 会在「只改了第 2 个模块」时停在旧修订上。
            rm = str(cur_rev) if cur_rev else None
            if rm is None:
                for v in vers:
                    mm = re.search(r"（修订 (\d{1,2})）", v)
                    if mm:
                        rm = mm.group(1)
                        break
            # 有 rev_note 的修订不新增改动点，pill 不能写「改动 N 处」（那个 N 是原稿那一批）。
            pill = ('<span class="ov-cur">第 %d 稿%s · %s</span>'
                    % (cur_draft, "（修订 %s）" % rm if rm else "",
                       "不新增改动点" if rev_note else "改动 %d 处" % chg_cur))
        # 只重写叙事、不新增改动点的修订（run.json 写 rev_note）不能说「本稿新增 N 处」——
        # 那个 N 是按 data-draft 数出来的，数到的是原稿那一批，会让读者以为这一修订又加了需求。
        if rev_note:
            _tail = "<br>%s" % esc(rev_note)
        else:
            _tail = "都相对 4.9 基线。"
        h.append('<div class="ov-ver"><b>迭代坐标</b>%s%s'
                 '<em>本次所有需求都挂在这条版本线上，模块逐个交付；'
                 '粉色是本条需求线的全部改动（累计 %d 处），'
                 '%s</em></div>'
                 % ("".join('<span>%s</span>' % esc(v) for v in vers), pill, chg_all, _tail))
    # 文档级确认：小团队只签一次，签在整份文档上，所以要放在最显眼的位置（坐标条下面）。
    # 没签就明说没签——空白会让人以为「没做这件事」，而不是「还没到这一步」。
    _dsg = doc_sign or {}
    if _dsg.get("by") and _dsg.get("at"):
        h.append('<div class="ov-sign ok"><b>本版已确认</b>'
                 '<span class="ov-who">%s</span><span class="ov-at">%s</span>'
                 '<em>%s · 覆盖%s（整份文档一次确认，不按模块签）</em></div>'
                 % (esc(_dsg["by"]), esc(_dsg["at"]),
                    esc(_dsg.get("note") or ""), esc(_dsg.get("covers") or "全部模块")))
    else:
        h.append('<div class="ov-sign"><b>尚未确认</b>'
                 '<em>这一版还没有人整份看过。确认之后，这里会写清是谁、什么时候看的。</em></div>')
    h.append('<h2 class="ov-h">全量 PRD<em>%d 个模块 · %d 条规则 · %d 个 case</em></h2>'
             % (len(mods), n_rules, n_cases))
    # 立项说明：谁 / 什么场景 / 什么问题 / 有哪些方案 / 为什么最优。
    # 这一段回答的是「这个方案该不该做」，后面的模块文档回答「怎么做对」。
    # 缺了它，读者只能看到 53 条规则，看不到为什么值得做。
    if meta.get("project_brief"):
        h.append('<div class="ov-brief">%s</div>' % meta["project_brief"])
    h.append('<p class="ov-lead">这份文件由 <b>%d 个模块 PRD</b> 合并而成，每个模块都是五源核查后的产物'
             '（浏览器渲染 / 后端接口 / 前端代码 / 后端代码 / 用例库 / 业务确认）。'
             '左边点任意模块即可看它的 8 段正文、规则、状态机，以及给 AI 读的条目化版本。</p>'
             % len(mods))

    # 关键数字
    h.append('<div class="ov-nums">')
    for label, val, hint in [
        ("模块", len(mods), "一个三级菜单算一个"),
        ("规则", n_rules, "一条一个命题"),
        ("case", n_cases, "正例 / 反例 / 边界"),
        ("待确认", n_q, "其中未答 %d 条" % n_open),
        ("页面与弹窗", n_dlg, "未覆盖 %d 个" % n_unc),
    ]:
        h.append('<div class="ov-num"><b>%d</b><span>%s</span><u>%s</u></div>'
                 % (val, esc(label), esc(hint)))
    h.append('</div>')

    # 模块索引
    h.append('<h3 class="ov-t">模块索引</h3>')
    h.append('<div class="tw"><table><thead><tr>'
             '<th style="width:158px">模块</th><th style="width:88px">系统</th>'
             '<th style="width:118px">%s</th>'
             '<th>菜单路径</th><th style="width:52px">规则</th>'
             '<th style="width:52px">case</th><th style="width:84px">状态机</th>'
             '<th style="width:92px">本次改动</th>'
             '<th style="width:76px">五源</th><th style="width:48px">缺口</th>'
             '<th style="width:68px">负责人</th></tr></thead><tbody>'
             % ("所属迭代" if chg_all else "版本"))
    for i, m in enumerate(mods):
        mt = m.get("meta") or {}
        tr = m.get("transitions") or {}
        ok = sum(1 for s in (m.get("sources") or []) if s.get("status") == "已核")
        unc = sum(1 for x in (m.get("dialogs") or []) if not x.get("covered"))
        nr = len(m.get("rules") or [])
        nc = sum(len(r.get("cases") or []) for r in (m.get("rules") or []))
        sm = "%d 态 / %d 迁" % (len(tr.get("states") or []), len(tr.get("rows") or []))
        # 本次改动数：按**唯一改动编号**算，不是按标注块数。
        # 同一个改动常在多段里重复标注（第 4 段讲怎么做、第 7 段讲边界），
        # 数块会得到「提现单据记录 6 处」，读者以为改了六件事，实际只改了四个编号。
        idx = CHG[i]
        n_all = len(idx)
        n_cur = sum(1 for d in idx.values() if cur_draft and d == cur_draft)
        if not n_all:
            cell = "—"
        elif not cur_draft:
            cell = '<span class="ov-cnt">%d 处</span>' % n_all
        elif n_cur:
            cell = '<span class="ov-cnt">%d 处</span>' % n_all
        else:
            # 「本稿无」两行跟上面「2 处 本稿 / 累计 6」的字数差太多，列里看着一高一低；
            # 统一成「本稿 0 处」，两张卡的骨架一样，读的人不用重新对位。
            cell = '<span class="ov-k">本稿 0 处</span><br><span class="ov-k">累计 %d</span>' % n_all
        sv_short, sv_full = short_ver(mt.get("version"))
        h.append('<tr><td><b>%s</b><br><span class="ov-k">%s</span></td>'
                 '<td>%s</td><td title="%s">%s</td><td class="ov-menu">%s</td>'
                 '<td>%d</td><td>%d</td><td>%s</td>'
                 '<td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>'
                 % (esc(mt.get("module", "?")), esc(mt.get("key", "")),
                    esc(mt.get("system", "")),
                    esc(sv_full), esc(sv_short),
                    esc(mt.get("menu", "")),
                    nr, nc, esc(sm), cell,
                    ('<span class="ov-ok">%d/6</span>' % ok) if ok >= 4
                    else ('<span class="ov-bad">%d/6</span>' % ok),
                    ('<span class="ov-bad">%d</span>' % unc) if unc else "—",
                    esc(mt.get("owner") or "—")))
    h.append('</tbody></table></div>')

    # 改动总览：迭代版才有。改动原本散在各模块里（帧改动条、段内 dchg、索引表一列数字），
    # 跨五六个模块时读者没有一页能通读「这次到底改了什么」，这一节就是那一页。
    if chg_all:
        rows = []
        for i, m in enumerate(mods):
            rows.extend(change_rows(m, i))
        rows.sort(key=lambda r: (r["n"], r["mod"]))
        n_why = sum(1 for r in rows if r["why"])
        h.append('<h3 class="ov-t">改动总览<em>%d 处，按编号排序'
                 '%s</em></h3>' % (len(rows),
                                   "；%d 处写了为什么改" % n_why if n_why else "；都还没写为什么改"))
        h.append('<div class="tw"><table class="ovchg"><thead><tr>'
                 '<th style="width:56px">编号</th><th style="width:120px">模块</th>'
                 '<th style="width:72px">落在帧</th><th style="width:240px">改了什么</th>'
                 '<th>为什么改</th><th style="width:88px">回原型</th>'
                 '</tr></thead><tbody>')
        for r in rows:
            if r["frames"]:
                fids = r["frames"]
                jump = ''.join(
                    '<a class="ov-jump" data-mod="%d" data-chg="%s" data-fi="%d" title="跳到原型 %s">%s</a>'
                    % (r["mod"], esc(r["code"]), fi, esc(fid), esc(fid))
                    for fi, fid in _frame_positions(mods[r["mod"]], fids))
                frames_txt = '<span class="ov-k">%s</span>' % esc("、".join(fids))
            else:
                jump = '<span class="ov-k">未落图</span>'
                frames_txt = '<span class="ov-k">—</span>'
            h.append('<tr><td class="mono">%s</td><td>%s</td><td>%s</td>'
                     '<td>%s</td><td>%s</td><td>%s</td></tr>'
                     % (esc(r["code"]), esc(r["module"]), frames_txt,
                        rich(r["what"]) or '<span class="ov-k">只有标注，正文没写</span>',
                        rich(r["why"]) or '<span class="ov-k">—</span>', jump))
        h.append('</tbody></table></div>')

    # 全局待确认
    qs = [(m.get("meta") or {}, q) for m in mods for q in (m.get("questions") or [])
          if q.get("status") != "answered"]
    h.append('<h3 class="ov-t">待确认汇总<em>%d 条未定，按模块分组</em></h3>' % len(qs))
    if not qs:
        h.append('<p class="ov-none">全部已裁定。</p>')
    else:
        h.append('<div class="tw"><table><thead><tr>'
                 '<th style="width:70px">编号</th><th style="width:130px">模块</th>'
                 '<th style="width:200px">问题</th><th>为什么拿不准 / 要定什么</th>'
                 '</tr></thead><tbody>')
        for mt, q in qs:
            h.append('<tr><td class="mono">%s</td><td>%s</td><td>%s</td>'
                     '<td>%s<br><span class="ov-ask">要定：%s</span></td></tr>'
                     % (esc(q.get("id")), esc(mt.get("module", "")),
                        rich(q.get("title", "")), rich(q.get("why", "")),
                        rich(q.get("ask", ""))))
        h.append('</tbody></table></div>')

    # 缺口
    gaps = [(m.get("meta") or {}, x) for m in mods
            for x in (m.get("dialogs") or []) if not x.get("covered")]
    if gaps:
        h.append('<h3 class="ov-t">未覆盖的页面与弹窗<em>%d 个</em></h3>' % len(gaps))
        h.append('<div class="tw"><table><thead><tr>'
                 '<th style="width:110px">模块</th><th style="width:80px">类型</th>'
                 '<th style="width:180px">名称</th><th>入口</th></tr></thead><tbody>')
        for mt, x in gaps:
            h.append('<tr><td>%s</td><td>%s</td><td>%s</td><td class="mono">%s</td></tr>'
                     % (esc(mt.get("module", "")), esc(x.get("type", "")),
                        esc(x.get("name", "")), esc(x.get("entry", ""))))
        h.append('</tbody></table></div>')

    h.append('<h3 class="ov-t">怎么读这份文件</h3>')
    h.append('<div class="ov-tips">'
             '<div><b>人读</b>每页固定 8 段：定位 / 业务背景 / 主流程 / 字段字典 / 业务规则 / '
             '状态与流转 / 异常边界 / 待确认。</div>'
             '<div><b>AI 读</b>同一切到条目化：context.yaml 说明为什么这样设计，'
             'rules.jsonl 一行一个命题，api_index 列出接口。</div>'
             '<div><b>并排</b>点任意 <code>R-xxx</code> 编号，右侧自动定位到同一条规则。</div>'
             '<div><b>口径</b>每条规则带证据强度（互证 / 双证 / 单源 / 确立），'
             '单源的不许当结论用。</div></div>')

    h.append('<p class="ov-foot">引擎 %s · 生成于 %s · 模块指纹 %s</p>'
             % (esc(meta["engine"]), esc(meta["generated"]),
                esc(", ".join("%s:%s" % (m["meta"]["key"], meta["fingerprints"][m["meta"]["key"]][:6])
                             for m in mods))))
    return "\n".join(h)


def build_overview_ai(meta, mods):
    """总览的 AI 视图：把全部模块的 context 与规则压成一份索引，AI 一次读完。"""
    out = ['<div class="jsec">project · 全量索引</div>',
           '<div class="jline"><span class="code"><pre class="yaml">'
           + esc("project: %s\nengine: %s\ngenerated: %s\nmodules: %d\nrules: %d\n"
                 % (meta["project"], meta["engine"], meta["generated"],
                    len(mods), sum(len(m.get("rules") or []) for m in mods)))
           + '</pre></span></div>',

           '<div class="jsec">rule_index · 全部规则一行一条</div>']
    for m in mods:
        mt = m.get("meta") or {}
        for r in (m.get("rules") or []):
            out.append('<div class="jline" data-rid="%s"><span class="code">'
                       '<span class="jstr">%s</span> <span class="jcm"># %s · %s · %s</span><br>'
                       '<span class="jk">statement</span>: %s</span></div>'
                       % (esc(r.get("id", "")), esc(r.get("id", "")),
                          esc(mt.get("module", "")), esc(r.get("type", "")),
                          esc(r.get("confidence", "")), esc(plain(r.get("statement", "")))))
    out.append('<div class="jsec">question_index · 未裁定</div>')
    for m in mods:
        mt = m.get("meta") or {}
        for q in (m.get("questions") or []):
            if q.get("status") == "answered":
                continue
            out.append('<div class="jline"><span class="code">'
                       '<span class="jstr">%s</span> <span class="jcm"># %s</span><br>'
                       '<span class="jk">ask</span>: %s</span></div>'
                       % (esc(q.get("id", "")), esc(mt.get("module", "")),
                          esc(plain(q.get("ask", "")))))
    return "\n".join(out)


# ------------------------------------------------------------------ 渲染

SIDENAV_CSS = """
/* ---------------- 全量模式：左侧模块导航 ---------------- */
body.full{display:flex;align-items:stretch}
#sn{width:252px;flex:0 0 252px;height:100vh;position:sticky;top:0;display:flex;
  flex-direction:column;background:#FBFDFF;border-right:1px solid var(--line);z-index:30}
body.navoff #sn{display:none}
/* 展开按钮必须留在侧栏外面：收起按钮在 #sn 里，navoff 一把 #sn 整个 display:none，
   按钮跟着消失，收起后就没有任何可见入口能打开（只剩 [ 快捷键，没人知道）。 */
#navOpen{display:none;position:fixed;left:0;top:50%;transform:translateY(-50%);
  width:26px;height:80px;padding:0;z-index:40;cursor:pointer;
  border:1px solid #CFDEEE;border-left:0;border-radius:0 8px 8px 0;
  background:#F2F7FD;color:#1E6FD9;font-family:inherit;font-size:14px;line-height:1;
  box-shadow:2px 0 12px rgba(11,46,78,.12);
  align-items:center;justify-content:center;transition:background .12s,color .12s}
body.navoff #navOpen{display:flex}
#navOpen:hover{background:#E4EEFA;color:#1558B0}
#sn .nh{padding:13px 16px 11px;border-bottom:1px solid var(--line)}
#sn .nh b{display:block;font-size:13.5px;color:var(--deep);letter-spacing:.2px}
#sn .nh span{font-size:11px;color:var(--sub)}
#sn .nq{padding:9px 12px;border-bottom:1px solid var(--line)}
#sn .nq input{width:100%;height:30px;border:1px solid #DFE8F2;border-radius:7px;
  padding:0 9px;font-size:12px;color:var(--txt);outline:none;background:#fff}
#sn .nq input:focus{border-color:#9CC3EE;box-shadow:0 0 0 3px rgba(30,111,217,.08)}
#sn .nl{flex:1;overflow-y:auto;padding:6px 0 20px}
#sn .ng{padding:9px 15px 4px;font-size:10.5px;font-weight:700;color:#9AAABA;
  letter-spacing:.06em;text-transform:uppercase}
/* 系统 → 一级菜单 → 模块 三级。一级菜单是可折叠的组标题：
   89 个模块平铺时人只能靠搜索找页面，但没有折叠的标题又只是块装饰。 */
#sn .ng2{display:flex;align-items:center;gap:5px;width:100%;text-align:left;
  border:0;background:transparent;padding:10px 14px 4px 12px;cursor:pointer;
  font-family:inherit;font-size:11px;font-weight:700;color:#5C6F84;
  letter-spacing:0;border-top:1px solid #EDF2F8;margin-top:4px}
#sn .ng2:first-child{border-top:0;margin-top:0}
#sn .ng2:hover{color:#1E6FD9}
#sn .ng2 .ga{font-size:9px;color:#9AAABA;display:inline-block;width:8px;
  transition:transform .15s;transform-origin:50% 50%}
#sn .ng2.closed .ga{transform:rotate(-90deg)}
#sn .ng2 .gt{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
#sn .ng2 .gc{font-weight:400;font-size:10px;color:#9AAABA;background:#EEF4FA;
  padding:0 5px;border-radius:8px;line-height:15px;flex:0 0 auto}
#sn .ngb{display:block}
#sn .ngb.hide{display:none}
#sn .ngb .ni{padding-left:25px}
#sn .ni.two b{font-size:12px}
#sn .ni.two i{font-size:10px}
#sn .ni{display:block;width:100%;text-align:left;border:0;background:transparent;
  padding:7px 15px 7px 16px;cursor:pointer;font-family:inherit;
  border-left:2px solid transparent;transition:background .12s}
#sn .ni:hover{background:#F1F7FE}
#sn .ni.on{background:#EAF2FD;border-left-color:var(--blue)}
#sn .ni b{display:block;font-size:12.5px;font-weight:600;color:#243B53;line-height:1.45}
#sn .ni i{display:block;font-style:normal;font-size:10.5px;color:#9AAABA;margin-top:2px}
#sn .ni em{font-style:normal;color:#C77700;font-weight:700}
#sn .ni.on b{color:var(--deep)}
#sn .ni.ov b{color:#1E6FD9}
#sn .nf{padding:8px 14px;border-top:1px solid var(--line);font-size:10.5px;color:#9AAABA;
  display:flex;align-items:center;gap:6px}
#sn .nf u{text-decoration:none;cursor:pointer;color:#5C6F84;padding:1px 6px;border-radius:4px}
#sn .nf u:hover{background:#EEF4FA;color:#1E6FD9}
.mn{flex:1;min-width:0}

/* 总览页：表格列多，放宽正文宽度 */
body.ovview .doc{max-width:1060px}
body.ovview .pane-hd{display:none}
/* 总览只有文字：原型与核查两块不显示，否则会留着上一个模块的图 */
body.ovview .pane.proto,body.ovview .pane.facts{display:none}
body.ovview .pane.human{flex:1 1 100%}

/* 总览页 */
.ov-h{font-size:21px;color:#0B2E4E;margin:2px 0 10px;font-weight:700;letter-spacing:-.2px;
  display:flex;align-items:baseline;gap:10px}
.ov-h em{font-style:normal;font-size:12px;font-weight:500;color:#8FA3B8}
.ov-lead{font-size:13.5px;color:#4A5C70;line-height:1.9;margin:0 0 18px}
.ov-nums{display:grid;grid-template-columns:repeat(5,1fr);gap:9px;margin:0 0 22px}
.ov-num{background:#F7FAFD;border:1px solid #E6EEF7;border-radius:9px;padding:11px 13px}
.ov-num b{display:block;font-size:22px;color:#1E6FD9;line-height:1.1;font-weight:700}
.ov-num span{display:block;font-size:12px;color:#3D5B7A;font-weight:600;margin-top:3px}
.ov-num u{display:block;text-decoration:none;font-size:10.5px;color:#9AAABA;margin-top:1px}
.ov-t{font-size:13px;color:#0B2E4E;margin:24px 0 9px;font-weight:700;
  padding-left:9px;border-left:3px solid #1E6FD9;line-height:1.3;
  display:flex;align-items:baseline;gap:9px}
.ov-t em{font-style:normal;font-size:11px;font-weight:500;color:#9AAABA}
.ov-k{font-size:10px;color:#9AAABA;font-family:var(--mono)}
/* 改动总览：编号是引用锚点，走等宽；「回原型」要能点，但别抢正文的注意力 */
.ovchg td{vertical-align:top;line-height:1.65}
.ov-jump{display:inline-block;margin:0 4px 4px 0;padding:2px 8px;border:1px solid #F3BFD2;
  background:#fff;color:#BE185D;border-radius:9px;font:600 10.5px/1.4 inherit;
  text-decoration:none;cursor:pointer}
.ov-jump:hover{background:#EC407A;border-color:#EC407A;color:#fff}
.ov-menu{font-size:11.5px;color:#5C6F84}
.ov-ok{color:#1B7F45;font-weight:700}
.ov-bad{color:#C62828;font-weight:700}
/* 立项说明：先回答「该不该做」，再回答「怎么做」。 */
.ov-brief{background:#fff;border:1px solid #E3EAF3;border-radius:10px;
  padding:16px 18px 6px;margin:0 0 20px}
.ov-brief h4{font-size:13.5px;color:#0B2E4E;margin:16px 0 8px;font-weight:700;
  padding-left:9px;border-left:3px solid #EC407A;line-height:1.35}
.ov-brief h4:first-child{margin-top:0}
.ov-brief p{font-size:13px;color:#3D4F63;line-height:1.95;margin:0 0 9px}
.ov-brief b{color:#0B2E4E}
.ov-brief table{width:100%;border-collapse:collapse;font-size:12.6px;margin:0 0 10px}
.ov-brief th{background:#F3F8FD;color:#41566E;text-align:left;padding:8px 10px;
  border-bottom:1px solid #E3EAF3;font-size:11.5px;white-space:nowrap}
.ov-brief td{padding:9px 10px;border-bottom:1px solid #F0F4F9;vertical-align:top;line-height:1.75}
.ov-brief tr:last-child td{border-bottom:0}
.ov-brief .qk{color:#7C93AC;font-size:11.5px;width:74px;white-space:nowrap}
.ov-brief .hit{background:#FFF5F8;border:1px solid #F7CBDA;border-left:3px solid #EC407A;
  border-radius:0 7px 7px 0;padding:11px 13px;margin:0 0 12px;font-size:13px;color:#6B2140;line-height:1.9}
.ov-brief .hit b{color:#B01D53}
.ov-brief .ok2{background:#F3FBF6;border:1px solid #CFEADB;border-left:3px solid #1B7F45;
  border-radius:0 7px 7px 0;padding:11px 13px;margin:0 0 12px;font-size:13px;color:#1C4634;line-height:1.9}
.ov-brief .ok2 b{color:#146B39}
.ov-brief .nums3{display:flex;gap:10px;flex-wrap:wrap;margin:0 0 6px}
.ov-brief .nums3 span{background:#F7FAFD;border:1px solid #E6EEF7;border-radius:8px;
  padding:8px 13px;font-size:12.4px;color:#31445A}
.ov-brief .nums3 b{font-size:15px;color:#1E6FD9;margin-right:5px}
/* 迭代坐标：这份全量 PRD 挂在哪个版本线上。做过迭代的文档必须先说清这一点，
   否则读者不知道「哪几条是这次改的」，只能通读全文找 */
.ov-ver{background:#FFF5F8;border:1px solid #F7CBDA;border-left:4px solid #EC407A;
  border-radius:0 9px 9px 0;padding:12px 15px;margin:0 0 18px;
  display:flex;align-items:center;gap:11px;flex-wrap:wrap}
.ov-ver b{font-size:13.5px;color:#B0244F}
.ov-ver span{font-family:var(--mono);font-size:11.5px;background:#fff;color:#B0244F;
  border:1px solid #F3B9CC;border-radius:20px;padding:3px 10px}
.ov-ver em{font-style:normal;font-size:11.5px;color:#8A6470;flex:1 1 240px;min-width:0;line-height:1.7}
/* 本稿 pill：实心，和版本号那几个白底 pill 分开，一眼能认出「这一稿」 */
.ov-ver .ov-cur{background:#EC407A;color:#fff;border-color:#EC407A;font-weight:600}
/* 现状基线（交付 A）：没有改动可标，配色换成中性蓝，别用粉色暗示「改过」 */
.ov-ver.base{background:#F5F9FE;border-color:#DCE8F6;border-left-color:#1E6FD9}
.ov-ver.base b{color:#1B4A7E}
.ov-ver.base span{color:#1B4A7E;border-color:#C9DDF3}
.ov-ver.base em{color:#5A7189}
/* 文档级确认条：签了是绿的，没签是灰的。不写「待补充」——那句话听起来像还有活要干，
   实际只是「还没看」。放坐标条下面，是因为它管的是整份文档，不属于任何模块 */
.ov-sign{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap;margin:-4px 0 14px;
  padding:9px 14px;border-radius:8px;background:#F4F6F8;border:1px solid #E3E9F0;
  border-left:3px solid #B4B2A9}
.ov-sign b{font-size:12.5px;color:#5F5E5A;white-space:nowrap}
.ov-sign em{font-style:normal;font-size:11.5px;color:#7A8794;line-height:1.7;flex:1 1 260px}
.ov-sign.ok{background:#EDF8F1;border-color:#CDE9D8;border-left-color:#1D9E75}
.ov-sign.ok b{color:#0F6E56}
.ov-sign .ov-who{font-size:12.5px;color:#0F6E56;font-weight:600}
.ov-sign .ov-at{font-family:var(--mono);font-size:11px;color:#4E7A63;background:#fff;
  border:1px solid #CDE9D8;border-radius:4px;padding:1px 6px}
.ov-cnt{display:inline-flex;align-items:center;gap:5px;font-size:11px;color:#B0244F;
  background:#FFF0F5;border:1px solid #F3B9CC;border-radius:5px;padding:1px 7px;white-space:nowrap}
.ov-cnt b{font:600 9px/1 -apple-system,"PingFang SC";color:#fff;background:#EC407A;
  border-radius:7px;padding:1px 4px}
.ov-ask{font-size:11px;color:#B45309}
.ov-none{font-size:12px;color:#9AAABA}
.ov-tips{background:#F7FAFD;border:1px solid #E6EEF7;border-radius:9px;padding:12px 15px}
.ov-tips div{font-size:12.5px;color:#4A5C70;line-height:1.95}
.ov-tips b{color:#1B3550;margin-right:5px}
/* 总览页签：核对报告 / 模块索引。报告是「签名前该先读的那一页」，必须一打开就在 */
.ov-tabs{display:flex;gap:2px;margin:14px 0 0;border-bottom:1px solid #E3EAF3}
.ov-tab{appearance:none;border:0;background:transparent;font-family:inherit;cursor:pointer;
  padding:9px 15px 10px;margin-bottom:-1px;border-bottom:2px solid transparent;
  display:flex;align-items:baseline;gap:8px;border-radius:6px 6px 0 0;transition:background .12s}
.ov-tab b{font-size:13.5px;color:#5C6F84;font-weight:600;white-space:nowrap}
.ov-tab em{font-style:normal;font-size:11px;color:#9AAABA}
.ov-tab:hover{background:#F4F8FD}
.ov-tab:hover b{color:#1E6FD9}
.ov-tab.on{border-bottom-color:#1E6FD9}
.ov-tab.on b{color:#0B2E4E}
.ov-pane{padding-top:16px}
.ov-pane[hidden]{display:none}
/* 报告正文：标题层级比正文低一档（页签已经是一级），字号跟文档正文对齐 */
.ov-rep{font-size:13px;color:#3D4F63;line-height:1.9}
.ov-rep .rep-s{font-size:15px;color:#0B2E4E;font-weight:700;margin:26px 0 10px;
  padding-left:10px;border-left:3px solid #1E6FD9;line-height:1.35;display:flex;
  align-items:baseline;gap:9px}
.ov-rep .rep-s:first-child{margin-top:2px}
.ov-rep .rep-s2{font-size:13.5px;color:#1B3550;font-weight:700;margin:20px 0 7px;line-height:1.5}
.ov-rep p{margin:0 0 10px}
.ov-rep ul,.ov-rep ol{margin:0 0 12px;padding-left:21px}
.ov-rep li{margin:0 0 5px}
.ov-rep li b{color:#0B2E4E}
.ov-rep table{width:100%;border-collapse:collapse;font-size:12.4px;margin:0 0 14px;
  table-layout:auto}
.ov-rep th{background:#F3F8FD;color:#41566E;text-align:left;padding:8px 10px;
  border-bottom:1px solid #E3EAF3;font-size:11.5px;white-space:nowrap;vertical-align:top}
.ov-rep td{padding:8px 10px;border-bottom:1px solid #F0F4F9;vertical-align:top;line-height:1.72}
.ov-rep tr:last-child td{border-bottom:0}
.ov-rep code{font-family:var(--mono);font-size:11.5px;background:#F4F7FA;color:#B0244F;
  border:1px solid #E6EEF7;border-radius:4px;padding:0 5px;white-space:nowrap}
/* 表格里 code 必须允许折行：列宽按内容自适应，nowrap 的长编号会把整表顶出正文宽 */
.ov-rep td code{white-space:normal;word-break:break-all}
.ov-rep .rep-note{background:#F5F9FE;border:1px solid #DCE8F6;border-left:3px solid #1E6FD9;
  border-radius:0 8px 8px 0;padding:10px 14px;margin:0 0 16px;font-size:12px;color:#41566E;
  line-height:1.85}
.ov-rep .rep-note p{margin:0}
.ov-rep hr{border:0;border-top:1px dashed #E6EEF7;margin:22px 0}
.ov-rep b{color:#0B2E4E}
.ov-foot{margin-top:22px;padding-top:12px;border-top:1px dashed #E6EEF7;
  font-size:10.5px;color:#9AAABA;font-family:var(--mono);word-break:break-all}
@media (max-width:1100px){.ov-nums{grid-template-columns:repeat(3,1fr)}}
"""

# 入门导读（可选）：整页 iframe，与主文档样式完全隔离。
# 为什么用 iframe 而不是内联：导读往往是自带 CSS 的独立文档，它的 :root 变量、
# body 字号、*{box-sizing} 会直接污染 PRD 的正文（--blue / --line / --bg 这种同名变量
# 含义还不一样），内联过一次，整份 PRD 的配色就变了。
GUIDE_CSS = """
#paneGuide{display:none}
#paneGuide iframe{flex:1;width:100%;height:100%;border:0;display:block;background:#F4F6FB}
body.gdview #paneGuide{display:flex;flex:1 1 100%;min-width:0}
body.gdview .pane:not(#paneGuide){display:none}
body.gdview #r2,body.gdview .modes{display:none}
"""

NAV_JS = r"""
/* ---------------- 全量模式：导航 / 总览 / 搜索 ---------------- */
var CUR = -1;   /* -1 = 总览 */
var HIT = {};   /* key -> 命中的规则数 */

function modText(m){
  var t = [ (m.meta||{}).module||"", (m.meta||{}).menu||"", (m.meta||{}).key||"" ];
  (m.rules||[]).forEach(function(r){ t.push(r.statement||"", r.id||""); });
  (m.dialogs||[]).forEach(function(x){ t.push(x.name||""); });
  (m.questions||[]).forEach(function(q){ t.push(q.title||""); });
  return t.join(" ").toLowerCase();
}

function renderNav(q){
  var box = document.getElementById("nvList");
  if (!box) return;
  var html = [];
  /* 入门导读排最前：第一次打开系统的人先要「这套东西怎么用」，不是「第几条规则」 */
  if (ALL.guide) {
    html.push('<button class="ni gd' + (CUR === -2 ? " on" : "") + '" data-i="-2">'
      + '<b>' + esc(ALL.guide.title || "基础业务说明") + '</b><i>'
      + esc(ALL.guide.note || "先看这一页再看模块") + '</i></button>');
  }
  html.push('<button class="ni ov' + (CUR < 0 && CUR !== -2 ? " on" : "") + '" data-i="-1">'
    + '<b>总览</b><i>' + ALL.modules.length + ' 个模块 · '
    + ALL.modules.reduce(function(a,m){ return a + (m.rules||[]).length; }, 0) + ' 条规则</i></button>');
  var lastSys = null, n = 0, inG = false;
  /* 系统 → 一级菜单 → 模块。一级菜单（menu 的第一段）是可折叠的组标题，
     其余段落成模块按钮的副标题（menu 写三段时第三段并进副标题，不再嵌一层）。
     先按「系统 + 一级菜单」稳定分组再渲染：模块是按 key 排序读进来的，
     同一菜单下的模块会被别的菜单隔开，不分组就会冒出两个「人员管理」。 */
  function closeG(){ if (inG) { html.push('</div>'); inG = false; } }
  var order = [], grp = {};
  ALL.modules.forEach(function(m, i){
    var mt = m.meta || {};
    var k = (mt.system || "") + "\u0001" + (String(mt.menu || "").split(" / ")[0] || "");
    if (!grp[k]) { grp[k] = []; order.push(k); }
    grp[k].push({ m: m, i: i });
  });
  var layered = order.length > 1 || !!(ALL.meta && ALL.meta.nav_group);
  order.forEach(function(k){
    var items = grp[k].filter(function(o){
      return !(q && (HIT[(o.m.meta || {}).key] || 0) === 0);
    });
    if (!items.length) return;
    var m0 = items[0].m.meta || {};
    var lv1 = String(m0.menu || "").split(" / ")[0] || "未分组";
    if (m0.system !== lastSys) {
      closeG();
      html.push('<div class="ng">' + esc(m0.system || "未分组") + '</div>');
      lastSys = m0.system;
    }
    if (layered) {
      var _mn = ((ALL.meta && ALL.meta.menu_notes) || {})[lv1] || "";
      var _gid = "g" + order.indexOf(k);
      html.push('<button class="ng2" data-g="' + _gid + '" aria-expanded="true" title="'
        + esc(_mn || lv1) + '">'
        + '<span class="ga">▾</span><span class="gt">' + esc(lv1) + '</span>'
        + '<span class="gc">' + items.length + '</span></button>');
      html.push('<div class="ngb" data-g="' + _gid + '">');
      inG = true;
    }
    items.forEach(function(o){
      var m = o.m, i = o.i, mt = m.meta || {};
      var lv2 = String(mt.menu || "").split(" / ").slice(1).join(" / ");
      n++;
      var tail = q ? ('命中 <em>' + HIT[mt.key] + '</em> 条') : ((m.rules || []).length + ' 条规则');
      var sub = (lv2 && lv2 !== mt.module) ? (lv2 + ' · ' + tail) : ((mt.key || "") + ' · ' + tail);
      html.push('<button class="ni' + (layered ? " two" : "") + (CUR === i ? " on" : "") + '" data-i="' + i + '">'
        + '<b>' + esc(mt.module || "?") + '</b><i>' + esc(sub) + '</i></button>');
    });
    closeG();
  });
  if (q && n === 0) html.push('<div class="ng">没有匹配的模块</div>');
  box.innerHTML = html.join("");
  /* 导航每次重渲染（点模块、搜关键字）都会把组重建一遍，折叠状态必须重放，
     否则收起一个组之后随手点一下别处，它又自己弹开了。 */
  applyClosed();
}

/* 折叠状态只留在内存里，按 data-g（菜单在 order 里的下标）记，搜索过滤不会串位 */
var CLOSED = {};
function applyClosed(){
  var box = document.getElementById("nvList");
  if (!box) return;
  Array.prototype.forEach.call(box.querySelectorAll(".ng2"), function(g){
    var off = !!CLOSED[g.dataset.g];
    g.classList.toggle("closed", off);
    g.setAttribute("aria-expanded", off ? "false" : "true");
    var b = g.nextElementSibling;
    if (b && b.classList.contains("ngb")) b.classList.toggle("hide", off);
  });
}

function esc(s){
  return String(s == null ? "" : s).replace(/&/g,"&amp;").replace(/</g,"&lt;")
    .replace(/>/g,"&gt;").replace(/"/g,"&quot;");
}

function search(q){
  q = (q || "").trim().toLowerCase();
  HIT = {};
  if (!q) { renderNav(""); return; }
  ALL.modules.forEach(function(m){
    var t = modText(m);
    var c = (m.rules||[]).filter(function(r){
      return (r.statement||"").toLowerCase().indexOf(q) >= 0
          || (r.id||"").toLowerCase().indexOf(q) >= 0;
    }).length;
    var hitName = t.indexOf(q) >= 0;
    HIT[(m.meta||{}).key] = hitName ? Math.max(c, 1) : c;
  });
  renderNav(q);
}

function showOverview(){
  CUR = -1;
  document.body.classList.remove("gdview");
  /* 从「核查/用例/代码」栏回总览时先切回 both：
     那几栏会把叙事 pane 整个 hide，而总览正文就渲染在叙事 pane 里，
     不切回来会看到一片空白（从事实卡点回总览时必现）。 */
  if (typeof goMode === "function") goMode("both");
  document.body.classList.add("ovview");
  document.getElementById("ttl").textContent = ALL.meta.title || "全量 PRD";
  document.getElementById("crumb").textContent = ALL.modules.length + " 个模块";
  document.getElementById("doc").innerHTML = ALL.overview_html || "<p>无总览</p>";
  document.getElementById("aiBody").innerHTML = ALL.overview_ai_html || "";
  document.getElementById("doc").scrollTop = 0;
  window.scrollTo(0, 0);
  document.querySelectorAll(".pane").forEach(function(p){ p.scrollTop = 0; });
  applyLayout();
  renderNav(document.getElementById("q").value);
  ovTabInit();
}

/* 入门导读：整页 iframe。原文放在 text/plain 的 script 里，第一次点开才写进 srcdoc，
   免得每次打开文档都白白解析 8MB 图文（不点这一页就永远不花这个钱）。 */
function showGuide(){
  CUR = -2;
  if (typeof goMode === "function") goMode("both");
  document.body.classList.remove("ovview");
  document.body.classList.add("gdview");
  var g = ALL.guide || {};
  document.getElementById("ttl").textContent = g.title || "基础业务说明";
  document.getElementById("crumb").textContent = g.note || "";
  document.getElementById("doc").innerHTML = "";
  document.getElementById("aiBody").innerHTML = "";
  renderNav(document.getElementById("q").value);
  gdBoot();
  applyLayout();
  window.scrollTo(0, 0);
}
function gdBoot(){
  var f = document.getElementById("gdFrame");
  if (!f || f.getAttribute("data-on")) return;
  var s = document.getElementById("gdSrc");
  if (!s) return;
  var html = s.textContent;
  /* 导读自己的目录是 href="#c8" 这种页内锚点。放进 iframe 后，锚点会按「文档地址」解析：
     srcdoc 继承父页地址 → 一点就把整份 PRD 加载进 iframe。所以统一接管：拦下页内锚点自己做
     scrollIntoView，不依赖浏览器的片段导航。
     （收尾标签用字符串拼接生成——注释里也绝对不能出现那个标签的字面量，
       写在 JS 注释里一样会把整个 script 块截断，整份文档的导航会直接失效） */
  var SB = "<" + "script>", SE = "<" + "/" + "script>";
  var boot = SB + "document.addEventListener('click',function(e){"
    + "var a=e.target.closest?e.target.closest('a'):null;if(!a)return;"
    + "var h=a.getAttribute('href')||'';if(h.charAt(0)!=='#')return;"
    + "var t=document.getElementById(h.slice(1));if(!t)return;"
    + "e.preventDefault();t.scrollIntoView();},true);" + SE;
  var cut = html.lastIndexOf("</body>");
  html = (cut > 0) ? (html.slice(0, cut) + boot + html.slice(cut)) : (html + boot);
  f.setAttribute("data-on", "1");

  /* 加载策略：先用 srcdoc，不用 blob。
     原因是一次真实事故：单文件拷到另一台电脑，点「基础业务说明」是一片空白。
     图并不缺——54 张全是内嵌的 data URI，全文零外链；缺的是 blob: 地址本身：
     部分浏览器（Safari、微信/企微内置浏览器、开了严格策略的环境）拒绝加载
     file:// 页面里由 blob 生成的 iframe，而 createObjectURL 不会抛错，
     所以 try/catch 兜不住，页面就安静地空着。
     srcdoc 不生成任何地址，也不受这类放行策略影响；额外好处是同一个文档里的
     contentDocument 可读，能真的验证「到底加载出来了没有」，而不是假装成功。 */
  var tip = document.getElementById("gdTip");
  var done = false;
  function win(){
    done = true;
    if (tip) tip.hidden = true;
    f.style.display = "";
  }
  function fail(msg){
    if (done) return;
    done = true;
    if (tip) {
      tip.hidden = false;
      tip.innerHTML = msg;
    }
    f.style.display = "none";
  }
  function blobFallback(){
    try {
      f.removeAttribute("srcdoc");
      f.src = URL.createObjectURL(new Blob([html], {type: "text/html;charset=utf-8"}));
      /* blob 的内容跨源，读不到，没法判断成功失败；不误报，交给用户自己看。 */
      if (tip) tip.hidden = true;
      f.style.display = "";
    } catch (e) {
      fail("这段内容在当前浏览器里没能加载。换用 Chrome / Edge 打开，"
         + "或双击同一个压缩包里的《基础业务说明-单页.html》。");
    }
  }
  var t0 = Date.now();
  function probe(){
    if (done) return;
    var d = null;
    try { d = f.contentDocument; } catch (e) {}
    if (d && d.body && d.body.innerHTML.length > 1000) { win(); return; }
    if (Date.now() - t0 < 20000) { setTimeout(probe, 250); return; }
    fail("基础业务说明没能加载出来（8 MB 正文、54 张图都在这个文件里，缺的是浏览器放行）。<br>"
       + "① 换用 Chrome / Edge 打开这个文件；<br>"
       + "② 或用同一个压缩包里的《基础业务说明-单页.html》单独看这一份。");
  }
  try {
    if ("srcdoc" in f) {
      f.srcdoc = html;
      setTimeout(probe, 300);
    } else {
      blobFallback();
    }
  } catch (e) {
    blobFallback();
  }
}

/* 总览页签：核对报告 / 模块索引。页签状态记在 OVTAB，
   从模块切回总览时停在上次看的那一页，不每次都弹回报告。 */
var OVTAB = "rep";
function ovTab(k){
  OVTAB = k || "rep";
  document.querySelectorAll(".ov-tab").forEach(function(b){
    b.classList.toggle("on", b.dataset.ov === OVTAB);
  });
  document.querySelectorAll(".ov-pane").forEach(function(p){
    p.hidden = (p.dataset.ov !== OVTAB);
  });
  var d = document.getElementById("doc");
  if (d) d.scrollTop = 0;
  window.scrollTo(0, 0);
}
function ovTabInit(){
  /* 没有页签（这份文档没配核对报告）就什么都不做，别动 hidden */
  if (!document.getElementById("ovTabs")) return;
  if (OVTAB !== "rep") ovTab(OVTAB);
}

function goto(i){
  if (i === -2) { showGuide(); return; }
  if (i < 0) { showOverview(); return; }
  CUR = i;
  document.body.classList.remove("gdview");
  D = ALL.modules[i];
  bootModule();
  window.scrollTo(0, 0);
  document.querySelectorAll(".pane").forEach(function(p){ p.scrollTop = 0; });
  renderNav(document.getElementById("q").value);
}

document.getElementById("nvList").addEventListener("click", function(e){
  if (!e.target.closest) return;
  /* 一级菜单组标题：折叠 / 展开。标题本身不是页面，点了不该跳走。
     状态记在 CLOSED 里而不是只改 class，重渲染后 applyClosed() 才能还原。 */
  var g = e.target.closest(".ng2");
  if (g) {
    var gid = g.dataset.g;
    CLOSED[gid] = !CLOSED[gid];
    applyClosed();
    return;
  }
  var b = e.target.closest(".ni");
  if (!b) return;
  goto(parseInt(b.dataset.i, 10));
});
document.getElementById("q").addEventListener("input", function(){ search(this.value); });
/* 页签内容每次切总览都重渲染，事件只能挂在 document 上，不能挂在按钮上 */
document.addEventListener("click", function(e){
  var b = e.target.closest ? e.target.closest(".ov-tab") : null;
  if (b) ovTab(b.dataset.ov);
});
/* 改动总览的「回原型」：跨模块 → 先切模块（DOM 整块重建），再切帧，最后交给
   正向那套 wireTo 高亮 + 连线。顺序反了就会在旧节点上操作，什么也没发生。 */
document.addEventListener("click", function(e){
  var b = e.target.closest ? e.target.closest(".ov-jump") : null;
  if (!b) return;
  e.preventDefault();
  e.stopPropagation();
  goto(parseInt(b.dataset.mod, 10));
  showFrame(parseInt(b.dataset.fi, 10));
  wireTo(b.dataset.chg);
});

/* ---------------- 交叉引用跳转 ----------------
   规则卡、状态机迁移表在文档栏，事实卡在核查栏，模块名只跳模块。
   跨模块要先 goto（整块 DOM 会重建），等渲染完再定位，否则拿到的是旧节点。 */
function xrefEl(xt, xa){
  if (xt === "rule")  return document.getElementById("rc-" + xa);
  if (xt === "trans") return document.getElementById("tr-" + xa);
  if (xt === "fact")  return document.querySelector('.fcard[data-id="' + xa + '"]');
  return null;
}
function xrefFlash(xt, xa){
  var el = xrefEl(xt, xa);
  if (!el) return false;
  if (xt === "fact" && el.classList.contains("hide")) {
    /* 事实卡可能被筛选条藏起来了，先回到「全部」再定位 */
    var all = document.querySelector('.fx-bar .chip[data-f="all"]');
    if (all) all.click();
  }
  if (xt === "trans") {
    /* 表格行不能套 flash()：它加的是 .hl 阴影，行上不生效，改用底色高亮 */
    el.classList.add("hl");
    el.scrollIntoView({block: "center", behavior: "smooth"});
    setTimeout(function(){ el.classList.remove("hl"); }, 2200);
  } else {
    flash(el, "center");
  }
  return true;
}
function xrefGo(mk, xt, xa){
  var idx = ALL.modules.findIndex(function(m){ return (m.meta||{}).key === mk; });
  if (idx < 0) return;
  if (xt === "module") { goto(idx); return; }
  var same = (idx === CUR);
  if (!same) goto(idx);
  setTimeout(function(){
    /* 规则/迁移落在文档栏，用 both 而不是 human：human 没有对应的顶栏按钮，
       切过去按钮还停在「原型+文档」，读的人会以为视图没切 */
    goMode(xt === "fact" ? "facts" : "both");
    setTimeout(function(){ xrefFlash(xt, xa); }, same ? 10 : 90);
  }, same ? 0 : 120);
}
document.addEventListener("click", function(e){
  var a = e.target.closest ? e.target.closest("a.xref") : null;
  if (!a) return;                      /* 没有 data-* 属性，不会被模板那边的跳转误接 */
  if (e.preventDefault) e.preventDefault();
  if (e.stopPropagation) e.stopPropagation();
  xrefGo(a.dataset.xm, a.dataset.xt, a.dataset.xa);
});
function navSet(off){
  document.body.classList.toggle("navoff", off);
  var t = document.getElementById("navToggle");
  if (t) t.textContent = off ? "展开 ›" : "收起 ‹";
  applyLayout();
}
document.getElementById("navToggle").addEventListener("click", function(){
  navSet(!document.body.classList.contains("navoff"));
});
var navOpenBtn = document.getElementById("navOpen");
if (navOpenBtn) navOpenBtn.addEventListener("click", function(){
  navSet(false);
  var q = document.getElementById("q");
  if (q) q.focus({ preventScroll: true });
});
document.addEventListener("keydown", function(e){
  if (e.target && /input|textarea/i.test(e.target.tagName)) return;
  if (e.key === "[") { navSet(!document.body.classList.contains("navoff")); }
  if (!ALL.modules.length) return;
  if (e.key === "ArrowDown" || e.key === "j") { e.preventDefault(); goto(Math.min(CUR + 1, ALL.modules.length - 1)); }
  if (e.key === "ArrowUp" || e.key === "k") { e.preventDefault(); goto(CUR <= 0 ? -1 : CUR - 1); }
});

/* 模式按钮与规则跳转只绑一次；切模块走 bootModule，不重复绑定 */
bind();

document.getElementById("ttl").textContent = ALL.meta.title || "全量 PRD";
renderNav("");
showOverview();
"""


# 项目级原型补丁样式（root/proto_extra.css），main 里读进来，make_full_html 注入。
# 帧里用了模板没有的 class 时必须带上，否则帧会整体走形（见 proto_extra.css 头注释）。
PROTO_CSS = ""


def make_full_html(meta, mods, overview_html, overview_ai_html, guide=None):
    tpl = open(TPL, encoding="utf-8").read()

    # 1. 数据起点：单模块 → 多模块容器
    old = "var D = window.PRD_DATA || {};"
    if old not in tpl:
        sys.exit("✗ 模板里找不到数据入口，模板可能被改过：%s" % old)
    new = ("var ALL = window.PRD_DATA || {meta:{},modules:[]};\n"
           "var D = (ALL.modules && ALL.modules[0]) || {};")
    tpl = tpl.replace(old, new, 1)

    # 2. 启动段：包成 bootModule()，去掉一次性启动
    start_old = '''document.getElementById("ttl").textContent = (D.meta && D.meta.module) || "模块 PRD";
document.getElementById("crumb").textContent = (D.meta && D.meta.menu) || "";
document.title = ((D.meta && D.meta.module) || "模块 PRD") + " · PRD";
document.getElementById("doc").innerHTML = head() + renderSections();
renderCode();          // 内含 AI 读（已并入代码栏末尾的折叠块）
document.getElementById("aiBody").innerHTML = renderAI();
renderCases();
renderProto();
markDraft();          // 叙事里的改动块也要按稿次分「本稿 / 前稿」
if (ONLYCUR) document.body.classList.add("onlycur");
renderFacts();
bind();
applyLayout();'''
    if start_old not in tpl:
        sys.exit("✗ 模板启动段与预期不符，无法安全改造")
    start_new = '''function bootModule(){
  document.body.classList.remove("ovview");
  document.getElementById("ttl").textContent = (D.meta && D.meta.module) || "模块 PRD";
  document.getElementById("crumb").textContent = (D.meta && D.meta.menu) || "";
  document.getElementById("doc").innerHTML = head() + renderSections();
  renderCode();                     // 代码栏 + 末尾 AI 读
  document.getElementById("aiBody").innerHTML = renderAI();
  renderCases();                    // 用例栏
  renderProto();
  markDraft();                      // 稿次标记要重打：切模块时叙事与原型都换了一遍
  document.body.classList.toggle("onlycur", ONLYCUR);
  renderFacts();
  applyLayout();
}'''
    tpl = tpl.replace(start_old, start_new, 1)

    # 3. bind() 由 NAV_JS 末尾统一调用一次（切模块不能重复绑定 document 级事件）
    #    启动段已被 bootModule 取代，这里只做兜底检查，防止模板再变回旧形态
    if "bind();\napplyLayout();" in tpl:
        tpl = tpl.replace("bind();\napplyLayout();", "bind();", 1)

    # 4. 注入导航 CSS
    tpl = tpl.replace("</style>", SIDENAV_CSS + "\n</style>", 1)
    if guide:
        tpl = tpl.replace("</style>", GUIDE_CSS + "\n</style>", 1)
    if PROTO_CSS:
        tpl = tpl.replace("</style>", "\n" + PROTO_CSS + "\n</style>", 1)

    # 5. body 包一层：nav + main
    body_open = "<body>\n\n<div class=\"top\">"
    if body_open not in tpl:
        sys.exit("✗ 模板 body 结构与预期不符")
    nav_html = '''<body class="full">

<nav id="sn">
  <div class="nh">
    <b>__TITLE__</b>
    <span>__SUBTITLE__</span>
  </div>
  <div class="nq"><input id="q" placeholder="搜模块或规则，如 字段类型"></div>
  <div class="nl" id="nvList"></div>
  <div class="nf">
    <span>__NMOD__ 个模块</span>
    <span style="margin-left:auto"></span>
    <u id="navToggle" title="快捷键 [">收起 ‹</u>
  </div>
</nav>
<button id="navOpen" title="展开导航（快捷键 [）" aria-label="展开导航">›</button>

<div class="mn">

<div class="top">'''
    tpl = tpl.replace(body_open, nav_html, 1)

    # 关闭 main
    tpl = tpl.replace('''</div>

<script>''', '''</div>

</div><!-- /mn -->

<script>''', 1)

    # 5.5 入门导读：整页 iframe + 原始文档（放在 stage 里，靠 body.gdview 切换显示）
    if guide:
        stage = '<div class="stage" id="stage">'
        if stage not in tpl:
            sys.exit("✗ 模板里找不到 stage 容器，无法挂入门导读")
        tpl = tpl.replace(
            stage,
            stage + '\n\n  <div class="pane guide" id="paneGuide">'
                    '<iframe id="gdFrame" title="%s"></iframe>'
                    '<div id="gdTip" hidden style="flex:1 1 100%%;min-width:0;'
                    'padding:28px 32px;'
                    'font:14px/1.9 -apple-system,BlinkMacSystemFont,\'PingFang SC\',\'Microsoft YaHei\',sans-serif;'
                    'color:#6b5321;background:#fff9e8;border-left:3px solid #e0a800">'
                    '正在加载基础业务说明……</div></div>' % esc(guide["title"]),
            1)
        # 导读原文塞进 text/plain 的 script：浏览器不解析、不改写，JS 取 textContent 直接给 srcdoc。
        # 前提是原文里不能有 </script（有的话脚本会被提前截断），构建时先查一遍。
        if "</script" in guide["html"].lower():
            sys.exit("✗ 入门导读原文里含 </script，无法安全内嵌。先去掉原文的脚本再合并。")

    # 6. 顶栏加「返回总览」和菜单键；去掉单模块的 r2 说明（全量版另有总览说明）
    tpl = tpl.replace('''    <div class="modes" id="modes">''',
                      '''    <div class="modes" id="modes">''', 1)

    # 7. 注入导航 JS（在 </script> 之前）
    tpl = tpl.replace("</script>\n</body>", NAV_JS + "\n</script>\n</body>", 1)

    # 7.5 导读原文（必须排在 NAV_JS 注入之后：否则上面那个 </script>\n</body> 会命中
    #     gdSrc 的收尾标签，把四千行导航脚本塞进 text/plain 里，页面直接白屏）
    if guide:
        # 必须定位到**最后**一个 </body>：脚本文本里也可能出现这个词（比如
        # lastIndexOf("</body>")），按第一个匹配插会把导读原文塞进 JS 字符串里，
        # 整份文档的脚本直接报废。
        _b = tpl.rfind("</body>")
        if _b < 0:
            sys.exit("✗ 模板里找不到 </body>，无法内嵌入门导读")
        tpl = (tpl[:_b]
               + '<script type="text/plain" id="gdSrc">%s</script>\n' % guide["html"]
               + tpl[_b:])
        # 装配自检：这两种事故都真的发生过——注入点命中自己新写的代码，
        # 结果把 8MB 导读塞进 JS 字符串里，页面看着正常、导航全部失效。
        _gi = tpl.find('id="gdSrc"')
        _nav = tpl.rfind("<script>", 0, _gi)
        _navend = tpl.find("</script>", _nav) if _nav >= 0 else -1
        if _nav < 0 or _navend < 0 or _navend > _gi:
            sys.exit("✗ 入门导读注入位置异常：导航脚本被截断了")
        if _gi - _nav > 300000:
            sys.exit("✗ 导航脚本异常膨胀（%d 字节），导读原文被塞进了脚本里" % (_gi - _nav))

    # 8. 数据注入
    payload = json.dumps({
        "meta": meta,
        "overview_html": overview_html,
        "overview_ai_html": overview_ai_html,
        "modules": mods,
        "guide": ({"title": guide["title"], "note": guide.get("note") or ""}
                  if guide else None),
    }, ensure_ascii=False, indent=1).replace("</", "<\\/")
    inject = "<script>\nwindow.PRD_DATA = %s;\n</script>\n" % payload
    i = tpl.find("<script>")
    tpl = tpl[:i] + inject + tpl[i:]

    # 9. 标题
    tpl = tpl.replace("<title>模块 PRD</title>",
                      "<title>%s</title>" % esc(meta["title"]), 1)
    tpl = tpl.replace("__TITLE__", esc(meta["short_title"]))
    tpl = tpl.replace("__SUBTITLE__", esc(meta["subtitle"]))
    tpl = tpl.replace("__NMOD__", str(len(mods)))
    return tpl


# ------------------------------------------------------------------ 文本层

def html_to_text(h):
    """HTML 段落转纯文本。块级标签必须换行，否则剥完标签文字会黏成一串
    （「STEP 1基本信息所属分组…」就是这样来的）。"""
    if not h:
        return ""
    x = h
    x = re.sub(r"<br\s*/?>", "\n", x)
    x = re.sub(r"<li[^>]*>", "\n- ", x)
    x = re.sub(r"<h([1-6])[^>]*>", "\n", x)
    x = re.sub(r"</(p|div|li|tr|table|ul|ol|section|blockquote)>", "\n", x)
    x = re.sub(r"</t[dh]>", " | ", x)
    x = re.sub(r"<t[dh][^>]*>", "", x)
    x = re.sub(r"<[^>]+>", "", x)
    x = (x.replace("&nbsp;", " ").replace("&lt;", "<").replace("&gt;", ">")
          .replace("&amp;", "&").replace("&quot;", '"'))
    x = re.sub(r"[ \t]+", " ", x)
    x = re.sub(r" *\| *\n", " |\n", x)
    x = re.sub(r"\n[ \t]+", "\n", x)
    x = re.sub(r"\n{3,}", "\n\n", x)
    return x.strip()


def md_rules(rules):
    L = []
    for r in rules:
        L.append("**%s**（%s / %s / %s）"
                 % (r["id"], r["type"], r["confidence"], "+".join(r["src"])))
        L.append("")
        L.append("%s" % html_to_text(r["statement"]).replace("\n", " "))
        L.append("")
        if r.get("evidence"):
            L.append("证据：%s" % html_to_text(r["evidence"]).replace("\n", " "))
            L.append("")
        for c in (r.get("cases") or []):
            L.append("- `%s` 给定 %s → 当 %s → 则 %s"
                     % (c["k"], html_to_text(c["g"]).replace("\n", " "),
                        html_to_text(c["w"]).replace("\n", " "),
                        html_to_text(c["t"]).replace("\n", " ")))
        if r.get("note"):
            L.append("")
            L.append("> %s" % html_to_text(r["note"]).replace("\n", " "))
        L.append("")
    return L


def md_sm(tr):
    L = ["状态：%s" % " → ".join(tr.get("states") or []), ""]
    L.append("| ID | 从 | 到 | 触发 | 条件 |")
    L.append("|:--|:--|:--|:--|:--|")
    for row in tr.get("rows") or []:
        L.append("| %s | %s | %s | %s | %s |"
                 % (row["id"], row["from"], row["to"], row["trigger"],
                    html_to_text(row.get("guard", ""))))
    if tr.get("caption"):
        L.append("")
        L.append(html_to_text(tr["caption"]))
    if tr.get("confidence"):
        L.append("")
        L.append("置信度：%s" % html_to_text(tr["confidence"]))
    return L


def build_md(meta, mods, report=None, guide=None):
    L = []
    L.append("# %s\n" % meta["title"])
    L.append("> 由 %d 个模块 PRD 合并。引擎 %s，生成于 %s。\n"
             % (len(mods), meta["engine"], meta["generated"]))
    # 导读是图文文档，不搬进文本层（54 张截图转 Base64 只会把 md 变成垃圾），
    # 但必须留一行指针，否则读 md 的人不知道还有那一页。
    if guide:
        L.append("\n> **入门导读**：HTML 版左侧第一项「%s」%s。"
                 "纯文本层不收图，需要看图请打开 HTML。\n"
                 % (guide["title"],
                    ("（%s）" % guide["note"]) if guide.get("note") else ""))
    # 文本层也要有核对报告：HTML 首页签里有、导出 md 里没有，等于两份产物说的不是一回事
    if report and report.get("md"):
        _r = report["md"]
        _r = re.sub(r"^### ", "#### ", _r, flags=re.M)
        _r = re.sub(r"^## ", "### ", _r, flags=re.M)
        _r = re.sub(r"^# ", "## ", _r, flags=re.M)
        L.append("\n" + _r.strip() + "\n")
        L.append("\n---\n")
    L.append("| 模块 | 系统 | 所属迭代 | 菜单 | 规则 | case | 负责人 |")
    L.append("|:--|:--|:--|:--|--:|--:|:--|")
    for m in mods:
        mt = m.get("meta") or {}
        nr = len(m.get("rules") or [])
        nc = sum(len(r.get("cases") or []) for r in (m.get("rules") or []))
        L.append("| %s | %s | %s | %s | %d | %d | %s |"
                 % (mt.get("module"), mt.get("system"), mt.get("version") or "—",
                    mt.get("menu"), nr, nc, mt.get("owner") or "—"))
    L.append("")

    for m in mods:
        mt = m.get("meta") or {}
        L.append("\n---\n\n## %s · %s\n" % (mt.get("module"), mt.get("system")))
        L.append("`%s` · 路由 `%s` · %s · %s · 负责人 %s\n"
                 % (mt.get("menu"), mt.get("route"), mt.get("env"),
                    mt.get("version"), mt.get("owner") or "—"))

        # 按段号顺序输出；第 5 段出规则、第 6 段出状态机
        secs = sorted(m.get("sections") or [], key=lambda s: s.get("n", 0))
        for s in secs:
            L.append("\n### %d. %s\n" % (s["n"], s["title"]))
            if s.get("rules"):
                L.extend(md_rules(m.get("rules") or []))
            elif s.get("statemachine"):
                L.extend(md_sm(m.get("transitions") or {}))
            else:
                L.append(html_to_text(s.get("html") or "") + "\n")

        L.append("\n### 接口\n")
        L.append("| 方法 | 路径 | 用途 | 鉴权 |")
        L.append("|:--|:--|:--|:--|")
        for x in (m.get("apis") or []):
            L.append("| %s | `%s` | %s | %s |"
                     % (x["method"], x["path"],
                        html_to_text(x["purpose"]), html_to_text(x["auth"])))

        if m.get("questions"):
            L.append("\n### 待确认\n")
            for q in m["questions"]:
                st = "已答" if q.get("status") == "answered" else "未定"
                L.append("- `%s` **%s**（%s）%s"
                         % (q["id"], q["title"], st, html_to_text(q.get("why", ""))))
                if q.get("answer"):
                    L.append("  - 答复：%s" % q["answer"])
                else:
                    L.append("  - 要定：%s" % html_to_text(q.get("ask", "")))
    return "\n".join(L) + "\n"


# ------------------------------------------------------------------ main


def _PY():
    """提示语里该写 python 还是 python3 —— Windows 上没有 python3 这个入口。"""
    try:
        import _compat
        return _compat.python_cmd()
    except Exception:  # noqa: BLE001
        return "python3"


def main():
    ap = argparse.ArgumentParser(description="多模块 → 全量 PRD")
    ap.add_argument("--root", help="工作台目录（读 modules/*.json）")
    ap.add_argument("--from-html", nargs="+", help="直接从单模块 HTML 合并（兜底）")
    ap.add_argument("--out", required=True, help="输出全量 HTML")
    ap.add_argument("--md", help="同时导出 Markdown 文本层")
    ap.add_argument("--json", dest="json_out", help="同时导出合并后的 JSON")
    ap.add_argument("--project", default="", help="项目名（缺省取 run.json）")
    ap.add_argument("--allow-mixed", action="store_true",
                    help="允许引擎版本不一致（默认拒绝：老数据合并会缺字段）")
    ap.add_argument("--strict", action="store_true", help="任一模块契约不过就终止")
    ap.add_argument("--allow-unsigned", action="store_true",
                    help="允许未封板也合并（只用于内部评审稿，不要拿去交付）")
    ap.add_argument("--report", help="跨模块核对报告（.md），挂成总览页的第一个页签；"
                                     "缺省读 run.json 的 report.file")
    ap.add_argument("--guide", help="入门导读（自带的独立 HTML），合成为导航第一项「基础业务说明」；"
                                   "缺省读 run.json 的 guide.file")
    a = ap.parse_args()

    if not a.root and not a.from_html:
        sys.exit("✗ 给 --root 或 --from-html")

    # ---- 命名门禁 ①：文件名不合规就别开始干活，免得渲染完才发现名字错了 ----
    # 产品版本写 V5.0；文档改到第几版写「第N稿」。写成 -V10.1 会被读成产品子版本。
    for flag, path in (("--out", a.out), ("--md", a.md), ("--json", a.json_out)):
        if not path:
            continue
        base = os.path.basename(path)
        if "管理后台" not in base:
            continue          # 临时文件名（full.html）不强制，交付名才管
        if re.search(r"[-_]V\d{1,2}\.\d", base) or not re.search(r"第\s*\d+\s*稿", base):
            sys.exit(
                "✗ %s 文件名不合规：%s\n"
                "  正确写法：管理后台V5.0-<需求名>-第N稿.html\n"
                "  产品版本是 V5.0；文档稿次写「第N稿」，不要写成 -V10.1。" % (flag, base))

    if a.root:
        root = os.path.abspath(os.path.expanduser(a.root))
        pairs, missing = load_from_root(root)
        runp = os.path.join(root, "run.json")
        project = a.project
        brief = ""
        if os.path.exists(runp):
            _run = json.load(open(runp, encoding="utf-8"))
            project = project or _run.get("project", "")
            # 项目级立项说明（五问 / 方案取舍 / 成功标准）：写在 run.json，渲染在总览顶部。
            # 放项目级而不是塞进某个模块的第 1 段——读任何一个模块的人都该先看到它。
            brief = _run.get("project_brief") or ""
            _run_rev = _run.get("rev")
        else:
            _run_rev = None

        # 修订序号对齐：run.json 说第 13 稿修订 1，文件名就不能还叫「第13稿.html」。
        # 两个文件同时躺在目录里时，人分不出哪个是修订前的——这正是命名门禁要防的。
        _out_base = os.path.basename(a.out or "")
        if "管理后台" in _out_base:
            _fn_rev = re.search(r"[-_]修订\s*(\d{1,2})", _out_base)
            _fn_rev = int(_fn_rev.group(1)) if _fn_rev else None
            if _run_rev and _fn_rev != int(_run_rev):
                sys.exit(
                    "✗ 文件名与 run.json 的修订号不一致：\n"
                    "  run.json rev = %s，文件名 %r %s\n"
                    "  正确写法：管理后台V5.0-<需求名>-第13稿-修订%s.html"
                    % (_run_rev, _out_base,
                       "没有修订号" if _fn_rev is None else "写的是修订 %d" % _fn_rev,
                       _run_rev))
            if _fn_rev and not _run_rev:
                sys.exit(
                    "✗ 文件名写着「修订 %d」，run.json 却没有 rev 字段。\n"
                    "  要么补 \"rev\": %d，要么把文件名改回「第N稿」。" % (_fn_rev, _fn_rev))
    else:
        pairs, missing = load_from_html([os.path.expanduser(x) for x in a.from_html])
        project = a.project
        brief = ""

    if not pairs:
        sys.exit("✗ 一个模块都没读到")
    for k in missing:
        print("  ! 登记了但没交数据：%s" % k)

    print("读到 %d 个模块，开始校验…" % len(pairs))
    mods, bad = [], 0
    for p, d in pairs:
        key = (d.get("meta") or {}).get("key") or os.path.basename(p)
        errs = S.validate(d)
        if errs:
            bad += 1
            print("  ✗ %s（%s）：%d 处不合规" % (key, os.path.basename(p), len(errs)))
            for e in errs[:3]:
                print("      %s：%s" % (e["path"] or "(根)", e["msg"]))
            if a.strict:
                continue
        if d.get("engine") != S.ENGINE and not a.allow_mixed:
            sys.exit("✗ %s 的引擎是 %r，当前 %s。\n"
                     "  混版本合并会缺字段。用新版重跑，或加 --allow-mixed 强行合并。"
                     % (key, d.get("engine"), S.ENGINE))
        mods.append(d)

    if not mods:
        sys.exit("✗ 没有可用的模块")

    # 去重：同 key 只留最后一个
    seen, uniq = {}, []
    for m in mods:
        k = m["meta"]["key"]
        if k in seen:
            print("  ! 模块 key 重复，后者覆盖前者：%s" % k)
            uniq[seen[k]] = m
        else:
            seen[k] = len(uniq)
            uniq.append(m)
    mods = uniq

    # 排序：管理后台 → 企业端 → 员工端，组内按 run 顺序
    order = {"管理后台": 0, "企业端": 1, "员工端": 2}
    mods.sort(key=lambda m: order.get((m.get("meta") or {}).get("system"), 9))

    # 跨模块规则编号查重：id 是全量 PRD 里的全局引用锚点，撞号后「R-xx 说了什么」会有歧义
    seen_r, dup_r = {}, []
    for m in mods:
        for r in (m.get("rules") or []):
            rid = r.get("id")
            if rid in seen_r and seen_r[rid] != m["meta"]["key"]:
                dup_r.append((rid, seen_r[rid], m["meta"]["key"]))
            seen_r[rid] = m["meta"]["key"]
    if dup_r:
        print("  ✗ 规则编号跨模块重复 %d 处：" % len(dup_r))
        for rid, ka, kb in dup_r[:8]:
            print("      %s 同时出现在 %s 与 %s" % (rid, ka, kb))
        print("      → 编号是全局引用锚点，撞号后无法唯一定位。改编号段，如 R-OPS-FIELD- / R-OPS-CUST-")
        if a.strict:
            sys.exit("✗ 规则编号重复，--strict 终止")

    # ---- 合并门禁：单模块过不代表能合。这里查机器查得动的那件事——有没有人封过板 ----
    # 为什么放在合并这一环：单模块自检时可以随便试，但一旦合并成全量 PRD，
    # 它就成了下游（研发/测试）唯一的事实来源，得有人对整份认过。
    unsigned, sig_info = [], {}
    stale_info = {}
    doc_sign = {}
    if a.root:
        _rp = os.path.join(root, "run.json")
        if os.path.exists(_rp):
            try:
                _run = json.load(open(_rp, encoding="utf-8"))
                doc_sign = _run.get("signoff") or {}
                if doc_sign and (doc_sign.get("draft") != _run.get("draft")
                                 or (doc_sign.get("rev") or 0) != (_run.get("rev") or 0)):
                    print("  ! 文档级确认记的是第 %s 稿，现为第 %s 稿 —— 改过稿，已失效"
                          % (doc_sign.get("draft"), _run.get("draft")))
                    doc_sign = {}
                elif doc_sign:
                    # 稿次没变不代表内容没变：比签字时记的内容指纹
                    _sd = doc_sign.get("digests") or {}
                    _chg = [_k for _k, _v in _sd.items()
                            if S.content_digest(os.path.join(root, "modules", _k + ".json")) != _v]
                    if _chg:
                        print("  ! 文档级确认之后，这些模块的内容被改过：%s —— 已失效"
                              % "、".join(sorted(_chg)))
                        doc_sign = {}
            except (json.JSONDecodeError, OSError):
                doc_sign = {}
    doc_ok = bool(doc_sign.get("by") and doc_sign.get("at"))
    if a.root:
        for m in mods:
            k = m["meta"]["key"]
            fp = os.path.join(root, "facts", k + ".facts.json")
            so = {}
            if os.path.exists(fp):
                try:
                    so = (json.load(open(fp, encoding="utf-8")).get("signoff") or {})
                except json.JSONDecodeError:
                    so = {}
            _sg = S.signer_of(so)
            # 封板只证明有人认过，不证明认的是现在这一版：比内容指纹，对不上算「封的是旧内容」
            _mh = S.content_digest(os.path.join(root, "modules", k + ".json"))
            _stale = bool(_sg.get("by") and _sg.get("digest") and _mh
                          and _sg["digest"] != _mh)
            sig_info[k] = _sg.get("by")
            if not _sg.get("by"):
                unsigned.append((k, "未封板"))
            elif _stale:
                stale_info[k] = _sg.get("by")
                unsigned.append((k, "封的是旧内容"))
        if unsigned and doc_ok:
            print("  ✓ 文档级确认：%s @ %s（%s，覆盖 %d 个模块，不逐模块封板）"
                  % (doc_sign["by"], doc_sign["at"], doc_sign.get("covers") or "全部模块", len(mods)))
            unsigned = []
        if unsigned:
            print("  ! 还不能合并的模块 %d 个：" % len(unsigned))
            for k, why in unsigned[:8]:
                if k in stale_info:
                    print("      %s 封的是旧内容——封板之后模块被改过（%s）" % (k, stale_info[k]))
                else:
                    print("      %s %s" % (k, why))
            if a.allow_unsigned:
                print("      → 已用 --allow-unsigned 合并。这份只能内部评审，不要交付。")
            else:
                sys.exit("✗ 还有模块没封板，拒绝合并。\n"
                         "  封：gate.py sign --root . --module <key> --by <姓名>\n"
                         "  只是内部评审：加 --allow-unsigned（产物会标未签）")
        else:
            print("  ✓ 已封板：%d 个模块" % len(mods))

    # 本稿稿次：run.json 优先（登记过就一定对），否则取各模块 meta.draft 的最大值。
    # 没有它，总览只能报「累计 N 处」，读者会读成「这一稿改了 N 处」。
    cur_draft, cur_rev = 0, 0
    if a.root:
        _runp = os.path.join(os.path.abspath(os.path.expanduser(a.root)), "run.json")
        if os.path.exists(_runp):
            _run = json.load(open(_runp, encoding="utf-8"))
            cur_draft = int(_run.get("draft") or 0)
            cur_rev = int(_run.get("rev") or 0)
    if not cur_draft:
        cur_draft = max([int((m.get("meta") or {}).get("draft") or 0) for m in mods] or [0])

    # 标题里的稿次标签：稿次是**文档级**属性，只改了一个模块也是整份文档换稿。
    # 所以以 run.json 的 draft/rev 为准；没有 run.json 才退回各模块 version 里的最大值
    # （取第一个模块会出现「本次改的是第 2 个模块，标题却停在前一稿」）。
    _ver_tag = ""
    if cur_draft:
        _ver_tag = " · 第 %d 稿%s" % (cur_draft, "（修订 %d）" % cur_rev if cur_rev else "")
    else:
        _cands = []
        for _m in mods:
            _v = (_m.get("meta") or {}).get("version") or ""
            _vm = re.search(r"第\s*(\d{1,2})\s*稿(（修订\s*(\d{1,2})）)?", _v)
            if _vm:
                _cands.append((int(_vm.group(1)), int(_vm.group(3) or 0)))
        if _cands:
            _d, _r = max(_cands)
            _ver_tag = " · 第 %d 稿%s" % (_d, "（修订 %d）" % _r if _r else "")

    _navcfg = {}
    if a.root:
        _np = os.path.join(os.path.abspath(os.path.expanduser(a.root)), "run.json")
        if os.path.exists(_np):
            try:
                _navcfg = json.load(open(_np, encoding="utf-8"))
            except Exception:
                _navcfg = {}

    meta = {
        "nav_group": bool(_navcfg.get("nav_group")),
        "menu_notes": _navcfg.get("menu_notes") or {},
        "project": project or "全量 PRD",
        "title": "%s · 全量 PRD%s" % (project or "系统", _ver_tag),
        "short_title": project or "全量 PRD",
        "project_brief": brief,
        "subtitle": "%d 个模块 · %d 条规则" % (
            len(mods), sum(len(m.get("rules") or []) for m in mods)),
        "engine": S.ENGINE,
        "generated": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "fingerprints": {m["meta"]["key"]:
                         hashlib.md5(json.dumps(m, ensure_ascii=False, sort_keys=True)
                                     .encode()).hexdigest()
                         for m in mods},
    }

    # 「只重写叙事、不新增改动点」的修订：run.json 用 rev_note 说明这一修订到底改了什么。
    # 没有它，坐标条只能按 data-draft 数出原稿那一批，写成「本稿新增 N 处」，读起来像又加了需求。
    _rev_note = ""
    if a.root:
        _rnp = os.path.join(os.path.abspath(os.path.expanduser(a.root)), "run.json")
        if os.path.exists(_rnp):
            try:
                _rev_note = json.load(open(_rnp, encoding="utf-8")).get("rev_note") or ""
            except Exception:
                _rev_note = ""
    # 跨模块核对报告：签名前第一个该看的东西，做成总览的首页签。
    # 没配就不出页签——不能因为缺一份报告把总览改成两页，那样老文档全变样。
    _rep = None
    if a.root:
        _rcfg = {}
        _rrp = os.path.join(root, "run.json")
        if os.path.exists(_rrp):
            try:
                _rcfg = (json.load(open(_rrp, encoding="utf-8")).get("report") or {})
            except (json.JSONDecodeError, OSError):
                _rcfg = {}
        _rf = a.report or _rcfg.get("file")
        if _rf:
            _rp = _rf if os.path.isabs(_rf) else os.path.join(root, _rf)
            if os.path.exists(_rp):
                _txt = open(_rp, encoding="utf-8").read()
                _rep = {
                    "title": _rcfg.get("title") or "跨模块核对",
                    "summary": _rcfg.get("summary") or "",
                    "html": (md_report_html(_txt) if _rp.lower().endswith((".md", ".markdown"))
                             else _txt),
                    "md": (_txt if _rp.lower().endswith((".md", ".markdown")) else ""),
                }
                print("  ✓ 核对报告 → 总览首页签：%s（%d 节）"
                      % (os.path.basename(_rp), _rep["html"].count("<h3")))
            else:
                print("  ! 登记了核对报告但文件不存在：%s" % _rp)

    # 入门导读：给第一次接触这套系统的人用的图文说明，合成为导航第一项。
    # 整篇塞进 text/plain 的 script，只在用户点开时才解析——不点就零成本。
    _gd = None
    if a.root:
        _gcfg = {}
        _grp = os.path.join(root, "run.json")
        if os.path.exists(_grp):
            try:
                _gcfg = (json.load(open(_grp, encoding="utf-8")).get("guide") or {})
            except (json.JSONDecodeError, OSError):
                _gcfg = {}
        _gf = a.guide or _gcfg.get("file")
        if _gf:
            _gp = _gf if os.path.isabs(_gf) else os.path.join(root, _gf)
            if os.path.exists(_gp):
                _gh = open(_gp, encoding="utf-8").read()
                _gd = {"title": _gcfg.get("title") or "基础业务说明",
                       "note": _gcfg.get("note") or "",
                       "html": _gh}
                print("  ✓ 入门导读 → 导航首项「%s」（%s，%.1f MB）"
                      % (_gd["title"], os.path.basename(_gp),
                         len(_gh.encode()) / 1e6))
            else:
                print("  ! 登记了入门导读但文件不存在：%s" % _gp)

    # 交叉引用：规则号 / 迁移号 / 事实号 / 模块名，一律做成可点锚点。
    # 必须在所有 HTML 生成完之后做——包括核对报告，它是运行时才转成 HTML 的。
    xr = Xref(mods)

    # 项目级原型补丁样式：帧专用 class 全在这里，缺了整帧走形
    global PROTO_CSS
    _pc = os.path.join(root, "proto_extra.css") if root else ""
    if _pc and os.path.exists(_pc):
        PROTO_CSS = open(_pc, encoding="utf-8").read()
        print("  ✓ 项目原型样式 → proto_extra.css（%.1f KB）"
              % (len(PROTO_CSS.encode()) / 1024))

    ov = build_overview(meta, mods, cur_draft, cur_rev, doc_sign, rev_note=_rev_note,
                        report=_rep)
    # 总览没有「当前模块」：mkey=None 时只链模块名，以及前面带 R-XXX 上下文的 T 号
    ov = linkify_html(ov, None, xr, set())
    ov_ai = build_overview_ai(meta, mods)
    # 模块正文挂链接，但只挂进 HTML 的副本；导出 JSON 仍是纯文本
    mods_view = linkify_mods(mods, xr)
    html = make_full_html(meta, mods_view, ov, ov_ai, guide=_gd)
    # 统计在注入前算：注入后整个 payload 的引号被 JSON 转义成 \"，按原样数会全是 0
    _src = ov + "".join(s.get("html") or "" for m in mods_view
                        for s in (m.get("sections") or []))
    print("  ✓ 交叉引用：%d 处（规则 %d / 迁移 %d / 事实 %d / 模块名 %d）"
          % (_src.count('class="xref'),
             _src.count('data-xt="rule"'), _src.count('data-xt="trans"'),
             _src.count('data-xt="fact"'), _src.count('data-xt="module"')))

    out = os.path.abspath(os.path.expanduser(a.out))
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    open(out, "w", encoding="utf-8").write(html)

    # ---- 命名门禁 ②：产物自检。模板文案、总览、某个模块的正文都可能写死 V 稿次 ----
    allowed = {"V5.0"}
    for m in mods:
        mv = re.match(r"^管理后台 (V\d{1,2}\.\d{1,2})",
                      ((m.get("meta") or {}).get("version") or ""))
        if mv:
            allowed.add(mv.group(1))
    badv = sorted({x for x in re.findall(r"V\d{1,2}\.\d{1,2}", html) if x not in allowed})
    if badv:
        sys.exit("✗ 产物里还有把稿次写成版本号的地方：%s\n"
                 "  稿次一律写「第 N 稿」。来源可能是某个模块的正文，或总览里的旧文案。\n"
                 "  文件已写出（%s），但不要拿去交付。" % ("、".join(badv), out))

    n_rules = sum(len(m.get("rules") or []) for m in mods)
    n_cases = sum(len(r.get("cases") or []) for m in mods for r in (m.get("rules") or []))
    n_q = sum(len(m.get("questions") or []) for m in mods)
    n_open = sum(1 for m in mods for q in (m.get("questions") or [])
                 if q.get("status") != "answered")

    print("\n→ %s（%.1f KB）" % (out, len(html.encode()) / 1024))
    print("  %d 个模块 · %d 条规则 · %d 个 case · %d 个待确认（未答 %d）"
          % (len(mods), n_rules, n_cases, n_q, n_open))
    print("  模块：" + "、".join(m["meta"]["module"] for m in mods))

    if a.md:
        mdp = os.path.abspath(os.path.expanduser(a.md))
        open(mdp, "w", encoding="utf-8").write(build_md(meta, mods, report=_rep, guide=_gd))
        print("  Markdown → %s（%.1f KB）" % (mdp, os.path.getsize(mdp) / 1024))
    if a.json_out:
        jp = os.path.abspath(os.path.expanduser(a.json_out))
        json.dump({"meta": meta, "modules": mods}, open(jp, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        print("  JSON     → %s（%.1f KB）" % (jp, os.path.getsize(jp) / 1024))

    # 合并报告：把「谁签的、哪些没签、有没有撞号」落成文件，别只留在终端滚动里
    report = {
        "generated": meta["generated"],
        "engine": S.ENGINE,
        "modules": len(mods),
        "rules": n_rules,
        "cases": n_cases,
        "questions_open": n_open,
        "dup_rule_ids": [{"id": r, "a": x, "b": y} for r, x, y in dup_r],
        "signoff": sig_info,
        "unsigned": [k for k, _ in unsigned],
        "strict": bool(a.strict),
        "allow_unsigned": bool(a.allow_unsigned),
    }
    rp = os.path.join(os.path.dirname(out) or ".", "merge_report.json")
    with open(rp, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)
    print("  合并报告 → %s（未签 %d 个）" % (rp, len(unsigned)))

    # 来源身份证：记下「这一版全量由哪些模块、各自什么指纹构成」。
    # 迭代副本整体复制时它跟着一起走，合回前对一下指纹就知道「我是不是基于这版」，
    # 不用再靠「未改模块」反推——那招在 scope 覆盖全部模块时就失效了。
    if a.root:
        _rdir = os.path.abspath(os.path.expanduser(a.root))
        _digs = {}
        for _m in mods:
            _k = (_m.get("meta") or {}).get("key")
            if not _k:
                continue
            _mp = os.path.join(_rdir, "modules", _k + ".json")
            if os.path.isfile(_mp):
                with open(_mp, "rb") as _f:
                    _digs[_k] = hashlib.sha256(_f.read()).hexdigest()
        _op = os.path.join(_rdir, "origin.json")
        with open(_op, "w", encoding="utf-8") as _f:
            json.dump({
                "engine": S.ENGINE,
                "built_at": meta["generated"],
                "draft": cur_draft,
                "rev": cur_rev,
                "state": "built",
                "modules": _digs,
            }, _f, ensure_ascii=False, indent=1)
        print("  来源身份证 → %s（第 %d 稿 · %d 个模块）" % (_op, cur_draft, len(_digs)))

    if bad and not a.strict:
        print("\n  ⚠ 有 %d 个模块契约不合规，已强行合并。交付前必须修。" % bad)
    print("\n下一步：实拍核对")
    print("  %s shot_verify.py --html %s" % (_PY(), out))


if __name__ == "__main__":
    import _compat as _c   # 控制台编码兜底（Windows 默认 cp936 编不出 ✓ ✗）
    _c.init()
    main()
