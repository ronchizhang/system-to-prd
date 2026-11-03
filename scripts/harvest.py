#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""五源采集工具：接口字典 / 单接口探测 / 前端 chunk 抽接口 / 后端代码读取。

四个子命令各对应一个源，输出统一 JSON，供 build_facts.py 与写作阶段消费。

    # 源2 接口：拉枚举字典（key 从前端 hook 记录里抄，或先跑 probe 看 listEnums 的 body）
    python3 harvest.py enums --token-file <临时目录>/prd_token.json \\
        --keys demo:fieldTextType,demo:fillParty -o enums.json

    # 源2 接口：调任意接口
    python3 harvest.py probe --token-file <临时目录>/prd_token.json \\
        --path /demo/form/group/list --body '{"id":"511..."}' -o groups.json

    # 源3 前端码：从本地 chunk 目录抽接口路径
    python3 harvest.py chunks --dir <chunk 目录> --match field -o fe_apis.json

    # 源4 后端码：读一个文件（代码仓库 或本地仓库都可）
    python3 harvest.py be --repo acme/events/form-service \\
        --path geo-backstage-app/src/.../FormFieldController.java -o be_ctrl.txt
    python3 harvest.py be --local /path/to/repo --path <相对路径> -o be_ctrl.txt
    python3 harvest.py be-list --repo <完整路径> --path <目录>

后端代码读取依赖 `cnb` CLI：
    export PATH="$HOME/.workbuddy/binaries/node/cli-connector-packages/bin:$PATH"
"""

import argparse
import _compat
import base64
import json
import os
import re
import subprocess
import shutil
import sys
import urllib.error
import urllib.request

def _find_cnb():
    """先看 PATH，再退回 WorkBuddy 连接器的默认安装位——不同机器两者不一定都有。"""
    p = shutil.which("cnb")
    if p:
        return p
    return os.path.expanduser("~/.workbuddy/binaries/node/cli-connector-packages/bin/cnb")


代码仓库 = _find_cnb()


# ---------------- 通用 ----------------

def strip_proxy():
    for k in ("http_proxy", "https_proxy", "all_proxy",
              "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
        os.environ.pop(k, None)
    os.environ["NO_PROXY"] = "*"


def make_url(a, api):
    base = (a.api or api or "").strip()
    if not base:
        sys.exit("✗ 不知道网关地址：token 文件里没有 api 字段，也没有传 --api。\n"
                 "  例：--api https://test1x-gateway.example.com")
    return base.rstrip("/") + a.path


def load_token(path):
    if not os.path.exists(path):
        sys.exit("✗ token 文件不存在：%s（先跑 login.py）" % path)
    if not _compat.IS_WIN and os.stat(path).st_mode & 0o077:
        print("⚠ token 文件权限过宽，建议 chmod 600 %s" % path, file=sys.stderr)
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    return d.get("token"), d.get("api", "")


def post(url, body, token, timeout=30):
    hdr = {"Content-Type": "application/json", "authToken": token or "", "lang": "zh"}
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=hdr)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "ignore"))
    except urllib.error.HTTPError as e:
        return {"_http": e.code, "_body": e.read()[:400].decode("utf-8", "ignore")}
    except Exception as e:
        return {"_err": str(e)[:200]}


def dump(obj, out):
    s = json.dumps(obj, ensure_ascii=False, indent=1)
    if out:
        os.makedirs(os.path.dirname(os.path.abspath(out)) or ".", exist_ok=True)
        with open(out, "w", encoding="utf-8") as f:
            f.write(s)
        print("→ %s（%.1f KB）" % (out, len(s.encode()) / 1024))
    else:
        print("\n（未指定 -o，仅显示前 1200 字符；要完整保存请加 -o 文件名.json）")
        print(s[:1200])


# ---------------- 子命令：enums ----------------

def cmd_enums(a):
    tok, api = load_token(a.token_file)
    keys = [k.strip() for k in a.keys.split(",") if k.strip()]
    if not keys:
        sys.exit("✗ --keys 为空")
    url = make_url(a, api)
    j = post(url, keys, tok)
    code = j.get("statusCode") or j.get("code")
    if j.get("_http") or j.get("_err"):
        sys.exit("✗ 请求失败：%s" % (j.get("_body") or j.get("_err")))
    if code not in ("B00000", "00000", "200", 200, "0", 0, "SUCCESS", None):
        sys.exit("✗ 返回异常：%s %s" % (code, j.get("message")))
    data = j.get("data") or {}
    flat = {}
    for k, v in data.items():
        short = k.split(":")[-1]
        flat[short] = v
        if v is None:
            print("  %-28s （空，key 可能拼错）" % short)
        elif isinstance(v, dict) and v and all(isinstance(x, str) for x in v.values()):
            print("  %-28s %d 项：%s" % (short, len(v), " / ".join(
                "%s=%s" % (a2, b2) for a2, b2 in v.items())))
        else:
            print("  %-28s %s" % (short, json.dumps(v, ensure_ascii=False)[:160]))
    dump(flat, a.out)


# ---------------- 子命令：probe ----------------

def cmd_probe(a):
    tok, api = load_token(a.token_file)
    body = {}
    if a.body:
        try:
            body = json.loads(a.body)
        except json.JSONDecodeError as e:
            sys.exit("✗ --body 不是合法 JSON：%s" % e)
    url = make_url(a, api)
    j = post(url, body, tok)
    code = j.get("statusCode") or j.get("code")
    data = j.get("data")
    n = len(data) if isinstance(data, list) else (
        len(data.get("list") or data.get("records") or []) if isinstance(data, dict) else 0)
    print("%s → %s %s（data 条目 %d）" % (a.path, code, j.get("message") or "", n))
    if isinstance(data, dict) and data:
        print("  keys: %s" % ", ".join(list(data.keys())[:20]))
    elif isinstance(data, list) and data and isinstance(data[0], dict):
        print("  [0] keys: %s" % ", ".join(list(data[0].keys())[:20]))
    if code not in ("B00000", "00000", "200", 200, "0", 0, "SUCCESS", None) and not a.keep:
        print("  提示：报 must not be null 时，回前端代码找真实 payload，不要逐个试参数名",
              file=sys.stderr)
    dump(j, a.out)


# ---------------- 子命令：chunks ----------------

API_RE = re.compile(r'["\'`](/(?:geo|api)[a-zA-Z0-9_/\-{}$.:]*)["\'`]')
URL_RE = re.compile(r'url\s*:\s*["\'`]([^"\'`]{4,80})["\'`]')
CN_RE = re.compile(r'["\'`]([\u4e00-\u9fa5][^"\'`]{0,40})["\'`]')


def cmd_chunks(a):
    if not os.path.isdir(a.dir):
        sys.exit("✗ 目录不存在：%s" % a.dir)
    files = [f for f in sorted(os.listdir(a.dir)) if f.endswith(".js")]
    if a.match:
        files = [f for f in files if a.match.lower() in f.lower()]
    if not files:
        sys.exit("✗ 没有匹配的 js 文件（--match 换关键词试试）")

    apis, texts = {}, {}
    for fn in files:
        p = os.path.join(a.dir, fn)
        try:
            s = open(p, encoding="utf-8", errors="ignore").read()
        except Exception as e:
            print("  跳过 %s：%s" % (fn, e), file=sys.stderr)
            continue
        for m in API_RE.finditer(s):
            apis.setdefault(m.group(1), []).append(fn)
        for m in URL_RE.finditer(s):
            u = m.group(1)
            if u.startswith("/"):
                apis.setdefault(u, []).append(fn)
        if a.texts:
            for m in CN_RE.finditer(s):
                t = m.group(1).strip()
                if t and t not in texts:
                    texts[t] = fn

    if a.prefix:
        pre = tuple(x.strip() for x in a.prefix.split(",") if x.strip())
        apis = {k: v for k, v in apis.items() if k.startswith(pre)}
        print("按前缀 %s 过滤后剩 %d 个" % (list(pre), len(apis)))

    print("扫描 %d 个文件，抽到 %d 个接口路径" % (len(files), len(apis)))
    if len(apis) > 40 and not a.prefix:
        print("  ⚠ 太多了：chunk 会把整个 app 的 API 常量表一起打包进来，"
              "抽到的是「全集」不是「本模块用到的」。\n"
              "    加 --prefix /demo/form,/demo/cust 缩小；"
              "真正调用了哪些要看浏览器 hook 记录。")
    for u in sorted(apis)[:60]:
        print("  %-58s %s" % (u[:58], apis[u][0][:26]))
    if len(apis) > 60:
        print("  …还有 %d 个" % (len(apis) - 60))
    if a.texts:
        print("\n中文文案 %d 条（前 40）：" % len(texts))
        for t in list(texts)[:40]:
            print("  ", t)

    # 顺带找 localStorage 的 token key —— 免登录要用
    tok_keys = set()
    for fn in files:
        s = open(os.path.join(a.dir, fn), encoding="utf-8", errors="ignore").read()
        for m in re.finditer(r'setItem\(\s*["\']([A-Za-z0-9_]*[Tt]oken[A-Za-z0-9_]*)["\']', s):
            tok_keys.add(m.group(1))
    if tok_keys:
        print("\nlocalStorage token key：%s  ← 免登录注入用这个" % ", ".join(sorted(tok_keys)))

    dump({"files": files, "apis": apis,
          "texts": texts if a.texts else {},
          "tokenKeys": sorted(tok_keys)}, a.out)


# ---------------- 子命令：be / be-list ----------------

def cnb_env():
    env = {**os.environ, "NO_PROXY": "*"}
    for k in ("http_proxy", "https_proxy", "all_proxy",
              "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
        env.pop(k, None)
    env["PATH"] = os.path.dirname(代码仓库) + os.pathsep + env.get("PATH", "")
    return env


def run_cnb(args):
    if not os.path.exists(代码仓库):
        sys.exit("✗ 找不到 cnb CLI：%s\n  需要连接 代码仓库连接器，或改用 --local 指向本地仓库" % 代码仓库)
    r = _compat.run_text([代码仓库] + args, timeout=180, env=cnb_env())
    out = r.stdout
    if r.returncode != 0 and not out:
        sys.exit("✗ cnb 调用失败：%s" % (r.stderr or "")[:300])
    return out


def parse_json(out):
    i = out.find("{")
    if i < 0:
        return None
    try:
        return json.loads(out[i:])
    except json.JSONDecodeError:
        return None


def cmd_be(a):
    if a.local:
        p = os.path.join(a.local, a.path)
        if not os.path.exists(p):
            sys.exit("✗ 本地文件不存在：%s" % p)
        s = open(p, encoding="utf-8", errors="ignore").read()
    else:
        if not a.repo:
            sys.exit("✗ 要么给 --repo（代码仓库 仓库完整路径），要么给 --local")
        out = run_cnb(["git", "get-content", "--repo", a.repo,
                       "--file-path", a.path, "-v"])
        d = parse_json(out) or {}
        c = (d.get("data") or {}).get("content", "")
        try:
            s = base64.b64decode(c).decode("utf-8")
        except Exception:
            s = c

    if not s.strip():
        sys.exit("✗ 文件内容为空（路径可能不对）")
    print("%s：%d 行 %d 字符" % (a.path.split("/")[-1], s.count("\n"), len(s)))

    # 顺手抽方法签名与权限注解，省一次人工翻
    sig = re.findall(r'(?:public|private|protected)\s+[\w<>,\[\]\s.?]+\s+(\w+)\s*\(', s)
    if sig:
        print("\n方法（%d）：%s" % (len(sig), ", ".join(sig[:30])))
    ann = re.findall(r'@(\w*(?:Auth|Permission)\w*)\s*(\([^)]*\))?', s)
    if ann:
        print("\n权限注解 %d 处：" % len(ann))
        for n_, args in ann[:20]:
            print("  @%s%s" % (n_, args or ""))

    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(s)
        print("\n→ %s" % a.out)
    elif not sig:
        print(s[:3000])


def cmd_be_list(a):
    if a.local:
        p = os.path.join(a.local, a.path or "")
        for n in sorted(os.listdir(p)):
            print(("dir  " if os.path.isdir(os.path.join(p, n)) else "file ") + n)
        return
    if not a.repo:
        sys.exit("✗ 需要 --repo 或 --local")
    out = run_cnb(["git", "get-content", "--repo", a.repo,
                   "--file-path", a.path, "-v"] if a.path
                  else ["git", "get-content-without-path", "--repo", a.repo, "-v"])
    d = parse_json(out) or {}
    entries = (d.get("data") or {}).get("entries") or []
    if not entries:
        print("（无条目，路径可能不对）")
    for e in entries:
        print("%-5s %s" % (e.get("type"), e.get("path")))


# ---------------- main ----------------

def main():
    strip_proxy()
    ap = argparse.ArgumentParser(description="五源采集：接口字典 / 单接口 / 前端码 / 后端码")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("enums", help="拉枚举字典真值")
    p.add_argument("--token-file", default=_compat.tmpfile("prd_token.json"))
    p.add_argument("--api", help="覆盖 token 文件里的网关地址")
    p.add_argument("--path", default="/demo/enum/listEnums")
    p.add_argument("--keys", required=True, help="逗号分隔，如 demo:fieldTextType,demo:fillParty")
    p.add_argument("-o", "--out")
    p.set_defaults(func=cmd_enums)

    p = sub.add_parser("probe", help="调单个接口，看返回结构")
    p.add_argument("--token-file", default=_compat.tmpfile("prd_token.json"))
    p.add_argument("--api")
    p.add_argument("--path", required=True)
    p.add_argument("--body", default="{}")
    p.add_argument("--keep", action="store_true", help="返回非成功码也照常输出")
    p.add_argument("-o", "--out")
    p.set_defaults(func=cmd_probe)

    p = sub.add_parser("chunks", help="从本地前端 chunk 抽接口与文案")
    p.add_argument("--dir", default=_compat.tmpfile("chunks"))
    p.add_argument("--match", help="文件名关键词，如 field")
    p.add_argument("--prefix", help="只保留这些路径前缀，逗号分隔，如 /demo/form")
    p.add_argument("--texts", action="store_true", help="同时抽中文文案字面量")
    p.add_argument("-o", "--out")
    p.set_defaults(func=cmd_chunks)

    p = sub.add_parser("be", help="读后端代码文件")
    p.add_argument("--repo", help="代码仓库 仓库完整路径，如 org/sub/grp/repo")
    p.add_argument("--local", help="本地仓库根目录（与 --repo 二选一）")
    p.add_argument("--path", required=True, help="文件相对路径")
    p.add_argument("-o", "--out")
    p.set_defaults(func=cmd_be)

    p = sub.add_parser("be-list", help="列后端仓库目录")
    p.add_argument("--repo")
    p.add_argument("--local")
    p.add_argument("--path", default="")
    p.set_defaults(func=cmd_be_list)

    a = ap.parse_args()
    a.func(a)


if __name__ == "__main__":
    import _compat as _c   # 控制台编码兜底（Windows 默认 cp936 编不出 ✓ ✗）
    _c.init()
    main()
