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

    一列 112px 装「管理后台 V5.0 · 企业内训票 支持对接空中通道C · 第 13 稿」，
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


def build_overview(meta, mods, cur_draft=0, cur_rev=0, doc_sign=None, rev_note=""):
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
    if vers:
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
            pill = ('<span class="ov-cur">本稿 第 %d 稿%s · %s</span>'
                    % (cur_draft, "（修订 %s）" % rm if rm else "",
                       "不新增改动点" if rev_note else "改动 %d 处" % chg_cur))
        # 只重写叙事、不新增改动点的修订（run.json 写 rev_note）不能说「本稿新增 N 处」——
        # 那个 N 是按 data-draft 数出来的，数到的是原稿那一批，会让读者以为这一修订又加了需求。
        if rev_note:
            _tail = "<br>%s" % esc(rev_note)
        else:
            _tail = ("其中本稿新增/改动的 %d 处，其余是前几稿沉淀下来的。" % chg_cur)
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
             '<th style="width:118px">所属迭代</th>'
             '<th>菜单路径</th><th style="width:52px">规则</th>'
             '<th style="width:52px">case</th><th style="width:84px">状态机</th>'
             '<th style="width:92px">本次改动</th>'
             '<th style="width:76px">五源</th><th style="width:48px">缺口</th>'
             '<th style="width:60px">负责人</th></tr></thead><tbody>')
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
        # 数块会得到「报名者退款记录 6 处」，读者以为改了六件事，实际只改了四个编号。
        idx = CHG[i]
        n_all = len(idx)
        n_cur = sum(1 for d in idx.values() if cur_draft and d == cur_draft)
        if not n_all:
            cell = "—"
        elif not cur_draft:
            cell = '<span class="ov-cnt">%d 处</span>' % n_all
        elif n_cur:
            cell = ('<span class="ov-cnt">%d 处<b>本稿</b></span>'
                    '<br><span class="ov-k">累计 %d</span>' % (n_cur, n_all))
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
.ov-foot{margin-top:22px;padding-top:12px;border-top:1px dashed #E6EEF7;
  font-size:10.5px;color:#9AAABA;font-family:var(--mono);word-break:break-all}
@media (max-width:1100px){.ov-nums{grid-template-columns:repeat(3,1fr)}}
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
  html.push('<button class="ni ov' + (CUR < 0 ? " on" : "") + '" data-i="-1">'
    + '<b>总览</b><i>' + ALL.modules.length + ' 个模块 · '
    + ALL.modules.reduce(function(a,m){ return a + (m.rules||[]).length; }, 0) + ' 条规则</i></button>');
  var lastSys = null, n = 0;
  ALL.modules.forEach(function(m, i){
    var mt = m.meta || {};
    if (q && (HIT[mt.key] || 0) === 0) return;
    if (mt.system !== lastSys) { html.push('<div class="ng">' + esc(mt.system || "未分组") + '</div>'); lastSys = mt.system; }
    n++;
    var sub = q ? ('命中 <em>' + HIT[mt.key] + '</em> 条') : ((m.rules||[]).length + ' 条规则');
    html.push('<button class="ni' + (CUR === i ? " on" : "") + '" data-i="' + i + '">'
      + '<b>' + esc(mt.module || "?") + '</b><i>' + esc(mt.key || "") + ' · ' + sub + '</i></button>');
  });
  if (q && n === 0) html.push('<div class="ng">没有匹配的模块</div>');
  box.innerHTML = html.join("");
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
}

function goto(i){
  if (i < 0) { showOverview(); return; }
  CUR = i;
  D = ALL.modules[i];
  bootModule();
  window.scrollTo(0, 0);
  document.querySelectorAll(".pane").forEach(function(p){ p.scrollTop = 0; });
  renderNav(document.getElementById("q").value);
}

document.getElementById("nvList").addEventListener("click", function(e){
  var b = e.target.closest ? e.target.closest(".ni") : null;
  if (!b) return;
  goto(parseInt(b.dataset.i, 10));
});
document.getElementById("q").addEventListener("input", function(){ search(this.value); });
document.getElementById("navToggle").addEventListener("click", function(){
  document.body.classList.toggle("navoff");
  applyLayout();
});
document.addEventListener("keydown", function(e){
  if (e.target && /input|textarea/i.test(e.target.tagName)) return;
  if (e.key === "[" ) { document.getElementById("navToggle").click(); }
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


def make_full_html(meta, mods, overview_html, overview_ai_html):
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

<div class="mn">

<div class="top">'''
    tpl = tpl.replace(body_open, nav_html, 1)

    # 关闭 main
    tpl = tpl.replace('''</div>

<script>''', '''</div>

</div><!-- /mn -->

<script>''', 1)

    # 6. 顶栏加「返回总览」和菜单键；去掉单模块的 r2 说明（全量版另有总览说明）
    tpl = tpl.replace('''    <div class="modes" id="modes">''',
                      '''    <div class="modes" id="modes">''', 1)

    # 7. 注入导航 JS（在 </script> 之前）
    tpl = tpl.replace("</script>\n</body>", NAV_JS + "\n</script>\n</body>", 1)

    # 8. 数据注入
    payload = json.dumps({
        "meta": meta,
        "overview_html": overview_html,
        "overview_ai_html": overview_ai_html,
        "modules": mods,
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


def build_md(meta, mods):
    L = []
    L.append("# %s\n" % meta["title"])
    L.append("> 由 %d 个模块 PRD 合并。引擎 %s，生成于 %s。\n"
             % (len(mods), meta["engine"], meta["generated"]))
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
                    help="允许双签不全也合并（只用于内部评审稿，不要拿去交付）")
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

    # 排序：管理后台 → 主办方端 → 报名者端，组内按 run 顺序
    order = {"管理后台": 0, "主办方端": 1, "报名者端": 2}
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

    # ---- 合并门禁（第二层）：单模块过不代表能合。这里只查一件机器查得动的事——双签 ----
    # 为什么放在合并这一环：单模块自检时可以只有作者自己，但一旦合并成全量 PRD，
    # 它就成了下游（研发/测试）唯一的事实来源，必须有第二个人看过。
    unsigned, sig_info = [], {}
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
            miss = [r for r in ("business", "tech") if not (so.get(r) or {}).get("by")]
            sig_info[k] = {r: (so.get(r) or {}).get("by") for r in ("business", "tech")}
            if miss:
                unsigned.append((k, miss))
        if unsigned and doc_ok:
            print("  ✓ 文档级确认：%s @ %s（%s，覆盖 %d 个模块，不逐模块双签）"
                  % (doc_sign["by"], doc_sign["at"], doc_sign.get("covers") or "全部模块", len(mods)))
            unsigned = []
        if unsigned:
            print("  ! 双签未齐 %d 个模块：" % len(unsigned))
            for k, miss in unsigned[:8]:
                print("      %s 缺 %s" % (k, "、".join("业务" if x == "business" else "技术"
                                                    for x in miss)))
            if a.allow_unsigned:
                print("      → 已用 --allow-unsigned 合并。这份只能内部评审，不要交付。")
            else:
                sys.exit("✗ 双签不齐，拒绝合并。\n"
                         "  签：gate.py sign --role business|tech --by <姓名> --module <key>\n"
                         "  只是内部评审：加 --allow-unsigned（产物会标未签）")
        else:
            print("  ✓ 双签齐全：%d 个模块" % len(mods))

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

    meta = {
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
    ov = build_overview(meta, mods, cur_draft, cur_rev, doc_sign, rev_note=_rev_note)
    ov_ai = build_overview_ai(meta, mods)
    html = make_full_html(meta, mods, ov, ov_ai)

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
        open(mdp, "w", encoding="utf-8").write(build_md(meta, mods))
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

    if bad and not a.strict:
        print("\n  ⚠ 有 %d 个模块契约不合规，已强行合并。交付前必须修。" % bad)
    print("\n下一步：实拍核对")
    print("  %s shot_verify.py --html %s" % (_PY(), out))


if __name__ == "__main__":
    import _compat as _c   # 控制台编码兜底（Windows 默认 cp936 编不出 ✓ ✗）
    _c.init()
    main()
