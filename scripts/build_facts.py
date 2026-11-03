#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把事实台账（JSON）生成一页可筛选的核查清单，供用户逐条确认。

    python3 build_facts.py --data facts.json --out 事实清单.html
    python3 build_facts.py --data facts.json --out x.html --md x.md

facts.json 结构（数组，字段见 references/five-sources.md 第三节）：

[
  {"id":"F-01","cls":"fix","sev":"P0","area":"字段类型",
   "title":"字段类型是 8 种，不是 9 种",
   "old":"PRD 写：9 种…","new":"字典只有 8 个 key…",
   "src":["api","be","fe","ima","ui"],"proof":"enum/listEnums → fieldTextType",
   "note":"单选/多选是子值","ask":"确认按 8 种改写？"}
]

cls 六选一：fix 需改 / add 缺失 / conflict 冲突 / risk 风险 / ask 待确认 / ok 一致
sev 三档：P0 阻塞写文档 / P1 影响准确性 / P2 补充即可
"""

import argparse
import json
import os
import sys

CLS_META = {
    "fix":      ("需改",   "#C62828", "PRD 现有写法与事实不符，必须改"),
    "add":      ("缺失",   "#1565C0", "页面/代码/用例里有，PRD 完全没有"),
    "conflict": ("冲突",   "#B45309", "两个来源说法不一致，需你裁定"),
    "risk":     ("风险",   "#6B46C1", "实现层面的缺陷或缺口，不一定是文档问题"),
    "ask":      ("待确认", "#0F766E", "我判断不了，必须你回答"),
    "ok":       ("一致",   "#1B7F45", "已核对，与现状一致"),
}
SEV_META = {"P0": "#C62828", "P1": "#B45309", "P2": "#5C6F84"}
SRC_META = {
    "ui":  ("浏览器渲染", "渲染", "#1E6FD9"),
    "api": ("后端接口",  "接口", "#0F766E"),
    "fe":  ("前端代码",  "前端码", "#6B46C1"),
    "be":  ("后端代码",  "后端码", "#B45309"),
    "ima": ("用例库",  "用例", "#C62828"),
    "biz": ("业务确认",  "业务", "#2E7D32"),
}

CSS = """
*{box-sizing:border-box;margin:0;padding:0}
:root{--ink:#0B2E4E;--ink2:#1B3550;--sub:#5C6F84;--line:#E3EAF3;--bg:#F6F9FC;
  --blue:#1E6FD9;--mono:"SFMono-Regular",Consolas,monospace}
body{font:14px/1.75 -apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif;
  color:var(--ink2);background:var(--bg);-webkit-font-smoothing:antialiased}
.wrap{max-width:1180px;margin:0 auto;padding:0 26px 90px}
header{background:linear-gradient(135deg,#0B2E4E 0%,#123D66 100%);color:#fff;padding:30px 0 26px}
header .wrap{padding-bottom:0}
.eyebrow{font-size:11px;letter-spacing:.14em;color:#7FB0E8;font-weight:700;text-transform:uppercase}
h1{font-size:26px;font-weight:800;letter-spacing:-.3px;margin:8px 0 10px;line-height:1.3}
.lead{font-size:13.5px;color:#B7CCE2;max-width:820px;line-height:1.8}
.hstat{display:flex;gap:26px;margin-top:20px;padding-top:18px;
  border-top:1px solid rgba(255,255,255,.14);flex-wrap:wrap}
.hstat div{display:flex;flex-direction:column;gap:2px}
.hstat b{font-size:22px;font-weight:800;letter-spacing:-.5px}
.hstat span{font-size:11px;color:#8AA6C2}
.hstat .p0 b{color:#FF8A8A}.hstat .cf b{color:#FFC46B}.hstat .ms b{color:#7FC7F0}
section{margin-top:26px}
h2{font-size:15px;font-weight:800;color:var(--ink);margin-bottom:12px;display:flex;align-items:center;gap:9px}
h2::before{content:"";width:3px;height:15px;background:var(--blue);border-radius:2px}
h2 em{font-style:normal;font-size:11.5px;font-weight:500;color:var(--sub)}
.srcs{background:#fff;border:1px solid var(--line);border-radius:11px;overflow:hidden}
.srcrow{display:grid;grid-template-columns:104px 74px 1fr;gap:14px;padding:11px 16px;
  border-top:1px solid #F0F5FA;align-items:start;font-size:12px}
.srcrow:first-child{border-top:0;background:#F8FBFE;font-weight:700;color:var(--ink);
  font-size:11px;letter-spacing:.03em}
.srcrow .k{font-weight:700;color:var(--ink);display:flex;align-items:center;gap:6px}
.srcrow .k i{width:6px;height:6px;border-radius:50%;flex:0 0 6px}
.srcrow .st{font-size:10.5px;font-weight:700;padding:1px 7px;border-radius:4px;
  background:#EAF7EE;color:#1B7F45;text-align:center;height:19px;line-height:17px}
.srcrow .st.part{background:#FFF6E8;color:#B45309}
.srcrow .d{color:var(--sub);line-height:1.7}
.ov{display:grid;grid-template-columns:repeat(5,1fr);gap:10px}
.ovc{background:#fff;border:1px solid var(--line);border-radius:10px;padding:13px 14px;
  cursor:pointer;transition:.18s;border-top:3px solid transparent}
.ovc:hover{box-shadow:0 4px 14px rgba(11,46,78,.09);transform:translateY(-1px)}
.ovc b{display:block;font-size:24px;font-weight:800;letter-spacing:-.6px;line-height:1.2}
.ovc span{font-size:11.5px;color:var(--sub);font-weight:600}
.ovc em{font-style:normal;display:block;font-size:10.5px;color:#9AAABA;margin-top:3px;line-height:1.5}
.bar{display:flex;gap:7px;flex-wrap:wrap;align-items:center;margin:22px 0 14px;
  position:sticky;top:0;z-index:20;background:var(--bg);padding:10px 0;border-bottom:1px solid var(--line)}
.bar .t{font-size:11.5px;color:var(--sub);font-weight:700;margin-right:3px}
.chip{font-size:11.5px;padding:4px 11px;border-radius:14px;border:1px solid var(--line);
  background:#fff;cursor:pointer;font-weight:600;color:var(--sub);transition:.15s;user-select:none}
.chip:hover{border-color:#B9CFE6;color:var(--ink)}
.chip.on{background:var(--ink);color:#fff;border-color:var(--ink)}
.chip.on.s0{background:#C62828;border-color:#C62828}
.sp{flex:1}.cnt{font-size:11.5px;color:#9AAABA}
.gt{font-size:12px;font-weight:800;color:#3D5B7A;letter-spacing:.05em;margin:24px 0 10px;
  padding-bottom:7px;border-bottom:1px dashed #DCE7F2;display:flex;align-items:center;gap:8px}
.gt u{text-decoration:none;font-size:10.5px;font-weight:600;color:#8FA3B8;
  background:#EEF4FA;padding:1px 8px;border-radius:4px;margin-left:7px}
.gt .gdesc{font-size:11px;font-weight:500;color:#9AAABA;margin-left:2px}
.card{background:#fff;border:1px solid var(--line);border-radius:11px;margin-bottom:11px;
  overflow:hidden;border-left:3px solid #ccc;transition:.16s}
.card:hover{box-shadow:0 3px 14px rgba(11,46,78,.07)}
.card.hide{display:none}
.ch{padding:12px 16px 10px;display:flex;gap:9px;align-items:flex-start;flex-wrap:wrap;
  border-bottom:1px solid #F4F8FC}
.id{font-family:var(--mono);font-size:11px;font-weight:700;padding:2px 7px;border-radius:4px;
  background:#F1F5FA;color:#5C6F84;flex:0 0 auto;cursor:pointer}
.ttl{font-size:14px;font-weight:700;color:var(--ink);flex:1;min-width:200px;line-height:1.55}
.area{font-size:10px;font-weight:600;padding:1.5px 7px;border-radius:4px;flex:0 0 auto;
  background:#F1F5FA;color:#7C8FA5;height:19px;line-height:16px}
.tag{font-size:10px;font-weight:700;padding:1.5px 7px;border-radius:4px;flex:0 0 auto;height:19px;line-height:16px}
.srclist{display:flex;gap:4px;flex-wrap:wrap;margin-left:auto}
.srclist i{font-style:normal;font-size:10px;font-weight:700;padding:1px 7px;border-radius:3px;
  color:#fff;height:17px;line-height:15px;opacity:.92}
.cb{padding:12px 16px 13px;font-size:12.5px;line-height:1.8}
.row{display:flex;gap:9px;margin-bottom:8px;align-items:flex-start}
.row:last-child{margin-bottom:0}
.rk{flex:0 0 58px;font-size:10.5px;font-weight:700;padding-top:2px}
.rk.o{color:#A0AEC0}.rk.n{color:#0F766E}.rk.p{color:#7C6CB0}.rk.q{color:#B45309}
.rv{flex:1;min-width:0}
.rv.o{color:#8C9AAB}
.new{background:#F3FBF7;border-left:2px solid #7DCBA4;padding:8px 11px;border-radius:0 6px 6px 0;
  white-space:pre-wrap;font-size:12.5px;line-height:1.85}
.old{background:#FBFBFD;border-left:2px solid #DDE4EC;padding:8px 11px;border-radius:0 6px 6px 0;color:#8C9AAB}
.note{font-size:11.5px;color:#7A6350;background:#FFFCF5;border-left:2px solid #E9C77B;
  padding:8px 11px;border-radius:0 6px 6px 0;line-height:1.75}
.ask{font-size:12px;color:#0F766E;background:#EDF8F6;border-left:2px solid #4FB3A4;
  padding:8px 11px;border-radius:0 6px 6px 0;font-weight:600;line-height:1.7}
.ev{margin:11px 0 0;border-top:1px dashed #E6EEF7;padding:9px 0 1px}
.ev summary{cursor:pointer;font-size:11px;color:#8FA3B8;font-weight:600;outline:none;list-style:none}
.ev summary::-webkit-details-marker{display:none}
.ev summary::before{content:"▸ ";font-size:9px}
.ev[open] summary::before{content:"▾ "}
.ev p{margin-top:7px;font-family:var(--mono);font-size:11px;line-height:1.75;color:#5C6F84;
  background:#FAFCFE;border:1px solid #EDF3F9;border-radius:6px;padding:9px 11px;
  word-break:break-all;white-space:pre-wrap}
.foot{background:#fff;border:1px solid var(--line);border-radius:11px;padding:18px 20px;margin-top:26px}
.foot h3{font-size:13.5px;color:var(--ink);margin-bottom:9px}
.foot p{font-size:12.5px;color:var(--sub);line-height:1.9}
.tpl{background:#0F1B2B;color:#C7D8E8;border-radius:8px;padding:13px 15px;margin-top:11px;
  font-family:var(--mono);font-size:11.5px;line-height:1.9;white-space:pre-wrap}
.tpl b{color:#6FD3B8}
@media (max-width:900px){.ov{grid-template-columns:repeat(2,1fr)}
  .srcrow{grid-template-columns:86px 66px 1fr;gap:8px}.srclist{margin-left:0;width:100%}}
"""


def esc(s):
    return (str(s or "")).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def card(f):
    cls = f.get("cls", "ask")
    label, color, _ = CLS_META.get(cls, CLS_META["ask"])
    sev = f.get("sev", "P2")
    sc = SEV_META.get(sev, "#5C6F84")
    srcs = "".join('<i style="background:%s" title="%s">%s</i>'
                   % (SRC_META[s][2], SRC_META[s][0], SRC_META[s][1])
                   for s in (f.get("src") or []) if s in SRC_META)

    p = ['<div class="card" data-cls="%s" data-sev="%s" style="border-left-color:%s">'
         % (cls, sev, color)]
    p.append('<div class="ch"><span class="id">%s</span><span class="ttl">%s</span>'
             % (esc(f.get("id")), esc(f.get("title"))))
    if f.get("area"):
        p.append('<span class="area">%s</span>' % esc(f["area"]))
    p.append('<span class="tag" style="background:%s;color:#fff">%s</span>' % (color, label))
    p.append('<span class="tag" style="background:%s18;color:%s;border:1px solid %s33">%s</span>'
             % (sc, sc, sc, sev))
    p.append('<span class="srclist">%s</span></div>' % srcs)

    p.append('<div class="cb">')
    if f.get("old") and f["old"] != "——":
        p.append('<div class="row"><span class="rk o">原说法</span><div class="rv o">'
                 '<div class="old">%s</div></div></div>' % esc(f["old"]))
    p.append('<div class="row"><span class="rk n">实际</span><div class="rv">'
             '<div class="new">%s</div></div></div>' % esc(f.get("new")))
    if f.get("note"):
        p.append('<div class="row"><span class="rk p">判断</span><div class="rv">'
                 '<div class="note">%s</div></div></div>' % esc(f["note"]))
    if f.get("ask"):
        p.append('<div class="row"><span class="rk q">要你定</span><div class="rv">'
                 '<div class="ask">%s</div></div></div>' % esc(f["ask"]))
    if f.get("proof"):
        p.append('<details class="ev"><summary>证据原文（%d 源）</summary><p>%s</p></details>'
                 % (len(f.get("src") or []), esc(f["proof"])))
    p.append("</div></div>")
    return "".join(p)


def build(d, meta):
    n = len(d)
    cnt = {k: sum(1 for f in d if f.get("cls") == k) for k in CLS_META}
    n_p0 = sum(1 for f in d if f.get("sev") == "P0")
    n_src = len(meta.get("sources") or [])

    rows = "".join(
        '<div class="srcrow"><span class="k"><i style="background:%s"></i>%s</span>'
        '<span class="st%s">%s</span><span class="d">%s</span></div>'
        % (SRC_META.get(s.get("k"), ("", "", "#888"))[2], esc(s.get("name")),
           "" if "已核" in (s.get("status") or "") else " part",
           esc(s.get("status") or "—"), esc(s.get("detail")))
        for s in (meta.get("sources") or [])) or \
        '<div class="srcrow"><span class="k">—</span><span class="st">—</span>' \
        '<span class="d">未登记来源清单</span></div>'

    ov = "".join('<div class="ovc" data-cls="%s" style="border-top-color:%s">'
                 '<b style="color:%s">%d</b><span>%s</span><em>%s</em></div>'
                 % (k, v[1], v[1], cnt[k], v[0], v[2]) for k, v in CLS_META.items())

    body = []
    for k, v in CLS_META.items():
        sub = [f for f in d if f.get("cls") == k]
        if not sub:
            continue
        body.append('<div class="grp"><div class="gt"><span style="color:%s">%s</span>'
                    '<u>%d 条</u><span class="gdesc">%s</span></div>'
                    % (v[1], v[0], len(sub), v[2]))
        body.extend(card(f) for f in sub)
        body.append("</div>")

    chips = ['<span class="t">筛选</span>', '<span class="chip on" data-f="all">全部 %d</span>' % n]
    for k, v in CLS_META.items():
        if cnt[k]:
            chips.append('<span class="chip" data-f="%s">%s %d</span>' % (k, v[0], cnt[k]))
    if n_p0:
        chips.append('<span class="chip s0" data-f="P0">P0 %d</span>' % n_p0)

    p0_items = [f.get("id") for f in d if f.get("sev") == "P0"][:5]

    html = """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>%(title)s</title><style>%(css)s</style></head><body>
<header><div class="wrap">
  <div class="eyebrow">五源核查 · 闸门 1 · 待确认</div>
  <h1>%(h1)s</h1>
  <p class="lead">这一页只有一件事：把从各个来源查出来的东西摆出来，凡是有冲突的地方不替你决定。
    逐条过完，才动手写 PRD。</p>
  <div class="hstat">
    <div><b>%(n)d</b><span>事实条目</span></div>
    <div class="p0"><b>%(p0)d</b><span>P0 阻塞</span></div>
    <div class="cf"><b>%(ncf)d</b><span>来源冲突</span></div>
    <div class="ms"><b>%(nadd)d</b><span>PRD 缺失</span></div>
    <div><b>%(nask)d</b><span>等你回答</span></div>
    <div><b>%(nsrc)d</b><span>核查来源</span></div>
  </div>
</div></header>
<div class="wrap">
  <section><h2>来源，各自核到了什么<em>不写「可达」，只写真看了什么</em></h2>
    <div class="srcs">%(rows)s</div></section>
  <section><h2>发现分布<em>点卡片可筛选</em></h2><div class="ov">%(ov)s</div></section>
  <div class="bar">%(chips)s<span class="sp"></span><span class="cnt" id="cnt"></span></div>
  %(body)s
  <div class="foot"><h3>怎么回最快</h3>
    <p>按编号回就行，不用整句。同一个编号可以一次说完，比如：</p>
    <div class="tpl">%(tpl)s</div>
    <p style="margin-top:11px">标 <b>P0</b> 的 %(p0)d 条不定，PRD 没法动笔——它们会改变正文骨架。
      其余的可以说「按你的判断写」，那就按证据强弱自己定，定完在文档里标出来。</p>
  </div>
</div>
<script>
(function(){
  var cards=[].slice.call(document.querySelectorAll('.card')), cls='all';
  function apply(){
    var n=0;
    cards.forEach(function(c){
      var hit = cls==='all' || (cls==='P0' ? c.dataset.sev==='P0' : c.dataset.cls===cls);
      c.classList.toggle('hide', !hit); if(hit) n++;
    });
    document.getElementById('cnt').textContent='显示 '+n+' / '+cards.length+' 条';
    document.querySelectorAll('.grp').forEach(function(g){
      var vis=g.querySelectorAll('.card:not(.hide)').length;
      g.style.display=vis?'':'none';
      var u=g.querySelector('u'); if(u) u.textContent=vis+' 条';
    });
  }
  document.querySelectorAll('.chip').forEach(function(b){
    b.addEventListener('click',function(){
      document.querySelectorAll('.chip').forEach(function(x){x.classList.remove('on');});
      b.classList.add('on'); cls=b.dataset.f; apply();
    });
  });
  document.querySelectorAll('.ovc').forEach(function(o){
    o.addEventListener('click',function(){
      cls=o.dataset.cls;
      document.querySelectorAll('.chip').forEach(function(x){x.classList.toggle('on',x.dataset.f===cls);});
      apply();
      window.scrollTo({top:document.querySelector('.bar').offsetTop-8,behavior:'smooth'});
    });
  });
  document.querySelectorAll('.id').forEach(function(e){
    e.title='点击复制编号';
    e.addEventListener('click',function(){
      var t=e.textContent; if(navigator.clipboard) navigator.clipboard.writeText(t);
      e.textContent='已复制'; setTimeout(function(){e.textContent=t;},900);
    });
  });
  apply();
})();
</script></body></html>""" % dict(
        title=esc(meta.get("title") or "事实清单"),
        h1=esc(meta.get("h1") or "事实清单"),
        css=CSS, rows=rows, ov=ov, chips="".join(chips), body="".join(body),
        n=n, p0=n_p0, ncf=cnt["conflict"], nadd=cnt["add"], nask=cnt["ask"], nsrc=n_src,
        tpl="\n".join("<b>%s</b> 对，按实际改" % x for x in p0_items) or "（没有 P0）",
    )
    return html


def to_md(d, meta):
    out = ["# %s" % (meta.get("h1") or "事实清单"), "",
           "> 五源核查 · 闸门 1 · 共 %d 条" % len(d), ""]
    for k, v in CLS_META.items():
        sub = [f for f in d if f.get("cls") == k]
        if not sub:
            continue
        out += ["## %s（%d）" % (v[0], len(sub)), ""]
        for f in sub:
            out.append("### %s %s" % (f.get("id"), f.get("title")))
            out.append("")
            out.append("- **严重度**：%s ｜ **来源**：%s" % (
                f.get("sev"), " + ".join(SRC_META[s][0] for s in (f.get("src") or []) if s in SRC_META)))
            if f.get("old") and f["old"] != "——":
                out.append("- **原说法**：%s" % f["old"].replace("\n", " "))
            out.append("- **实际**：%s" % (f.get("new") or "").replace("\n", " / "))
            if f.get("note"):
                out.append("- **判断**：%s" % f["note"].replace("\n", " "))
            if f.get("ask"):
                out.append("- **要你定**：%s" % f["ask"])
            if f.get("proof"):
                out.append("- **证据**：`%s`" % f["proof"].replace("\n", " "))
            out.append("")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description="事实台账 → 可筛选核查清单")
    ap.add_argument("--data", required=True, help="facts.json")
    ap.add_argument("--out", required=True, help="输出 HTML")
    ap.add_argument("--md", help="同时导出 Markdown")
    a = ap.parse_args()

    if not os.path.exists(a.data):
        sys.exit("✗ 数据文件不存在：%s" % a.data)
    try:
        obj = json.load(open(a.data, encoding="utf-8"))
    except json.JSONDecodeError as e:
        sys.exit("✗ 不是合法 JSON：%s" % e)

    if isinstance(obj, dict):
        d = obj.get("facts") or obj.get("items") or []
        meta = obj.get("meta") or {}
    else:
        d = obj
        meta = {}
    if not isinstance(d, list) or not d:
        sys.exit("✗ 台账为空：需要一个非空数组，或 {\"meta\":…,\"facts\":[…]}")
    if not meta.get("title"):
        meta["title"] = "事实清单"
    if not meta.get("h1"):
        meta["h1"] = meta.get("module", "") + " 事实清单" if meta.get("module") else "事实清单"

    # 体检
    cls_cnt = {}
    for f in d:
        c = f.get("cls")
        cls_cnt[c] = cls_cnt.get(c, 0) + 1
        if c not in CLS_META:
            print("  ⚠ %s 的 cls=%r 不认识，按 ask 处理" % (f.get("id"), c), file=sys.stderr)
        if not f.get("src"):
            print("  ⚠ %s 没有 src（来源），会渲染成空徽标" % f.get("id"), file=sys.stderr)
        for s in f.get("src") or []:
            if s not in SRC_META:
                print("  ⚠ %s 的 src 含未知来源 %r" % (f.get("id"), s), file=sys.stderr)

    html = build(d, meta)
    os.makedirs(os.path.dirname(os.path.abspath(a.out)) or ".", exist_ok=True)
    open(a.out, "w", encoding="utf-8").write(html)
    n_p0 = sum(1 for f in d if f.get("sev") == "P0")
    print("→ %s（%.1f KB）" % (a.out, len(html.encode()) / 1024))
    print("  %d 条（%s）· P0 %d" % (
        len(d), " / ".join("%s %d" % (CLS_META[k][0], v) for k, v in cls_cnt.items() if k in CLS_META),
        n_p0))

    if a.md:
        open(a.md, "w", encoding="utf-8").write(to_md(d, meta))
        print("→ %s" % a.md)


if __name__ == "__main__":
    import _compat as _c   # 控制台编码兜底（Windows 默认 cp936 编不出 ✓ ✗）
    _c.init()
    main()
