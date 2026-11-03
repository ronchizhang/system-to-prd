#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""凭据残留审计 —— 确认 skill 与项目目录里没有留下账号密码。

本 skill 的硬约束：凭据只在当前会话内传递，绝不写入任何文件。
交付前跑一遍这个脚本，确认没有遗漏。

用法：
    python3 audit_no_secrets.py                    # 只扫本 skill 目录
    python3 audit_no_secrets.py --path ~/proj      # 追加扫描其它目录
    python3 audit_no_secrets.py --strict           # 连 4 位以下的短值也报

退出码：
    0  未发现疑似凭据
    1  发现疑似凭据（交付前必须清理）
"""

import argparse
import os
import re
import sys

TEXT_EXT = {".md", ".txt", ".py", ".json", ".yaml", ".yml",
            ".html", ".htm", ".ini", ".cfg", ".conf", ".sh", ".env"}

SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv", ".idea"}

# 命中「凭据类关键词 + 分隔符 + 值」才算
PATTERN = re.compile(
    r"(?i)[\w.$-]*(password|passwd|pwd|passcode|secret|token|api_?key|密码|口令)[\w$-]*"
    r"\s*[:=：]\s*[\"']?([^\s\"'，,;；\n]{4,64})"
)

# 这些值明显是占位示例，不算泄露
PLACEHOLDER = {
    "xxx", "xxxx", "xxxxx", "****", "******", "***", "your_password",
    "yourpassword", "changeme", "todo", "none", "null", "空", "<password>",
    "your-password", "password", "pwd", "secret", "示例", "略",
}
PLACEHOLDER_PREFIX = ("your_", "your-", "<", "${", "{{", "%(", "os.env", "env.",
                     "getpass.", "input(", "find_token", "os.environ",
                     "d.get(", "json.", "sys.env")

# 值形如 函数名(...) 的，是取值调用而不是字面量，不算凭据
CALL_RE = re.compile(r"^[A-Za-z_][\w.]*\s*\(")

MASK_KEEP = 2


def mask(v):
    """脱敏展示，避免审计脚本自己把密码打印出来。"""
    if len(v) <= MASK_KEEP * 2:
        return "*" * len(v)
    return v[:MASK_KEEP] + "*" * (len(v) - MASK_KEEP * 2) + v[-MASK_KEEP:]


def is_placeholder(v):
    lv = v.lower()
    if lv in PLACEHOLDER:
        return True
    if lv.startswith(PLACEHOLDER_PREFIX):
        return True
    if v.strip("*/xX-_.·") == "":      # 纯掩码字符
        return True
    if CALL_RE.match(v):               # 函数调用取值
        return True
    if any(ch in v for ch in "()（）"):  # 表达式片段或说明文字，不是字面量
        return True
    return False


def scan(root, strict=False, self_path=None):
    hits = []
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if d not in SKIP_DIRS]
        for fn in fns:
            ext = os.path.splitext(fn)[1].lower()
            if ext not in TEXT_EXT:
                continue
            p = os.path.join(dp, fn)
            if self_path and os.path.abspath(p) == os.path.abspath(self_path):
                continue
            try:
                lines = open(p, encoding="utf-8", errors="ignore").read().splitlines()
            except OSError:
                continue
            for i, line in enumerate(lines, 1):
                for m in PATTERN.finditer(line):
                    val = m.group(2).strip()
                    if not strict and len(val) < 4:
                        continue
                    if is_placeholder(val):
                        continue
                    # 纯英文单词且不是常见密码形态，视为说明性文字
                    if re.fullmatch(r"[A-Za-z_]{4,20}", val) and "_" in val:
                        continue
                    hits.append((p, i, m.group(1), mask(val)))
    return hits


def main():
    ap = argparse.ArgumentParser(description="审计凭据残留")
    ap.add_argument("--path", action="append", default=[],
                    help="追加扫描目录，可多次指定")
    ap.add_argument("--strict", action="store_true", help="连短值也报")
    args = ap.parse_args()

    skill_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    targets = [skill_dir] + [os.path.expanduser(p) for p in args.path]

    print("== 凭据残留审计 ==")
    total = 0
    for t in targets:
        if not os.path.isdir(t):
            print("  跳过（不存在）：%s" % t)
            continue
        hits = scan(t, args.strict, self_path=os.path.abspath(__file__))
        print("  %s → %d 处疑似" % (t, len(hits)))
        for p, line_no, kw, masked in hits:
            print("      %s:%d  %s = %s" % (
                os.path.relpath(p, t), line_no, kw, masked))
        total += len(hits)

    print()
    if total:
        print("结果：发现 %d 处疑似凭据 —— **交付前必须清理**。" % total)
        print("注意：只删值，保留字段说明。若确认是示例占位，可加进脚本的 PLACEHOLDER 白名单。")
        return 1
    print("结果：干净，未发现凭据残留。")
    return 0


if __name__ == "__main__":
    import _compat as _c   # 控制台编码兜底（Windows 默认 cp936 编不出 ✓ ✗）
    _c.init()
    sys.exit(main())
