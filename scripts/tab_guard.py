#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tab_guard.py —— 标签页生命周期管理：只借不占，用完就关。

为什么单独一个模块：`vendor_cdp.py` 是 browser-automation-cdp 的上游副本，
保持原样才方便日后对比更新；标签页回收是本 skill 自己的纪律，放这里。

一条原则：**只关自己开的页面，绝不碰用户正在看的那个。**

三个常用动作：

    from tab_guard import Workspace
    with Workspace(port=9222) as w:          # 开一个专用标签页
        w.navigate(url)                      # w.client 是 CDPClient
        w.close_extra()                      # 点链接/弹窗跑出来的新页，随手收掉
    # 退出 with 时自动关闭（异常退出也关）

环境变量：
    PRD_KEEP_TAB=1   开着不关，便于人工接手调试（默认关闭）

命令行清理（不占用标签页，直接操作浏览器）：
    python scripts/cdp_tabs.py list
    python scripts/cdp_tabs.py close --blank
    python scripts/cdp_tabs.py close --url-contains admin
    python scripts/cdp_tabs.py close --all-but <targetId>
"""

import atexit
import json
import os
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import cdp_boot  # noqa: E402


def _http(port, path, method="GET", timeout=3.0, host="127.0.0.1"):
    url = "http://%s:%d%s" % (host, port, path)
    req = urllib.request.Request(url, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8", "replace")
    return body


def list_pages(port=9222, host="127.0.0.1"):
    """当前所有页面标签：[(id, url, title), ...]"""
    raw = _http(port, "/json/list", host=host)
    data = json.loads(raw)
    return [(t.get("id"), t.get("url") or "", t.get("title") or "")
            for t in data if t.get("type") == "page"]


def close_tab(port, target_id, host="127.0.0.1"):
    """关一个标签页。GET /json/close/{id} 是 CDP 的 HTTP 端点，不占 WebSocket。"""
    if not target_id:
        return False
    for method in ("GET", "PUT"):
        try:
            _http(port, "/json/close/%s" % target_id, method=method, host=host)
            return True
        except urllib.error.HTTPError:
            continue
        except Exception:  # noqa: BLE001
            continue
    return False


def close_extra(port, baseline_ids, keep_ids=(), host="127.0.0.1"):
    """关掉基线之外、也不在保留名单里的页面。

    基线 = 开工那一刻浏览器里已有的标签页。用这个当边界，才不会误伤
    用户自己的页面；点「查看」弹出来的新页、window.open 出来的新窗口，
    都在基线之外，会被收掉。
    """
    base = set(baseline_ids or ())
    keep = set(keep_ids or ())
    closed = []
    for tid, url, title in list_pages(port, host):
        if tid in base or tid in keep:
            continue
        if close_tab(port, tid, host):
            closed.append((tid, url, title))
    return closed


class Workspace(object):
    """一个由本进程负责的标签页。用完必须关（with 语句自动关）。

    用法：
        with Workspace(port=9222) as w:
            w.navigate("https://example.com")
            w.client.evaluate("document.title")
    """

    def __init__(self, port=9222, host="127.0.0.1", url="about:blank",
                 reuse=False, keep=None, timeout=30):
        self.port = port
        self.host = host
        self.url = url
        self.reuse = reuse
        self.keep = (os.environ.get("PRD_KEEP_TAB") == "1") if keep is None else keep
        self.timeout = timeout
        self.client = None
        self.target_id = None
        self.baseline = []      # 开工前的标签页，作为「不是我开的」边界
        self._closed = False
        self._atexit_hooked = False

    # ---------- 生命周期 ----------
    def __enter__(self):
        self.open()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False

    def open(self):
        cdp = cdp_boot.load()
        try:
            self.client = cdp.CDPClient(port=self.port, timeout=self.timeout)
        except TypeError:
            self.client = cdp.CDPClient()

        self.baseline = [p[0] for p in list_pages(self.port, self.host)]

        if self.reuse:
            pages = list_pages(self.port, self.host)
            if pages:
                self.target_id = pages[0][0]
                self.client.connect_page(self.target_id)
                self._hook_atexit()
                return self

        self.client.connect_browser()
        r = self.client.send("Target.createTarget", {"url": self.url or "about:blank"})
        tid = (r or {}).get("targetId")
        self.client.close()
        if not tid:
            raise RuntimeError("新建标签页失败：%r" % (r,))
        time.sleep(0.25)
        self.client.connect_page(tid)
        self.target_id = tid
        self._hook_atexit()
        return self

    def close(self):
        """关掉自己开的页（keep=True 时保留），并断开 WebSocket。可重复调用。

        顺手把「本次跑出来的其他新页」一起收掉：window.open / target=_blank
        弹出来的页不属于基线，留着就是泄漏——尤其是脚本抛异常时，那些页
        根本没人会去关。
        """
        if self._closed:
            return
        self._closed = True
        try:
            if self.target_id and self.baseline:
                close_extra(self.port, self.baseline, keep_ids={self.target_id}, host=self.host)
        except Exception:  # noqa: BLE001
            pass
        try:
            if self.client:
                self.client.close()
        except Exception:  # noqa: BLE001
            pass
        if self.target_id and not self.keep and self.target_id not in self.baseline:
            close_tab(self.port, self.target_id, self.host)

    def _hook_atexit(self):
        """脚本中途抛异常、sys.exit 都不怕：进程退出时兜底关一次。"""
        if self._atexit_hooked:
            return
        self._atexit_hooked = True
        atexit.register(self.close)

    # ---------- 便捷动作 ----------
    def navigate(self, url, timeout=30.0):
        return self.client.navigate(url, timeout=timeout)

    def evaluate(self, expression, return_by_value=True):
        return self.client.evaluate(expression, return_by_value=return_by_value)

    def close_extra(self):
        """把点击后新冒出来的页面收掉（保留自己这一个）。"""
        return close_extra(self.port, self.baseline, keep_ids={self.target_id}, host=self.host)

    def pages(self):
        return list_pages(self.port, self.host)

    def __repr__(self):
        return "<Workspace port=%d target=%s keep=%s>" % (self.port, self.target_id, self.keep)
