#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""按顺序找一个能用的 CDP 客户端，找到哪个用哪个。

查找顺序：
  1. 包内 vendor_cdp.py   —— 打包自带，装到干净机器也能跑（推荐）
  2. browser-automation-cdp skill —— 本机装了那个 skill 时复用，省一份副本

两个模块的 CDPClient 接口一致，所以调用方不用关心是哪一个。
"""

import importlib
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def load():
    if os.path.exists(os.path.join(HERE, "vendor_cdp.py")):
        if HERE not in sys.path:
            sys.path.insert(0, HERE)
        return importlib.import_module("vendor_cdp")

    ext = os.path.expanduser("~/.workbuddy/skills/browser-automation-cdp/scripts")
    if os.path.isdir(ext):
        if ext not in sys.path:
            sys.path.insert(0, ext)
        return importlib.import_module("cdp")

    raise ImportError(
        "找不到 CDP 客户端：包内缺 vendor_cdp.py，也没有装 browser-automation-cdp skill。\n"
        "  修法：把 vendor_cdp.py 放回 scripts/ 目录，或安装 browser-automation-cdp skill。"
    )


def port_open(port=9222, host="127.0.0.1", timeout=1.5):
    """Chrome 是否已经在这个端口上等着。"""
    import urllib.request
    try:
        urllib.request.urlopen("http://%s:%d/json/version" % (host, port), timeout=timeout)
        return True
    except Exception:
        return False


def hint(port=9222):
    return ("Chrome 没开调试端口。先跑：\n"
            "  python3 %s --port %d\n"
            "（或手动启动：Chrome 加 --headless=new --no-sandbox "
            "--remote-debugging-port=%d）" % (os.path.join(HERE, "launch_chrome.py"), port, port))
