#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""变更台账校验 —— 检查编号连续性与字段完整性。

台账是四路同源的唯一数据源，一旦编号重号或字段缺失，
页面徽标、文档标注、变更记录页签、CHANGELOG 四处会同时出错。

用法：
    python3 ledger.py check --file <changes.py>
    python3 ledger.py check --file <changes.py> --prefix ADM
    python3 ledger.py list  --file <changes.py>

退出码：
    0  通过
    1  发现问题
    2  无法读取台账
"""

import argparse
import importlib.util
import os
import re
import sys

REQUIRED = ["id", "ver", "page", "kind", "what", "why", "impact"]
MIN_LEN = {"what": 6, "why": 8, "impact": 6}

# 「按需求调整」「优化体验」这类无信息量的理由
VAGUE = ["按需求", "按产品要求", "优化体验", "调整一下", "根据反馈", "待补充", "见文档", "略"]


def load_changes(path):
    """从 python 文件里取出 CHANGES 列表，不执行其主流程。"""
    if not os.path.isfile(path):
        print("找不到台账文件：%s" % path)
        return None
    src = open(path, encoding="utf-8").read()
    cut = src.find("if __name__")
    if cut > 0:
        src = src[:cut]
    ns = {}
    try:
        exec(compile(src, path, "exec"), ns)
    except Exception as e:
        print("台账文件无法解析：%s" % e)
        return None
    return ns.get("CHANGES")


def check(changes, prefix):
    problems = []
    ids, nums = [], []
    for i, c in enumerate(changes, 1):
        cid = c.get("id", "")
        ids.append(cid)

        for f in REQUIRED:
            if f not in c or (isinstance(c.get(f), str) and not c[f].strip()):
                problems.append("第 %d 条 %s：缺字段 %s" % (i, cid or "(无编号)", f))

        for f, n in MIN_LEN.items():
            v = str(c.get(f, "")).strip()
            if v and len(v) < n:
                problems.append("第 %d 条 %s：%s 内容过短（%d 字），需写清" % (i, cid, f, len(v)))
            if v and any(v.startswith(w) or v == w for w in VAGUE):
                problems.append("第 %d 条 %s：%s 是无信息量的套话「%s」" % (i, cid, f, v[:16]))

        m = re.fullmatch(r"([A-Z]+)-(\d+)", cid or "")
        if not m:
            problems.append("第 %d 条：编号格式不对「%s」，应为 XXX-01" % (i, cid))
            continue
        if prefix and m.group(1) != prefix:
            problems.append("第 %d 条：编号前缀 %s 与预期 %s 不符" % (i, m.group(1), prefix))
        nums.append(int(m.group(2)))

    dup = {x for x in ids if ids.count(x) > 1}
    for d in sorted(dup):
        problems.append("编号重复：%s" % d)

    if nums:
        expect = list(range(min(nums), max(nums) + 1))
        missing = sorted(set(expect) - set(nums))
        if missing:
            problems.append("编号跳号：缺 %s" % ", ".join(
                "%s-%02d" % (prefix or "?", n) for n in missing))

    return problems, nums


def main():
    ap = argparse.ArgumentParser(description="变更台账校验")
    ap.add_argument("action", choices=["check", "list"])
    ap.add_argument("--file", required=True, help="changes.py 路径")
    ap.add_argument("--prefix", default="", help="限定编号前缀，如 CR / ADM")
    args = ap.parse_args()

    changes = load_changes(args.file)
    if changes is None:
        return 2
    if not changes:
        print("台账为空，或没有 CHANGES 变量")
        return 1

    print("== 台账校验：%s ==" % os.path.basename(args.file))
    print("共 %d 条\n" % len(changes))

    if args.action == "list":
        for c in changes:
            print("%-7s %-5s %-24s %s" % (
                c.get("id", "?"), c.get("ver", "?"),
                str(c.get("page", ""))[:24], str(c.get("what", ""))[:50]))
        return 0

    problems, nums = check(changes, args.prefix)
    if problems:
        print("发现 %d 个问题：" % len(problems))
        for p in problems:
            print("  ✗ " + p)
        print("\n结论：不通过。编号或字段不完备时不要交付。")
        return 1

    print("  ✓ 编号连续（%s ~ %s），无重号" % (
        "%s-%02d" % (args.prefix or "?", min(nums)),
        "%s-%02d" % (args.prefix or "?", max(nums))))
    print("  ✓ 必填字段齐全，无套话")
    print("\n结论：通过。")
    return 0


if __name__ == "__main__":
    import _compat as _c   # 控制台编码兜底（Windows 默认 cp936 编不出 ✓ ✗）
    _c.init()
    sys.exit(main())
