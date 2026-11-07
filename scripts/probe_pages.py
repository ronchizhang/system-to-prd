#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从已登录的浏览器里探测页面结构，输出 JSON。

不负责业务判断，只负责把 DOM 里的客观事实捞出来：
导航有哪些、表单有哪些字段、表格有哪些列、某个元素的真实尺寸是多少。

前置：Chrome/Edge 以 --remote-debugging-port=9222 启动，且已登录目标系统。
      自行登录一次即可，本脚本不碰凭据。

用法：
    python3 probe_pages.py nav
    python3 probe_pages.py form
    python3 probe_pages.py table
    python3 probe_pages.py dims --selector ".ant-form-item input"
    python3 probe_pages.py nav --port 9223 --url-filter test1admin
"""

import argparse
import json
import os
import sys
import urllib.request

CDP_LIST = "http://127.0.0.1:%d/json/list"

JS_NAV = r"""
(function(){
  var out = [];
  var seen = {};
  document.querySelectorAll('a[href], .ant-menu-item, .ant-menu-submenu-title, nav *[role=menuitem]')
    .forEach(function(el){
      var t = (el.innerText || '').trim().split('\n')[0];
      var h = el.getAttribute('href') || '';
      if (!t || t.length > 30) return;
      var k = t + '|' + h;
      if (seen[k]) return;
      seen[k] = 1;
      out.push({text: t, href: h});
    });
  return JSON.stringify(out);
})()
"""

JS_FORM = r"""
(function(){
  var items = document.querySelectorAll('.ant-form-item, .el-form-item, form .form-item, form .row');
  if (!items.length) items = document.querySelectorAll('form > div');
  var out = [];
  items.forEach(function(it){
    var lab = it.querySelector('label');
    var ctl = it.querySelector('input, select, textarea');
    if (!lab && !ctl) return;
    out.push({
      label: lab ? lab.innerText.trim().replace(/\s+/g,' ') : '',
      required: !!it.querySelector('.ant-form-item-required, .required, [class*=required]'),
      control: ctl ? ctl.tagName.toLowerCase() : '',
      type: ctl ? (ctl.getAttribute('type') || '') : '',
      disabled: ctl ? (ctl.disabled || ctl.hasAttribute('readonly')) : false,
      value: ctl ? (ctl.value || '').toString().slice(0, 40) : ''
    });
  });
  return JSON.stringify(out);
})()
"""

JS_TABLE = r"""
(function(){
  var out = [];
  document.querySelectorAll('table').forEach(function(tb, ti){
    var ths = [].slice.call(tb.querySelectorAll('thead th')).map(function(th){
      return th.innerText.trim().replace(/\s+/g,' ');
    });
    if (!ths.length) return;
    var rows = [].slice.call(tb.querySelectorAll('tbody tr')).slice(0, 3).map(function(tr){
      return [].slice.call(tr.children).map(function(td){
        return (td.innerText || '').trim().replace(/\s+/g,' ').slice(0, 60);
      });
    });
    out.push({index: ti, headers: ths, sample: rows});
  });
  return JSON.stringify(out);
})()
"""

JS_DIMS = r"""
(function(sel){
  var out = [];
  document.querySelectorAll(sel).forEach(function(el, i){
    if (i > 5) return;
    var r = el.getBoundingClientRect();
    var c = getComputedStyle(el);
    out.push({
      tag: el.tagName.toLowerCase(),
      w: Math.round(r.width), h: Math.round(r.height),
      fontSize: c.fontSize, color: c.color,
      bg: c.backgroundColor, border: c.borderColor,
      radius: c.borderRadius, display: c.display
    });
  });
  return JSON.stringify(out);
})(%s)
"""


def pick_target(port, url_filter):
    try:
        lst = json.loads(urllib.request.urlopen(CDP_LIST % port, timeout=5).read())
    except Exception as e:
        sys.exit("连不上 CDP 端口 %d：%s\n请确认浏览器以 --remote-debugging-port 启动" % (port, e))
    pages = [t for t in lst if t.get("type") == "page"]
    if not pages:
        sys.exit("没有可用的页面标签")
    if url_filter:
        hit = [t for t in pages if url_filter in t.get("url", "")]
        if not hit:
            sys.exit("没有 URL 含「%s」的标签页。现有：\n  %s"
                     % (url_filter, "\n  ".join(t.get("url", "") for t in pages)))
        return hit[0]
    return pages[0]


def run_js(port, url_filter, expr):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    try:
        import cdp_boot
        cdp = cdp_boot.load()
    except ImportError as e:
        sys.exit("✗ %s" % e)
    t = pick_target(port, url_filter)
    P = cdp.CDPClient(port=port).connect_page(t["id"])
    r = P.evaluate(expr)
    return r.get("value") if isinstance(r, dict) else r


def main():
    ap = argparse.ArgumentParser(description="探测页面结构")
    ap.add_argument("what", choices=["nav", "form", "table", "dims"])
    ap.add_argument("--port", type=int, default=9222)
    ap.add_argument("--url-filter", default="", help="按 URL 关键字选标签页")
    ap.add_argument("--selector", default="input", help="dims 模式的选择器")
    ap.add_argument("--pretty", action="store_true", help="格式化输出")
    args = ap.parse_args()

    js = {"nav": JS_NAV, "form": JS_FORM, "table": JS_TABLE}.get(args.what)
    if args.what == "dims":
        js = JS_DIMS % json.dumps(args.selector)

    raw = run_js(args.port, args.url_filter, js)
    try:
        data = json.loads(raw)
    except Exception:
        print(raw)
        return 1

    if args.pretty:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(data, ensure_ascii=False))
    print("\n# 共 %d 项" % (len(data) if isinstance(data, list) else 1), file=sys.stderr)
    return 0


if __name__ == "__main__":
    import _compat as _c   # 控制台编码兜底（Windows 默认 cp936 编不出 ✓ ✗）
    _c.init()
    sys.exit(main())
