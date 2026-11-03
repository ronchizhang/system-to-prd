#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""测试环境域名守门员 —— system-to-prd 的强制前置检查。

硬约束：本 skill 只允许对**测试环境**操作。判定标准是域名里必须有一段
label 以 test 开头（如 test、test1、test-api、test1enterprise）。
生产域名（哪怕长得像测试）一律拒绝。

用法：
    python3 check_test_env.py https://test1enterprise.example.com/home
    python3 check_test_env.py https://a.com https://b.com     # 批量
    python3 check_test_env.py --allow-local http://localhost:3000

退出码：
    0  全部通过
    1  存在不合规 URL（必须终止，不得继续抓取）
    2  参数错误
"""

import argparse
import sys
from urllib.parse import urlparse

LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}

PASS_TMPL = "  PASS  {url}\n        理由：域名段 '{label}' 以 test 开头"
FAIL_NOTEST = ("  FAIL  {url}\n"
               "        理由：域名 '{host}' 中没有任何一段以 test 开头。\n"
               "        本 skill 只允许操作测试环境。请确认是否拿错了地址。")
FAIL_LOCAL = ("  FAIL  {url}\n"
              "        理由：'{host}' 是本地地址，未通过 --allow-local 放行。\n"
              "        如确属本地开发服务，加 --allow-local 重试。")
FAIL_SCHEME = ("  FAIL  {url}\n"
               "        理由：只接受 http/https，'{scheme}' 不是可访问的测试环境。")
FAIL_BADURL = "  FAIL  {url}\n        理由：无法解析为合法 URL。"


def judge(url, allow_local=False):
    """返回 (ok, message) 。ok=True 表示通过。"""
    try:
        p = urlparse(url.strip())
    except Exception:
        return False, FAIL_BADURL.format(url=url)

    if p.scheme not in ("http", "https"):
        return False, FAIL_SCHEME.format(url=url, scheme=p.scheme or "(空)")

    host = (p.hostname or "").lower()
    if not host:
        return False, FAIL_BADURL.format(url=url)

    if host in LOCAL_HOSTS:
        if allow_local:
            return True, "  PASS  %s\n        理由：本地地址已由 --allow-local 放行" % url
        return False, FAIL_LOCAL.format(url=url, host=host)

    # 只看 host，不看路径与查询串 —— 防止 /test/xxx 这种路径混进来
    for label in host.split("."):
        if label.startswith("test"):
            return True, PASS_TMPL.format(url=url, label=label)

    return False, FAIL_NOTEST.format(url=url, host=host)


def main():
    ap = argparse.ArgumentParser(description="校验目标 URL 是否为测试环境")
    ap.add_argument("urls", nargs="*", help="待校验的 URL")
    ap.add_argument("--allow-local", action="store_true",
                    help="放行 localhost / 127.0.0.1")
    args = ap.parse_args()

    if not args.urls:
        ap.print_help()
        return 2

    print("== 测试环境校验（域名段须以 test 开头）==")
    bad = []
    for u in args.urls:
        ok, msg = judge(u, args.allow_local)
        print(msg)
        if not ok:
            bad.append(u)

    print()
    if bad:
        print("结果：%d/%d 未通过 —— **立即终止，不得登录、不得抓取任何页面**"
              % (len(bad), len(args.urls)))
        print("请向用户索要测试环境地址，不要擅自换用生产域名。")
        return 1

    print("结果：全部通过，可以进入下一步（索取凭据）。")
    return 0


if __name__ == "__main__":
    import _compat as _c   # 控制台编码兜底（Windows 默认 cp936 编不出 ✓ ✗）
    _c.init()
    sys.exit(main())
