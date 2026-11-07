#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""测试环境域名提示器 —— system-to-prd 的前置提示。

**定位：提示，不是安全边界。**
它拦不住真想绕的人——不跑脚本、看了提示照做，都能绕。所以这里不做严防：
严到卡流程，人的反应不是「我改地址」，是「这脚本真烦，跳过吧」。
它只做一件事：**把「你现在要去动哪个域名」摆到明面上**，让人自己看一眼。

判定分三档：

  PASS        host 某段 label 里有一个**完整的环境词**
              test.xx.com · api-test.xx.com · test1client.xx.com

  PASS 提示   label 里只是**局部含**环境词，看着像其实不是
              contest / latest / device / preview / site（含 sit）
              照样放行，但会附一句 —— 这才叫「弱弱的限制」

  FAIL        host 里连环境词的字都没有
              demobackstage.xx.com

环境词：test / testing / uat / sit / dev / stg / stage / staging /
        pre / preprod / qa / sandbox / demo / beta / gray / canary

用法：
    python3 check_test_env.py https://test1client.example.com/home
    python3 check_test_env.py https://a.com https://b.com     # 批量
    python3 check_test_env.py --allow-local http://localhost:3000

退出码：0 通过（含带提示的通过）/ 1 连环境词都没有 / 2 参数错误
"""

import argparse
import re
import sys
from urllib.parse import urlparse

LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}

ENV_WORDS = (
    "test", "testing", "uat", "sit", "dev", "stg", "stage", "staging",
    "pre", "preprod", "qa", "sandbox", "demo", "beta", "gray", "canary",
)

# 只有这几个词参与「局部含」的弱匹配。
# 其余（stage / pre / stg…）太容易藏在普通词里——backstage、preview、presto，
# 而 demobackstage 恰恰是自家后台的域名。弱匹配放到这种词上等于没限制。
WEAK_WORDS = ("test", "testing", "uat", "qa", "dev", "sit")

PASS_CLEAN = ("  PASS  {url}\n"
              "        环境词：'{label}' 里的 '{word}'")
PASS_WEAK = ("  PASS  {url}\n"
             "        提醒：'{label}' 只是含 '{env}' 这两个字，不是完整的环境词"
             "（contest / latest / device / site 都长这样）。\n"
             "        不拦你，但请自己看一眼——这真是测试环境吗？")
FAIL_NOWORD = ("  FAIL  {url}\n"
               "        域名 '{host}' 里连环境词的字都没有"
               "（test/uat/sit/dev/staging/pre/qa…）。\n"
               "        是不是拿错了地址？确认后再跑一次。")
FAIL_LOCAL = ("  FAIL  {url}\n"
              "        '{host}' 是本地地址，未通过 --allow-local 放行。\n"
              "        如确属本地开发服务，加 --allow-local 重试。")
FAIL_SCHEME = ("  FAIL  {url}\n"
               "        只接受 http/https，'{scheme}' 不是可访问的测试环境。")
FAIL_BADURL = "  FAIL  {url}\n        无法解析为合法 URL。"


def split_words(label):
    """label 按分隔符切词；没有分隔符时整段当一个词。"""
    return [w for w in re.split(r"[-_]", label) if w]


def clean_hit(label):
    """完整环境词命中（含 test1 / test1client 这种命名习惯），返回命中的词。"""
    for w in split_words(label):
        for env in ENV_WORDS:
            if w == env:
                return w
            if re.fullmatch(r"%s(\d+)" % re.escape(env), w):
                return w
    for env in ("test", "uat", "sit", "qa"):
        if re.match(r"^%s\d" % re.escape(env), label):
            return label
    return None


def weak_hit(label):
    """局部含环境词，返回 (词, 环境词)。只认 WEAK_WORDS。"""
    for w in split_words(label):
        for env in WEAK_WORDS:
            if env in w:
                return w, env
    return None, None


def judge(url, allow_local=False):
    """返回 (ok, message)。ok=True 表示放行（可能带提示）。"""
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
            return True, "  PASS  %s\n        本地地址已由 --allow-local 放行" % url
        return False, FAIL_LOCAL.format(url=url, host=host)

    # 只看 host，不看路径与查询串 —— 防止 /test/xxx 这种路径混进来
    weak = None
    for label in host.split("."):
        w = clean_hit(label)
        if w:
            return True, PASS_CLEAN.format(url=url, label=label, word=w)
        if weak is None:
            ww, env = weak_hit(label)
            if ww:
                weak = (label, ww, env)

    if weak:
        return True, PASS_WEAK.format(url=url, label=weak[0], env=weak[2])

    return False, FAIL_NOWORD.format(url=url, host=host)


def main():
    ap = argparse.ArgumentParser(description="提示目标 URL 是不是测试环境")
    ap.add_argument("urls", nargs="*", help="待校验的 URL")
    ap.add_argument("--allow-local", action="store_true",
                    help="放行 localhost / 127.0.0.1")
    args = ap.parse_args()

    if not args.urls:
        ap.print_help()
        return 2

    print("== 测试环境提示（不是门禁，自己看一眼）==")
    bad, warned = [], 0
    for u in args.urls:
        ok, msg = judge(u, args.allow_local)
        print(msg)
        if not ok:
            bad.append(u)
        elif "提醒" in msg:
            warned += 1

    print()
    if bad:
        print("结果：%d/%d 的域名里连环境词都没有。"
              % (len(bad), len(args.urls)))
        print("确认一下是不是拿错了地址；确实要跑，先跟对方确认这是测试环境。")
        return 1

    if warned:
        print("结果：全部放行，其中 %d 个带提醒——自己确认过再往下走。" % warned)
    else:
        print("结果：全部通过。下一步索取凭据（每次现要，不落盘）。")
    return 0


if __name__ == "__main__":
    import _compat as _c   # 控制台编码兜底（Windows 默认 cp936 编不出 ✓ ✗）
    _c.init()
    sys.exit(main())
