#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""起一个带调试端口的 Chrome，给实拍核对用。

    python3 launch_chrome.py                 # headless，端口 9222，起完就返回
    python3 launch_chrome.py --headed        # 有界面（想自己看着它点的时候）
    python3 launch_chrome.py --port 9333     # 换端口
    python3 launch_chrome.py --stop          # 关掉

为什么要单起一个：占用你日常 Chrome 的配置目录会互相打架，所以固定用临时 profile
（默认放在系统临时目录下的 prd-chrome-profile，可 --profile 改）。

找不到 Chrome 时：用 --path 指定可执行文件，或直接告诉我路径。
"""

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import time
import urllib.request

import _compat

CANDIDATES = {
    "Darwin": [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
        "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
        "/Applications/Google Chrome Canary.app/Contents/MacOS/Google Chrome Canary",
    ],
    "Windows": [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ],
    "Linux": [
        "/usr/bin/google-chrome", "/usr/bin/google-chrome-stable",
        "/usr/bin/chromium", "/usr/bin/chromium-browser", "/snap/bin/chromium",
    ],
}


def find_chrome(explicit=None):
    if explicit:
        if os.path.exists(explicit):
            return explicit
        sys.exit("✗ 你给的路径不存在：%s" % explicit)
    for p in CANDIDATES.get(platform.system(), []):
        if os.path.exists(p):
            return p
    for name in ("google-chrome", "chromium", "chrome", "msedge"):
        p = shutil.which(name)
        if p:
            return p
    sys.exit("✗ 没找到 Chrome。用 --path 指定：\n  %s launch_chrome.py --path \"<浏览器可执行文件>\""
             % _compat.python_cmd())


def alive(port, host="127.0.0.1"):
    try:
        info = json.loads(urllib.request.urlopen(
            "http://%s:%d/json/version" % (host, port), timeout=1.5).read())
        return info.get("Browser", "")
    except Exception:
        return ""


def stop(port, profile):
    pidf = os.path.join(profile, "pid")
    killed = False
    if os.path.exists(pidf):
        try:
            pid = int(open(pidf).read().strip())
            ok, msg = _compat.kill_pid(pid)
            killed = ok
            print(("已结束 pid %d" if ok else "按 pid 停止失败(%s)，pid %d") %
                  ((pid,) if ok else (msg, pid)))
        except Exception as e:
            print("读 pid 文件失败：%s" % e)
    if not killed:
        print("没找到 pid 文件（%s）。手动关：" % _compat.path_hint(pidf))
        print("  %s" % _compat.kill_by_port_cmd(port))
    return 0


def main():
    ap = argparse.ArgumentParser(description="起一个带调试端口的 Chrome")
    ap.add_argument("--port", type=int, default=9222)
    ap.add_argument("--path", help="Chrome 可执行文件路径")
    ap.add_argument("--profile", default=_compat.tmpfile("prd-chrome-profile"),
                    help="临时配置目录（默认系统临时目录下）")
    ap.add_argument("--headed", action="store_true", help="有界面（默认 headless）")
    ap.add_argument("--keep-profile", action="store_true", help="保留上次的 profile")
    ap.add_argument("--stop", action="store_true", help="停掉这个端口上的 Chrome")
    a = ap.parse_args()

    if a.stop:
        return stop(a.port, a.profile)

    ver = alive(a.port)
    if ver:
        print("端口 %d 上已经有 Chrome 在跑：%s —— 直接用，不重复启动" % (a.port, ver))
        return 0

    chrome = find_chrome(a.path)
    if not a.keep_profile and os.path.isdir(a.profile):
        shutil.rmtree(a.profile, ignore_errors=True)
    os.makedirs(a.profile, exist_ok=True)

    args = [chrome,
            "--remote-debugging-port=%d" % a.port,
            "--user-data-dir=%s" % a.profile,
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-background-networking",
            "--disable-features=Translate,MediaRouter",
            "--window-size=1680,1200",
            "about:blank"]

    # 受限环境（容器 / 沙箱 / 某些受管机器）里 Chrome 自己的 sandbox 初始化会被拦，
    # 表现是「Failed to initialize sandbox」然后 GPU 进程反复崩、最后 Goodbye。
    # 有界面模式同样需要这几个参数，不能只在 headless 时加。
    common = ["--no-sandbox", "--disable-setuid-sandbox",
              "--disable-software-rasterizer", "--in-process-gpu"]
    if a.headed:
        args[1:1] = common + ["--disable-dev-shm-usage"]
    else:
        args[1:1] = ["--headless=new"] + common + ["--disable-gpu"]

    out = open(os.path.join(a.profile, "chrome.log"), "wb")
    p = subprocess.Popen(args, stdout=out, stderr=out,
                         start_new_session=(platform.system() != "Windows"))
    open(os.path.join(a.profile, "pid"), "w").write(str(p.pid))

    for _ in range(40):
        time.sleep(0.25)
        ver = alive(a.port)
        if ver:
            print("✓ Chrome 已就绪：%s" % ver)
            print("  端口 %d · pid %d · profile %s" % (a.port, p.pid, a.profile))
            print("  关掉：%s launch_chrome.py --stop --port %d"
                  % (_compat.python_cmd(), a.port))
            return 0
    print("✗ 等了 10 秒端口还没起来，看日志：%s"
          % _compat.path_hint(os.path.join(a.profile, "chrome.log")))
    return 1


if __name__ == "__main__":
    _compat.init()
    sys.exit(main())
