#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""平台适配层。团队里 Windows 占多数，这个文件专门收所有「Windows 上会不一样」的地方。

用法（在每个命令行脚本的入口调一次）：

    import _compat
    _compat.init()

init() 做三件事：
  1. Windows 控制台编码兜底 —— 默认 cp936 编不出 ✓ ✗ ⚠，会直接抛 UnicodeEncodeError
  2. 把 sys.stdout 设成行缓冲，Windows 下 print 不 flush 会卡顺序
  3. 什么都不改，非 Windows 上是个空操作

其余函数给各脚本按需取用：
  tmpdir()        跨平台临时目录（不要写死 /tmp）
  kill_pid()      跨平台结束进程
  python_cmd()    提示里该写 python 还是 python3
  run_text()      跑子进程并按 utf-8 解码输出（Windows 默认按 cp936 解会乱码）
  path_hint()     把 posix 风格路径换成当前平台的显示方式
"""

import os
import platform
import subprocess
import sys
import tempfile

IS_WIN = platform.system() == "Windows"
IS_MAC = platform.system() == "Darwin"


# ---------------------------------------------------------------- 控制台

def init():
    """入口调用。除了 Windows 的控制台兜底，别的什么都不做。"""
    if not IS_WIN:
        return
    for stream in (sys.stdout, sys.stderr):
        try:
            # 保留控制台原编码（cp936 里中文本身没问题），
            # 只把编不出来的字符换成 ?，别让 print 抛异常把整个脚本打死
            stream.reconfigure(errors="replace")
        except Exception:  # noqa: BLE001
            pass
        try:
            if hasattr(stream, "reconfigure"):
                stream.reconfigure(line_buffering=True)
        except Exception:  # noqa: BLE001
            pass


def console_is_utf8():
    """控制台是不是已经能正确显示 ✓ ✗ 这类符号。"""
    enc = (getattr(sys.stdout, "encoding", "") or "").lower()
    return "utf" in enc


def symbol(name):
    """按控制台能力给符号：能显示就给图形符号，否则给 ASCII。"""
    ok = console_is_utf8()
    return {
        "ok": "✓" if ok else "[OK]",
        "fail": "✗" if ok else "[X]",
        "warn": "⚠" if ok else "[!]",
        "arrow": "→" if ok else "->",
        "bullet": "·" if ok else "-",
    }.get(name, "")


# ---------------------------------------------------------------- 路径

def tmpdir():
    """跨平台临时目录。Windows 上是 %TEMP%，POSIX 上是 /tmp（或 $TMPDIR）。"""
    d = tempfile.gettempdir()
    try:
        os.makedirs(d, exist_ok=True)
    except Exception:  # noqa: BLE001
        pass
    return d


def tmpfile(name):
    return os.path.join(tmpdir(), name)


def path_hint(p):
    """显示用：Windows 上把 / 换成 \\，其它平台原样。"""
    if not p:
        return p
    return p.replace("/", "\\") if IS_WIN else p


def file_url(path, query=None):
    """本地文件路径 → 浏览器能打开的 file:// URL。

    Windows 上 "file://" + "C:\\a\\b.html" = "file://C:\\a\\b.html" 是错的，
    浏览器会当成主机名 C 去找。必须写成 file:///C:/a/b.html。
    路径里的中文和空格也要 percent-encode，否则 Chrome 打不开。
    """
    import urllib.parse
    p = os.path.abspath(os.path.expanduser(path))
    # 两种分隔符都换掉：别指望 os.sep 一定是错的（跨平台传路径时会踩）
    p = p.replace("\\", "/")
    if IS_WIN and not p.startswith("/"):
        p = "/" + p                      # C:/x -> /C:/x
    url = "file://" + urllib.parse.quote(p, safe="/:")
    if query:
        url += ("&" if "?" in url else "?") + query
    return url


# ---------------------------------------------------------------- 进程

def kill_pid(pid, force=True):
    """结束一个进程。返回 (成功?, 说明)。"""
    if IS_WIN:
        args = ["taskkill", "/PID", str(pid)]
        if force:
            args.append("/F")
        try:
            r = subprocess.run(args, capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=10)
            return r.returncode == 0, (r.stderr or r.stdout or "").strip()
        except Exception as exc:  # noqa: BLE001
            return False, str(exc)
    import signal
    try:
        os.kill(int(pid), signal.SIGTERM)
        return True, ""
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)


def kill_by_port_cmd(port):
    """给用户的兜底命令（pid 文件丢了时用）。"""
    if IS_WIN:
        return ('for /f "tokens=2" %%i in (\'netstat -ano ^| findstr :%d\') '
                'do taskkill /PID %%i /F' % port)
    return "pkill -f 'remote-debugging-port=%d'" % port


# ---------------------------------------------------------------- 子进程

def run_text(args, timeout=30, **kw):
    """跑子进程并按 utf-8 解码。

    Windows 上 text=True 不加 encoding 会按 cp936 解，中文输出直接乱码或报错；
    cnb / git 这类工具输出都是 utf-8。
    """
    kw.setdefault("capture_output", True)
    kw.setdefault("timeout", timeout)
    kw.setdefault("encoding", "utf-8")
    kw.setdefault("errors", "replace")
    return subprocess.run(args, **kw)


def python_cmd():
    """提示语里该写哪个命令。Windows 上一般没有 python3 这个入口。"""
    return "python" if IS_WIN else "python3"


def rel(path):
    """提示用的相对路径（统一用 /，跨平台都能贴进命令行）。"""
    return path.replace(os.sep, "/")
