#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 PRD 单文件 HTML 里的规格文档导出成纯 Markdown（交付必备）。

为什么必须导
------------
PRD 产物的页面与文档都存在 JS 字符串里，整段被 json.dumps 打成**一行**
（实测某端那行 344 KB）。任何按行读文件的工具都会在 2000 字符处截断，
于是模型"打不开 PRD"——不是文件坏了，是它只看到那一行的开头 2 KB。

交付物只有 HTML 时，这份 PRD 对人和对模型都是不可检索的。
所以：**HTML 是视觉真相，Markdown 是检索层，两个一起交。**

做法：用浏览器（CDP）把页面跑起来，从运行时的 `DOCS` 对象
（或已渲染的 `[id^="doc-"]` 容器）取 HTML，再转 Markdown。

用法
----
    python3 export_docs_md.py --html ../01-机构端/PRD.html --out-dir ../90-共享/PRD规格
    python3 export_docs_md.py --html a.html --html b.html --out-dir out/
    python3 export_docs_md.py --html a.html --check     # 只探测能取到几页

前置：Chrome 以 --remote-debugging-port=9222 启动（脚本自己开标签页、自己关）。
"""

import argparse
import glob
import json
import os
import sys
import time
import urllib.parse
from html.parser import HTMLParser

# ---------------------------------------------------------------- HTML → MD


class HtmlToMd(HTMLParser):
    """够用的 HTML→Markdown。只覆盖 PRD 文档实际用到的标签，不做通用转换。"""

    BLOCK = {"p", "div", "section", "blockquote", "h1", "h2", "h3", "h4", "h5", "h6",
             "ul", "ol", "li", "table", "tr", "td", "th", "br", "hr"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.blocks = []        # 已完成的 Markdown 块
        self.buf = []           # 当前块的行内文本
        self.prefix = ""        # 当前块前缀（标题 / 列表符 / 引用）
        self.tag_stack = []
        self.list_stack = []    # [(kind, counter)]
        self.table = None       # {"rows": [[cell,...]], "row": [...], "cell": [...]}
        self.in_cell = False

    # ---- 小工具
    def _flush(self):
        text = "".join(self.buf)
        text = " ".join(text.split())
        if text:
            self.blocks.append((self.prefix + text) if self.prefix else text)
        self.buf = []
        self.prefix = ""

    def _text(self, s):
        if self.in_cell:
            self.table["cell"].append(s)
        else:
            self.buf.append(s)

    # ---- HTMLParser 回调
    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        cls = a.get("class") or ""
        self.tag_stack.append(tag)

        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self._flush()
            level = int(tag[1])
            self.prefix = "#" * min(level, 6) + " "
            return

        if tag == "table":
            self._flush()
            self.table = {"rows": [], "row": [], "cell": []}
            return
        if tag == "tr" and self.table is not None:
            self.table["row"] = []
            return
        if tag in ("td", "th") and self.table is not None:
            self.table["cell"] = []
            self.in_cell = True
            return

        if tag in ("ul", "ol"):
            self._flush()
            self.list_stack.append([tag, 0])
            return
        if tag == "li":
            self._flush()
            depth = max(len(self.list_stack) - 1, 0)
            indent = "  " * depth
            if self.list_stack and self.list_stack[-1][0] == "ol":
                self.list_stack[-1][1] += 1
                self.prefix = "%s%d. " % (indent, self.list_stack[-1][1])
            else:
                self.prefix = "%s- " % indent
            return

        if tag == "br":
            self._text("  \n")
            return

        if tag in ("b", "strong"):
            self._text("**")
            return
        if tag in ("i", "em"):
            self._text("*")
            return
        if tag == "code":
            self._text("`")
            return
        if tag == "a":
            href = a.get("href") or ""
            if href and not href.startswith("#"):
                self._text("[")
                self.tag_stack[-1] = "a|" + href
            return
        if tag in ("p", "div", "blockquote", "section"):
            self._flush()
            if "dchg" in cls:
                self.prefix = "> 🔖 改动："
            return
        if tag == "hr":
            self._flush()
            self.blocks.append("---")

    def handle_endtag(self, tag):
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "div",
                   "blockquote", "section"):
            self._flush()
        elif tag == "table" and self.table is not None:
            self._flush_table()
        elif tag == "tr" and self.table is not None:
            if self.table["row"]:
                self.table["rows"].append(self.table["row"])
            self.table["row"] = []
        elif tag in ("td", "th") and self.table is not None:
            cell = " ".join("".join(self.table["cell"]).split())
            cell = cell.replace("|", "\\|")
            self.table["row"].append(cell)
            self.table["cell"] = []
            self.in_cell = False
        elif tag in ("ul", "ol"):
            self._flush()
            if self.list_stack:
                self.list_stack.pop()
        elif tag in ("b", "strong"):
            self._text("**")
        elif tag in ("i", "em"):
            self._text("*")
        elif tag == "code":
            self._text("`")
        elif tag == "a":
            if self.tag_stack and str(self.tag_stack[-1]).startswith("a|"):
                href = str(self.tag_stack[-1])[2:]
                self._text("](%s)" % href)

        if self.tag_stack:
            self.tag_stack.pop()

    def handle_data(self, data):
        self._text(data)

    def _flush_table(self):
        t = self.table
        if t["row"]:
            t["rows"].append(t["row"])
        rows = [r for r in t["rows"] if any(c.strip() for c in r)]
        self.table = None
        if not rows:
            return
        width = max(len(r) for r in rows)
        rows = [r + [""] * (width - len(r)) for r in rows]
        out = ["| " + " | ".join(rows[0]) + " |",
               "|" + "|".join(["---"] * width) + "|"]
        for r in rows[1:]:
            out.append("| " + " | ".join(r) + " |")
        self.blocks.append("\n".join(out))

    def result(self):
        self._flush()
        return "\n\n".join(self.blocks)


def html_to_md(html):
    p = HtmlToMd()
    p.feed(html or "")
    p.close()
    return p.result()


# ---------------------------------------------------------------- CDP 取数


def cdp_dir():
    here = os.path.dirname(os.path.abspath(__file__))
    if os.path.isfile(os.path.join(here, "vendor_cdp.py")):
        return here
    cands = [os.environ.get("CODEBUDDY_SKILL_DIR", "")]
    cands.append(os.path.expanduser(
        "~/.workbuddy/skills/browser-automation-cdp/scripts"))
    pats = [os.path.expanduser(
        "~/.workbuddy/plugins/cache/*/browser-automation-cdp*/**/scripts")]
    for d in cands:
        if d and os.path.isfile(os.path.join(d, "cdp.py")):
            return d
    for pat in pats:
        for d in glob.glob(pat, recursive=True):
            if os.path.isfile(os.path.join(d, "cdp.py")):
                return d
    sys.exit("找不到 CDP 机构端：包内少了 vendor_cdp.py，也没装 browser-automation-cdp skill")


EXTRACT_JS = r"""
(function(){
  var out = {mode: '', pages: []};
  function titleOf(k, html, fallback){
    if (typeof TITLES !== 'undefined' && TITLES && TITLES[k]) return String(TITLES[k]);
    var d = document.createElement('div');
    d.innerHTML = html || '';
    var h = d.querySelector('h1,h2,h3,h4');
    return h ? h.textContent.trim() : (fallback || k);
  }
  if (typeof DOCS !== 'undefined' && DOCS && typeof DOCS === 'object'
      && Object.keys(DOCS).length) {
    out.mode = 'DOCS';
    Object.keys(DOCS).forEach(function(k, i){
      var html = String(DOCS[k] || '');
      out.pages.push([k, i, html, titleOf(k, html, k)]);
    });
    return JSON.stringify(out);
  }
  out.mode = 'DOM';
  var nodes = document.querySelectorAll('[id^="doc-"]');
  for (var i = 0; i < nodes.length; i++) {
    var key = nodes[i].id.slice(4), html = nodes[i].innerHTML;
    out.pages.push([key, i, html, titleOf(key, html, key)]);
  }
  return JSON.stringify(out);
})()
"""


def fetch_pages(html_path, wait=2.0):
    d = cdp_dir()
    sys.path.insert(0, d)
    mod = "vendor_cdp" if os.path.isfile(os.path.join(d, "vendor_cdp.py")) else "cdp"
    CDPClient = __import__(mod).CDPClient
    CDPError = __import__(mod).CDPError

    import _compat
    url = _compat.file_url(html_path)
    c = CDPClient(port=9222, timeout=30)
    try:
        tab = c._http_json("/json/new?" + urllib.parse.quote(url, safe=""),
                           method="PUT")
    except CDPError as exc:
        sys.exit("CDP 不可达（%s）。请先起一个带调试端口的 Chrome：\n"
                 "  %s %s" % (exc, _compat.python_cmd(),
                                 os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                              "launch_chrome.py")))
    c.connect_page(tab["id"])
    last = None
    deadline = time.time() + 25
    while time.time() < deadline:
        time.sleep(wait)
        try:
            r = c.send("Runtime.evaluate",
                       {"expression": EXTRACT_JS, "returnByValue": True})
            val = (r.get("result") or {}).get("value")
            if val:
                last = json.loads(val)
                break
        except CDPError:
            pass
        wait = 1.0
    try:
        c.send("Page.close", {})
    except CDPError:
        pass
    c.close()
    if not last:
        sys.exit("在 %s 里取不到文档数据（超时）" % os.path.basename(html_path))
    return last


# ---------------------------------------------------------------- 组装输出


def export_one(html_path, out_dir, check_only=False):
    if not os.path.isfile(html_path):
        print("  ✗ 源文件不存在：%s" % html_path)
        return None
    label = os.path.splitext(os.path.basename(html_path))[0]

    data = fetch_pages(os.path.abspath(html_path))
    pages = sorted(data["pages"], key=lambda x: x[1])
    pages = [(k, h, t) for k, _i, h, t in pages]
    print("  %s：%d 页（取数方式 %s）" % (label, len(pages), data["mode"]))
    if check_only:
        return len(pages)

    md = []
    md.append("# %s · 规格导出" % label)
    md.append("")
    md.append("> **自动生成，不要手改。** 由 `export_docs_md.py` 从 `%s` 导出。"
              % os.path.basename(html_path))
    md.append("> 视觉真相仍在 HTML 里；本文件是给**检索与问答**用的文本层。")
    md.append("> 页数 %d ｜ 生成于 %s"
              % (len(pages), time.strftime("%Y-%m-%d %H:%M")))
    md.append("")
    md.append("## 页面索引")
    md.append("")
    for key, _h, title in pages:
        md.append("- `%s` — %s" % (key, title.replace(",", " · ")))
    md.append("")
    md.append("---")
    total = 0
    for key, html, title in pages:
        body = html_to_md(html).strip()
        # 文档自己的首个标题常常就是页标题，去掉避免和 ## 标题重复
        lines = body.split("\n")
        if lines:
            head = lines[0].lstrip("#").strip()
            if head and head.replace(",", " · ") == title.replace(",", " · "):
                body = "\n".join(lines[1:]).lstrip("\n")
        total += len(body)
        md.append("")
        md.append("<!-- page: %s -->" % key)
        md.append("")
        md.append("## %s" % title.replace(",", " · "))
        md.append("")
        md.append(body)
        md.append("")
    text = "\n".join(md).rstrip() + "\n"

    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, label + "-规格.md")
    with open(out, "w", encoding="utf-8") as fp:
        fp.write(text)
    print("    → %s（%d 页 / 正文 %.1f 万字）"
          % (out, len(pages), total / 10000.0))
    return len(pages)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--html", action="append", required=True,
                    help="PRD 单文件 HTML，可重复给多个")
    ap.add_argument("--out-dir", default=".", help="md 输出目录（默认当前目录）")
    ap.add_argument("--check", action="store_true", help="只探测页数，不写文件")
    a = ap.parse_args()

    print("导出 PRD 规格为 Markdown%s" % ("（仅探测）" if a.check else ""))
    ok = 0
    for h in a.html:
        if export_one(h, a.out_dir, a.check):
            ok += 1
    print("完成：%d / %d" % (ok, len(a.html)))
    sys.exit(0 if ok == len(a.html) else 1)


if __name__ == "__main__":
    import _compat as _c   # 控制台编码兜底（Windows 默认 cp936 编不出 ✓ ✗）
    _c.init()
    main()
