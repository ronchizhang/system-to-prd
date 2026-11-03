#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""账号密码登录测试环境后台，换出 token 供后续脚本使用。

凭据只从环境变量 PRD_USER / PRD_PASS 读，或运行时交互输入；
不接受命令行明文（会留在 shell history 与进程列表里）。

token 写到 0600 的临时文件（默认在系统临时目录），**不写进项目目录**。

用法：
    export PRD_USER='13800000000' PRD_PASS='...'
    python3 login.py --url https://test1x.example.com/login \\
        --api https://test1x-gateway.example.com \\
        --path /demo/login/loginUser

    # 密码走 MD5（多数老后台）
    python3 login.py ... --md5

    # 换一个用户要求的字段名
    python3 login.py ... --payload '{"account":"{user}","password":"{pass}","loginType":1}'

    # 登录后验证 token 并打印可用菜单数
    python3 login.py ... --verify /demo/menu/action/menuTree

退出码：0 成功 / 2 缺凭据 / 3 测试环境校验失败 / 4 登录失败 / 5 token 无效
"""

import argparse
import _compat
import getpass
import hashlib
import json
import os
import stat
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_OUT = _compat.tmpfile("prd_token.json")


def die(code, msg):
    print("✗ " + msg, file=sys.stderr)
    sys.exit(code)


def strip_proxy():
    for k in ("http_proxy", "https_proxy", "all_proxy",
              "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
        os.environ.pop(k, None)
    os.environ["NO_PROXY"] = "*"


def guard(url):
    """调用 check_test_env.py，非 0 直接终止。"""
    p = os.path.join(HERE, "check_test_env.py")
    if not os.path.exists(p):
        print("⚠ 找不到 check_test_env.py，跳过域名校验（不安全），建议先补回", file=sys.stderr)
        return
    r = _compat.run_text([sys.executable, p, url], timeout=20)
    sys.stdout.write(r.stdout)
    if r.returncode != 0:
        sys.stderr.write(r.stderr)
        die(3, "目标不是测试环境，任务终止（这是硬约束，不可跳过）")


def get_creds(args):
    user = args.user or os.environ.get("PRD_USER") or ""
    pwd = os.environ.get("PRD_PASS") or ""
    if not user:
        if sys.stdin.isatty():
            user = input("账号: ").strip()
        else:
            die(2, "缺少账号：设置 PRD_USER 环境变量，或在终端里交互输入")
    if not pwd:
        if sys.stdin.isatty():
            pwd = getpass.getpass("密码（不回显）: ")
        else:
            die(2, "缺少密码：设置 PRD_PASS 环境变量，或在终端里交互输入")
    if not user or not pwd:
        die(2, "账号或密码为空")
    return user, pwd


def build_payload(tpl, user, pwd):
    """把 {user}/{pass} 填进模板；模板里密码字段本身可要求 md5。"""
    try:
        raw = tpl.format(user=user, pass_=pwd, passmd5=hashlib.md5(pwd.encode()).hexdigest(),
                         user_=user)
    except (KeyError, IndexError) as e:
        die(2, "payload 模板里只能出现 {user} {pass_} {passmd5}，出错的占位符：%s" % e)
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        die(2, "payload 模板不是合法 JSON：%s" % e)


def post(url, body, token=None, timeout=25):
    hdr = {"Content-Type": "application/json"}
    if token:
        hdr["authToken"] = token
        hdr["lang"] = "zh"
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=hdr)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "ignore"))
    except urllib.error.HTTPError as e:
        return {"_http": e.code, "_body": e.read()[:400].decode("utf-8", "ignore")}
    except Exception as e:
        return {"_err": str(e)[:200]}


def find_token(obj, wanted=("token", "authToken", "accessToken", "jwt")):
    """递归找 token，不假设层级。"""
    if isinstance(obj, dict):
        for k in wanted:
            v = obj.get(k)
            if isinstance(v, str) and len(v) > 12:
                return v
        for v in obj.values():
            t = find_token(v, wanted)
            if t:
                return t
    elif isinstance(obj, list):
        for v in obj:
            t = find_token(v, wanted)
            if t:
                return t
    return None


def save_token(path, token, user, api):
    d = {"token": token, "user": user, "api": api,
         "note": "runtime credential, 0600, do not copy into project dirs"}
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    try:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass
    if _compat.IS_WIN:
        print("（Windows 上文件权限靠目录 ACL，chmod 只保证不是只读）", file=sys.stderr)
    return path


def main():
    ap = argparse.ArgumentParser(description="登录测试环境并保存 token")
    ap.add_argument("--url", required=True, help="登录页地址（用于域名守门）")
    ap.add_argument("--api", required=True, help="网关根地址，如 https://test1x-gateway.example.com")
    ap.add_argument("--path", default="/demo/login/loginUser", help="登录接口路径")
    ap.add_argument("--user", help="账号；不传则读 PRD_USER 或交互输入")
    ap.add_argument("--md5", action="store_true", help="密码按 MD5 提交")
    ap.add_argument("--payload", help="自定义 JSON 模板，可用 {user} {pass_} {passmd5}")
    ap.add_argument("--out", default=DEFAULT_OUT, help="token 输出文件（会被设为 0600）")
    ap.add_argument("--verify", help="登录后调这个接口验证 token（POST，空 body）")
    ap.add_argument("--skip-guard", action="store_true",
                    help="跳过域名校验（仅当用户已明确确认为测试环境时）")
    args = ap.parse_args()

    strip_proxy()
    if not args.skip_guard:
        guard(args.url)
    else:
        print("⚠ 已跳过域名校验（--skip-guard）", file=sys.stderr)

    user, pwd = get_creds(args)
    pwd_for_body = hashlib.md5(pwd.encode()).hexdigest() if args.md5 else pwd

    if args.payload:
        body = build_payload(args.payload, user, pwd)
        # 模板里若写了 {pass_} 且开了 --md5，替换成 md5 值
        if args.md5:
            body = json.loads(json.dumps(body, ensure_ascii=False)
                              .replace(pwd, pwd_for_body))
    else:
        body = {"account": user, "password": pwd_for_body, "phone": user, "loginName": user}

    url = args.api.rstrip("/") + args.path
    print("登录 %s ..." % url)
    j = post(url, body)
    code = j.get("statusCode") or j.get("code")
    if j.get("_http") or j.get("_err"):
        die(4, "登录请求失败：%s" % (j.get("_body") or j.get("_err")))
    if code not in ("B00000", "00000", "200", 200, "0", 0, "SUCCESS", None):
        die(4, "登录被拒：code=%s msg=%s" % (code, j.get("message") or j.get("msg")))

    tok = find_token(j)
    if not tok:
        die(4, "登录返回里找不到 token，实际返回：%s" % json.dumps(j, ensure_ascii=False)[:400])

    p = save_token(args.out, tok, user, args.api)
    print("✓ token 已保存：%s（0600，长度 %d）" % (p, len(tok)))

    if args.verify:
        vurl = args.api.rstrip("/") + args.verify
        v = post(vurl, {}, token=tok)
        vc = v.get("statusCode") or v.get("code")
        data = v.get("data")
        n = len(data) if isinstance(data, list) else (
            len(data.get("list", [])) if isinstance(data, dict) else 0)
        if vc in ("B00000", "00000", "200", 200, "0", 0, "SUCCESS", None):
            print("✓ token 可用：%s → %s，返回条目 %d" % (args.verify, vc, n))
        else:
            die(5, "token 验证失败：%s %s" % (vc, v.get("message")))

    print("\n后续脚本：")
    print("  %s harvest.py enums --token-file %s --keys ..."
          % (_compat.python_cmd(), _compat.path_hint(p)))
    print("用完记得 rm %s" % p)


if __name__ == "__main__":
    import _compat as _c   # 控制台编码兜底（Windows 默认 cp936 编不出 ✓ ✗）
    _c.init()
    main()
