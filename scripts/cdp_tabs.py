#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cdp_tabs.py —— 看和清浏览器标签页，专治「跑完一轮 PRD，浏览器里堆了一排标签」。

为什么需要：采集阶段一个页面要抓很多帧（列表 / 详情 / 弹窗 / 页签），
点「查看」还可能再弹一个新页。一个页面一个标签不关，几十个页面下来内存就上去了。
脚本内部已经用 tab_guard 自动回收，这个命令是给「已经堆了」「想先看看」用的。

用法：
    python scripts/cdp_tabs.py list
    python scripts/cdp_tabs.py list --json
    python scripts/cdp_tabs.py close --blank                 # 关所有空白页（最常见）
    python scripts/cdp_tabs.py close --url-contains admin  # 关某类页
    python scripts/cdp_tabs.py close --all-but <targetId>     # 只留一个
    python scripts/cdp_tabs.py close --url-contains xxx --dry  # 只看会关哪些

安全边界：默认**不关**非空白页；要关带内容的页必须显式给 --url-contains 或 --all-but。
"""

import argparse
import json
import sys
import urllib.error

import tab_guard

BLANK_PREFIX = ("about:blank", "chrome://newtab", "chrome://new-tab-page",
                "edge://newtab", "devtools://")


def is_blank(url):
    u = (url or "").strip()
    return (not u) or any(u.startswith(p) for p in BLANK_PREFIX)


def pick_targets(pages, args):
    if args.all_but:
        return [p for p in pages if p[0] != args.all_but]
    if args.url_contains:
        return [p for p in pages if args.url_contains.lower() in (p[1] or "").lower()]
    if args.blank:
        return [p for p in pages if is_blank(p[1])]
    return []


def cmd_list(args):
    pages = tab_guard.list_pages(args.port, args.host)
    if args.json:
        print(json.dumps([{"id": i, "url": u, "title": t} for i, u, t in pages],
                         ensure_ascii=False, indent=2))
        return 0
    blanks = sum(1 for p in pages if is_blank(p[1]))
    print("共 %d 个标签页（其中空白页 %d 个）" % (len(pages), blanks))
    for tid, url, title in pages:
        print("  %-10s %-42s %s" % (tid[:8], (title or "")[:40], (url or "")[:70]))
    if blanks >= 3:
        print("\n提示：空白页已经堆到 %d 个，跑一次 `python scripts/cdp_tabs.py close --blank` 收一下。" % blanks)
    return 0


def cmd_close(args):
    pages = tab_guard.list_pages(args.port, args.host)
    targets = pick_targets(pages, args)
    if not targets:
        print("没有匹配的标签页（共 %d 个）。要看清单：python scripts/cdp_tabs.py list" % len(pages))
        return 0
    if args.dry:
        print("将关闭 %d 个（--dry，未执行）：" % len(targets))
        for tid, url, title in targets:
            print("  %-10s %-40s %s" % (tid[:8], (title or "")[:38], (url or "")[:70]))
        return 0
    closed = 0
    for tid, url, title in targets:
        if tab_guard.close_tab(args.port, tid, args.host):
            closed += 1
            print("  ✓ %-8s %s" % (tid[:8], (url or title or "")[:70]))
        else:
            print("  ✗ %-8s 关不掉，可能已经不存在" % tid[:8])
    left = len(tab_guard.list_pages(args.port, args.host))
    print("\n关闭 %d 个，剩 %d 个。" % (closed, left))
    return 0


def main():
    ap = argparse.ArgumentParser(description="查看 / 清理 Chrome 标签页")
    ap.add_argument("--port", type=int, default=9222)
    ap.add_argument("--host", default="127.0.0.1")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list", help="列出标签页")
    p_list.add_argument("--json", action="store_true")

    p_close = sub.add_parser("close", help="关闭标签页（默认什么都不关，必须给条件）")
    p_close.add_argument("--blank", action="store_true", help="关所有空白页")
    p_close.add_argument("--url-contains", default="", help="关 URL 含该关键字的页")
    p_close.add_argument("--all-but", default="", help="除这个 targetId 外全关")
    p_close.add_argument("--dry", action="store_true", help="只列出将要关闭的，不执行")

    args = ap.parse_args()
    if args.cmd == "close" and not (args.blank or args.url_contains or args.all_but):
        print("必须指定 --blank / --url-contains / --all-but 之一。"
              "\n先看清单：python scripts/cdp_tabs.py list")
        return 1
    try:
        if args.cmd == "list":
            return cmd_list(args)
        return cmd_close(args)
    except (urllib.error.URLError, ConnectionError, OSError) as e:
        # 浏览器没开 / 端口没在监听，是最常见的失败。直接说人话，
        # 别把 urllib 的堆栈甩给人看 —— 那不是使用者该读的东西。
        import cdp_boot
        print("连不上端口 %d（%s）。\n\n%s" % (args.port, e, cdp_boot.hint(args.port)))
        return 2


if __name__ == "__main__":
    import _compat as _c
    _c.init()
    sys.exit(main())
