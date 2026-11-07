#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""逐页截图 + 自动布局诊断。

改完样式必须逐页核一遍。人眼看截图能发现大部分问题，
但有两类问题很适合让脚本先筛出来，省掉反复看图的功夫：

  1. 文字竖排 —— 容器宽度被压到几十像素
  2. 页面区被挤窄 —— 文档栏的宽表格把左栏顶掉

用法：
    python3 shot_verify.py --html ../02-管理后台/管理后台PRD-原型版.html
    python3 shot_verify.py --html x.html --keys ov,p1,p2 --out ../资源/shots
    python3 shot_verify.py --html x.html --keys p1 --width 1440 --scale 2

前置：Chrome 以 --remote-debugging-port=9222 启动。
"""

import argparse
import base64
import json
import os
import sys
import time
import urllib.request

DIAG_JS = r"""
(function(){
  var f = document.getElementById('cv');
  var d = f && f.contentDocument;
  var res = {docW: document.documentElement.clientWidth, issues: []};

  // 页面区宽度：被文档栏挤掉时这里会显著变小
  var stage = document.querySelector('.stage, .main, #stage');
  if (stage){
    res.stageW = Math.round(stage.getBoundingClientRect().width);
    if (res.stageW < res.docW * 0.45)
      res.issues.push('页面区过窄：' + res.stageW + 'px（视口 ' + res.docW + 'px），检查文档栏是否缺 min-width:0');
  }

  var doc = document.querySelector('.doc, #doc');
  if (doc) res.docW = Math.round(doc.getBoundingClientRect().width);

  if (!d) { res.issues.push('找不到 iframe 内容（页面未渲染）'); return JSON.stringify(res); }

  res.pageH = d.documentElement.scrollHeight;

  // 横向溢出
  var sw = d.documentElement.scrollWidth, cw = d.documentElement.clientWidth;
  if (sw > cw + 8) res.issues.push('页面横向溢出：' + sw + 'px > ' + cw + 'px');

  // 竖排嫌疑：窄且高、且文字超过 3 个字
  var suspects = [];
  d.querySelectorAll('div, td, span').forEach(function(el){
    var r = el.getBoundingClientRect();
    if (r.width > 0 && r.width < 46 && r.height > 90){
      var t = (el.innerText || '').trim();
      if (t.length > 3) suspects.push(t.slice(0, 14) + '(' + Math.round(r.width) + 'px)');
    }
  });
  if (suspects.length)
    res.issues.push('疑似文字竖排 ' + suspects.length + ' 处：' + suspects.slice(0, 3).join(' / '));

  return JSON.stringify(res);
})()
"""


SINGLE_JS = r"""
(function(){
  var d = document, doc = d.getElementById('doc');
  var res = {mode: 'single', docW: d.documentElement.clientWidth, issues: []};
  var meta = (window.PRD_DATA || {}).meta || {};
  res.title = meta.module || '-';

  // 关键结构计数
  res.h2 = d.querySelectorAll('#doc h2').length;
  res.rules = d.querySelectorAll('.rule').length;
  res.cases = d.querySelectorAll('.case').length;
  res.svg = d.querySelectorAll('.sm svg').length;
  res.dlg = d.querySelectorAll('.dlg table').length;
  res.jlines = d.querySelectorAll('.jline').length;
  res.warn = d.querySelectorAll('.warnbar').length;

  // 四块
  res.frames = d.querySelectorAll('.ptab').length;
  res.pxH = (d.querySelector('.px') || {}).offsetHeight || 0;
  var z = d.getElementById('protoZoom');
  res.zoom = z ? z.textContent : '';
  res.facts = d.querySelectorAll('.fcard').length;
  res.p0 = d.querySelectorAll('.fcard[data-sev="P0"]').length;
  res.rlink = d.querySelectorAll('.rule .frel a').length;
  res.kfact = d.querySelectorAll('.fch .fsrclist i').length;

  // 8 段齐全？
  if (res.h2 < 8) res.issues.push('叙事只有 ' + res.h2 + ' 段，应有 8 段');
  if (res.warn) res.issues.push('页面顶部有缺段警告条，说明 sections 不足 8 段');
  if (!res.rules) res.issues.push('没有规则卡（rules 为空）');
  if (!res.svg) res.issues.push('没有状态机图（transitions.states 为空或未声明 statemachine）');
  if (!res.jlines) res.issues.push('AI 层没有条目（context/entities/rules 全空？）');

  // 四块齐全？
  if (!res.frames) res.issues.push('① 原型：没有帧（prototype.frames 为空）');
  if (!res.facts) res.issues.push('④ 核查：没有事实卡（facts 为空）');
  if (res.frames && !res.pxH) res.issues.push('① 原型：帧存在但 .px 没渲染出高度，html 可能是空的');
  if (res.facts && !res.kfact) res.issues.push('④ 核查：事实卡没有来源徽标（src 为空）');
  if (res.rules && !res.rlink) res.issues.push('叙事规则没有挂依据（rule.facts 全空，点不回核查）');

  // 横向溢出
  if (d.documentElement.scrollWidth > res.docW + 2)
    res.issues.push('页面横向溢出：' + d.documentElement.scrollWidth + 'px > 视口 ' + res.docW);

  // 文字竖排 / 容器被压窄
  var narrow = [];
  d.querySelectorAll('#doc .rule, #doc .scn, #doc .tw, #doc .callout, #doc p').forEach(function(e){
    var r = e.getBoundingClientRect();
    if (r.width > 0 && r.width < 60 && r.height > 80)
      narrow.push((e.className || e.tagName) + ' ' + Math.round(r.width) + 'x' + Math.round(r.height));
  });
  if (narrow.length) res.issues.push('疑似文字竖排：' + narrow.slice(0,3).join('; '));

  // 表格是否溢出容器
  var tw = [];
  d.querySelectorAll('.tw').forEach(function(e){
    if (e.scrollWidth > e.clientWidth + 4 &&
        getComputedStyle(e).overflowX === 'visible') tw.push(Math.round(e.scrollWidth)+'>'+Math.round(e.clientWidth));
  });
  if (tw.length) res.issues.push('表格溢出且无横向滚动：' + tw.slice(0,3).join(', '));

  // 原型缩放是否过小（并排时窄栏必然缩小，提醒去看单视图）
  var m = /(\d+)%/.exec(res.zoom || '');
  res.zoomPct = m ? parseInt(m[1], 10) : 0;
  if (res.zoomPct && res.zoomPct < 40)
    res.issues.push('原型在并排栏里只有 ' + res.zoomPct + '%——看图请切「原型」单视图');

  // 空段
  var empty = 0;
  d.querySelectorAll('#doc h2').forEach(function(h){
    var n = h.nextElementSibling;
    if (!n || (n.tagName === 'H2')) empty++;
  });
  if (empty) res.issues.push('有 ' + empty + ' 个段落标题下面没有内容');

  return JSON.stringify(res);
})()
"""


# 截图前先等页面稳：字体、图片、连续两帧布局都不再变。
# 固定 sleep 是要么截早了（半截渲染），要么白等——两种情况都真实发生过。
SETTLE_JS = r"""
new Promise(function(resolve){
  var t0 = Date.now(), last = null, stable = 0, imgWait = 0;
  function metrics(){
    var d = document;
    return [d.documentElement.scrollHeight, d.documentElement.scrollWidth,
            document.body ? document.body.scrollHeight : 0].join("x");
  }
  function tick(){
    var m = metrics();
    if (m === last) stable++; else { stable = 0; last = m; }
    // 连续两个 rAF 尺寸一致 = 布局不再动；2.6s 硬上限防止页面永远在动
    if (stable >= 2 || Date.now() - t0 > 2600) { resolve(1); return; }
    requestAnimationFrame(tick);
  }
  function afterFonts(){
    var pending = Array.prototype.filter.call(document.images, function(im){ return !im.complete; });
    if (pending.length && imgWait < 40) { imgWait++; setTimeout(afterFonts, 50); return; }
    requestAnimationFrame(function(){ requestAnimationFrame(tick); });
  }
  if (document.fonts && document.fonts.ready && document.fonts.ready.then) {
    document.fonts.ready.then(afterFonts).catch(afterFonts);
  } else { afterFonts(); }
})
"""


def wait_settle(P, fallback=1.0):
    """等渲染真的落定再截图。失败就退回固定等待，不让核对流程挂住。"""
    try:
        P.send("Runtime.evaluate",
               {"expression": SETTLE_JS, "awaitPromise": True,
                "returnByValue": True, "userGesture": True},
               timeout=8)
        return True
    except Exception:
        time.sleep(fallback)
        return False


# 内容被 overflow:hidden 切掉：模板里已算过一次，这里再兜底问一次
CLIP_JS = r"""
(function(){
  try{
    if (!window.clipScan) return '';
    var c = window.clipScan();
    if (!c.length) return '';
    return c.slice(0, 4).map(function(x){
      return x.cls + '(' + x.axis + '溢 ' + x.over + 'px)';
    }).join(' / ') + (c.length > 4 ? ' 等 ' + c.length + ' 处' : '');
  }catch(e){ return ''; }
})()
"""


def clip_issue(ev):
    try:
        s = ev(CLIP_JS)
    except Exception:
        return None
    return ('内容被裁切：' + s) if s else None


# 只查当前这一帧是不够的：底部按钮被切往往只发生在某一个弹窗帧上
# （2026-11-06 字段详情那帧就是这么漏掉的）。逐帧点一遍再量。
FRAME_SWEEP_JS = r"""
(function(){
  var tabs = document.querySelectorAll('.ptab'), bad = [], first = null;
  if (!tabs.length || !window.clipScan) return '';
  first = tabs[0];
  for (var i = 0; i < tabs.length; i++){
    tabs[i].click();
    try {
      var c = window.clipScan();
      if (c.length) {
        bad.push(tabs[i].textContent.replace(/\s+/g,' ').trim() + ' → ' +
          c.map(function(x){ return x.cls + ' ' + x.axis + '溢 ' + x.over + 'px'; }).join('、'));
      }
    } catch(e){}
  }
  if (first) first.click();
  return bad.join(' ｜ ');
})()
"""


def frame_sweep(ev):
    try:
        s = ev(FRAME_SWEEP_JS)
    except Exception:
        return None
    return ('逐帧裁切：' + s) if s else None


def verify_single(P, ev, args, out_dir):
    """单页模板（原型 / 叙事 / AI 读 / 核查 四视图）的核对。"""
    diag = {}
    try:
        diag = json.loads(ev(SINGLE_JS) or "{}")
    except Exception as e:
        print("  诊断失败：%s" % e)
    issues = diag.get("issues", [])
    ci = clip_issue(ev)
    if ci:
        issues.append(ci)
    fs = frame_sweep(ev)
    if fs:
        issues.append(fs)
    print("== 单页 PRD 核对：%s ==" % diag.get("title", "-"))
    print("  ① 原型 %d 帧（缩放 %s）· ② 叙事 %d 段 / %d 规则 / %d case / %d 状态图"
          % (diag.get("frames", 0), diag.get("zoom", "?"), diag.get("h2", 0),
             diag.get("rules", 0), diag.get("cases", 0), diag.get("svg", 0)))
    print("  ③ AI 读 %d 条目 · ④ 核查 %d 条事实（P0 %d）· 规则挂依据 %d 处"
          % (diag.get("jlines", 0), diag.get("facts", 0), diag.get("p0", 0),
             diag.get("rlink", 0)))

    for mode in ("both", "proto", "human", "ai", "facts"):
        if args.skip_shot:
            break
        ok = ev("""(function(){var b=document.querySelector('.modes button[data-m=\"%s\"]');
          if(!b) return 0; b.click(); return 1;})()""" % mode)
        if not ok:
            continue
        wait_settle(P)
        r = P.send("Page.captureScreenshot", {"format": "png"})
        path = os.path.join(out_dir, "prd_%s.png" % mode)
        open(path, "wb").write(base64.b64decode(r["data"]))
        print("  截图 → %s" % path)

    print()
    if issues:
        print("结论：%d 处可疑，逐条看：" % len(issues))
        for i in issues:
            print("  · " + i)
        return 1
    print("结论：结构诊断未发现问题。**仍需人眼过截图**——重叠、标签压线、颜色对比这些都查不出来。")
    return 0



FULL_ONE_JS = r"""
(function(){
  var d = document, res = {}, issues = [];
  res.title = (D.meta || {}).module || '-';
  res.h2 = d.querySelectorAll('#doc h2').length;
  res.rules = d.querySelectorAll('.rule').length;
  res.cases = d.querySelectorAll('.case').length;
  res.svg = d.querySelectorAll('.sm svg').length;
  res.jlines = d.querySelectorAll('.jline').length;
  res.frames = d.querySelectorAll('.ptab').length;
  res.facts = d.querySelectorAll('.fcard').length;
  res.p0 = d.querySelectorAll('.fcard[data-sev="P0"]').length;
  res.rlink = d.querySelectorAll('.rule .frel a').length;
  var z = d.getElementById('protoZoom');
  res.zoom = z ? z.textContent : '';
  if (res.h2 < 8) issues.push('叙事只有 ' + res.h2 + ' 段');
  if (!res.rules) issues.push('没有规则卡');
  if (!res.svg) issues.push('没有状态机图');
  if (!res.jlines) issues.push('AI 层没有条目');
  if (!res.frames) issues.push('① 原型没帧（定时任务、纯配置这类无界面模块可忽略）');
  if (!res.facts) issues.push('④ 事实清单为空');
  if (res.rules && !res.rlink) issues.push('规则没挂依据（点不回核查）');
  res.issues = issues;
  return JSON.stringify(res);
})()
"""


def verify_full(P, ev, args, out_dir):
    """全量 PRD（多模块 + 左侧导航）：逐个模块切过去，量四块有没有渲染出来。"""
    mods = json.loads(ev("JSON.stringify(((window.PRD_DATA||{}).modules||[]).map(function(m){"
                         "return {key:(m.meta||{}).key,name:(m.meta||{}).module}}))") or "[]")
    print("== 全量 PRD 核对：%d 个模块 ==" % len(mods))
    bad = 0
    for i, m in enumerate(mods):
        ok = ev("(function(){var b=document.querySelectorAll('#nvList .ni:not(.ov)')[%d];"
                "if(!b) return 0; b.click(); return 1;})()" % i)
        if not ok:
            print("  ✗ %-12s 侧栏点不到" % m.get("key"))
            bad += 1
            continue
        wait_settle(P)
        try:
            diag = json.loads(ev(FULL_ONE_JS) or "{}")
        except Exception:
            diag = {}
        issues = diag.get("issues", [])
        ci = clip_issue(ev)
        if ci:
            issues.append(ci)
        fs = frame_sweep(ev)
        if fs:
            issues.append(fs)
        print("  %s %-18s %d 段 · %d 规则 · %d case · 原型 %d 帧 · 事实 %d(P0 %d) · 依据 %d"
              % ("✗" if issues else "✓", diag.get("title", "-"), diag.get("h2", 0),
                 diag.get("rules", 0), diag.get("cases", 0), diag.get("frames", 0),
                 diag.get("facts", 0), diag.get("p0", 0), diag.get("rlink", 0)))
        for x in issues:
            print("      · " + x)
        if issues:
            bad += 1
        if not args.skip_shot and i < 2:
            path = os.path.join(out_dir, "full_%02d_%s.png" % (i, m.get("key")))
            cl_shot(P, path)
            print("      截图 → %s" % path)

    print()
    if bad:
        print("结论：%d 个模块有缺口。" % bad)
        return 1
    print("结论：全部模块四块齐全。仍需人眼过截图确认排版。")
    return 0


def cl_shot(P, path):
    r = P.send("Page.captureScreenshot", {"format": "png"})
    open(path, "wb").write(base64.b64decode(r["data"]))


def main():
    ap = argparse.ArgumentParser(description="逐页截图与诊断")
    ap.add_argument("--html", required=True, help="产物 HTML 路径")
    ap.add_argument("--keys", default="", help="页面 key，逗号分隔；留空则自动探测")
    ap.add_argument("--out", default="", help="截图输出目录，默认与 html 同级")
    ap.add_argument("--width", type=int, default=1680)
    ap.add_argument("--height", type=int, default=1200)
    ap.add_argument("--scale", type=float, default=1.0)
    ap.add_argument("--port", type=int, default=9222)
    ap.add_argument("--skip-shot", action="store_true", help="只诊断不截图")
    args = ap.parse_args()

    html_abs = os.path.abspath(args.html)
    if not os.path.isfile(html_abs):
        sys.exit("找不到产物：%s" % html_abs)
    out_dir = args.out or os.path.dirname(html_abs)
    os.makedirs(out_dir, exist_ok=True)

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    try:
        import cdp_boot
        cdp = cdp_boot.load()
    except ImportError as e:
        sys.exit("✗ %s" % e)

    try:
        lst = json.loads(urllib.request.urlopen(
            "http://127.0.0.1:%d/json/list" % args.port, timeout=5).read())
    except Exception as e:
        sys.exit("连不上 CDP（%s）。\n%s" % (e, cdp_boot.hint(args.port)))
    pages = [t for t in lst if t.get("type") == "page"]
    if not pages:
        sys.exit("没有可用标签页")

    P = cdp.CDPClient(port=args.port).connect_page(pages[0]["id"])
    P.send("Emulation.setDeviceMetricsOverride", {
        "width": args.width, "height": args.height,
        "deviceScaleFactor": args.scale, "mobile": False})
    time.sleep(0.4)

    # 必须带缓存破坏参数，否则截到的是旧页面
    import _compat
    P.navigate(_compat.file_url(html_abs, "v=%d" % int(time.time())))
    time.sleep(0.5)
    wait_settle(P)                      # 首屏也要等：字体一换，整页高度都会变

    def ev(js):
        r = P.evaluate(js)
        return r.get("value") if isinstance(r, dict) else r

    keys = [k.strip() for k in args.keys.split(",") if k.strip()]
    if not keys:
        raw = ev("""(function(){
          try{ if (typeof MODULES !== 'undefined') {
            var o=[]; MODULES.forEach(function(m){ m[2].forEach(function(p){ o.push(p[0]); }); });
            return o.join(',');
          } }catch(e){}
          return '';
        })()""")
        keys = [k for k in (raw or "").split(",") if k]
        if not keys:
            # 全量 PRD：window.PRD_DATA.modules 存在
            if ev("(function(){return (window.PRD_DATA&&window.PRD_DATA.modules)?1:0})()"):
                return verify_full(P, ev, args, out_dir)
            # 单页模板（原型 / 叙事 / AI 读 / 核查 四视图）走另一条核对路径
            if ev("(function(){return (typeof window.PRD_DATA!=='undefined')?1:0})()"):
                return verify_single(P, ev, args, out_dir)
            sys.exit("无法自动探测页面 key，请用 --keys 显式指定")

    print("== 截图核对：%d 个页面 ==" % len(keys))
    bad = []
    for k in keys:
        ok = ev("(function(){try{return goKey('%s')?1:0}catch(e){return 0}})()" % k)
        if not ok:
            print("  %-5s 跳转失败（goKey 不存在或 key 不匹配）" % k)
            bad.append((k, ["goKey 失败"]))
            continue
        wait_settle(P)

        diag = {}
        try:
            diag = json.loads(ev(DIAG_JS) or "{}")
        except Exception:
            pass
        issues = diag.get("issues", [])
        ci = clip_issue(ev)
        if ci:
            issues.append(ci)

        if not args.skip_shot:
            r = P.send("Page.captureScreenshot", {"format": "png"})
            path = os.path.join(out_dir, "%s.png" % k)
            open(path, "wb").write(base64.b64decode(r["data"]))

        flag = "  ✗" if issues else "  ✓"
        print("%s %-6s 页面高 %-6s 文档栏 %-5s" % (
            flag, k, diag.get("pageH", "?"), diag.get("docW", "?")))
        for i in issues:
            print("        · " + i)
        if issues:
            bad.append((k, issues))

    print()
    if bad:
        print("结论：%d 个页面有可疑布局，先看上面列出的项，再决定是否人工复查截图。"
              % len(bad))
        return 1
    print("结论：结构诊断未发现问题。仍需人眼过一遍截图确认文字与对齐。")
    return 0


if __name__ == "__main__":
    import _compat as _c   # 控制台编码兜底（Windows 默认 cp936 编不出 ✓ ✗）
    _c.init()
    sys.exit(main())
