#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""闸门登记：把「谁、什么时候、凭什么」记进事实台账，供 check_delivery / merge 复核。

    python3 gate.py status --root ./prd-run --module ops-field
    python3 gate.py facts  --root ./prd-run --module ops-field --by 王小明 --total 12 --answered 12
    python3 gate.py scope  --root ./prd-run --module ops-field --by 张三 --what "8 段骨架、22 条规则、状态机 7 态"
    python3 gate.py sign   --root ./prd-run --module ops-field --role business --by 王小明 --note "口径逐条过"
    python3 gate.py sign   --root ./prd-run --module ops-field --role tech --by 李四 --note "契约与接口已核"

    # 小团队默认方式：整份文档确认一次，不按模块签
    python3 gate.py doc    --root ./prd-run --by 王小明 --note "整份看过，按默认口径推进"
    python3 gate.py doc    --root ./prd-run --revoke

为什么要这个脚本：

  闸门如果只写「approved_at 有值」，那它证明不了任何事——自己填一个时间就算过了。
  所以每道门都记 `by / at / note`，并且交付前要求两个**不同的人**分别签业务与技术。
  机器查得出「有没有签」，查不出「签得对不对」；人查得出「对不对」，但人多半不会去翻全篇。
  两层各管一半，这就是「门禁上加门禁」。

写入位置：facts/<key>.facts.json

    {"meta": {...},
     "gate":   {"facts": {"by","at","note","total","answered"},
                "scope": {"by","at","what"}},
     "signoff":{"business": {"by","at","note"},
                "tech":     {"by","at","note"}},
     "facts":  [...]}

旧的 `gate.approved_at` 仍然认（兼容），但 status 会提示补 `by`。
"""

import argparse
import datetime as dt
import json
import os
import sys

ROLES = ("business", "tech")
ROLE_CN = {"business": "业务确认", "tech": "技术复核"}


def now():
    return dt.datetime.now().isoformat(timespec="minutes")


def load(p):
    if not os.path.exists(p):
        return {"meta": {}, "gate": {}, "signoff": {}, "facts": []}
    with open(p, encoding="utf-8") as f:
        d = json.load(f)
    d.setdefault("gate", {})
    d.setdefault("signoff", {})
    d.setdefault("facts", [])
    return d


def save(p, d):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
        f.write("\n")
    os.replace(tmp, p)


def path_of(root, key):
    return os.path.join(root, "facts", key + ".facts.json")


def fmt(s):
    return "%s @ %s" % (s.get("by") or "未署名", s.get("at") or "—")


def cmd_doc(root, a):
    """文档级确认：一个人、一次、覆盖全部模块。

    为什么要有这条：模块级双签在 6 个模块的工程里要签 12 次名，小团队没人会做——
    结果是每轮检查都挂着红叉，红叉就不再传递信息。改成「整份看一遍、一个人确认」，
    既留了痕（谁、哪一稿、确认了什么），又不需要走不存在的审批流程。
    """
    rp = os.path.join(root, "run.json")
    if not os.path.exists(rp):
        sys.exit("✗ 没有 run.json，先用 init_run.py 建工程")
    with open(rp, encoding="utf-8") as f:
        run = json.load(f)

    if a.revoke:
        run.pop("signoff", None)
        tmp = rp + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(run, f, ensure_ascii=False, indent=1)
            f.write("\n")
        os.replace(tmp, rp)
        print("✓ 已撤销文档级确认。改完稿要重新看一遍再确认。")
        return 0

    if not (a.by or "").strip():
        sys.exit("✗ 要写 --by <姓名>。这不是形式——它是「谁认过这一版」的唯一记录")
    if len((a.note or "").strip()) < 4:
        sys.exit("✗ --note 太短。写一句确认了什么，比如「整份看过，按默认口径推进」")

    run["signoff"] = {
        "by": a.by.strip(),
        "at": now(),
        "draft": run.get("draft"),
        "rev": run.get("rev") or 0,
        "note": a.note.strip(),
        "covers": a.covers,
    }
    tmp = rp + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(run, f, ensure_ascii=False, indent=1)
        f.write("\n")
    os.replace(tmp, rp)

    so = run["signoff"]
    print("✓ 文档级确认已记：%s @ %s" % (so["by"], so["at"]))
    print("  覆盖：%s · 第 %s 稿%s" % (
        so["covers"], so["draft"],
        "（修订 %s）" % so["rev"] if so["rev"] else ""))
    print("  说明：%s" % so["note"])
    print()
    print("  闸门 1 / 闸门 2 / 双签 三项按这一条认定，不再逐模块要求签名。")
    print("  改稿（推新稿或加修订）后这条自动失效，要重新确认。")
    return 0


def cmd_status(d, key):
    g, so = d.get("gate") or {}, d.get("signoff") or {}
    legacy = g.get("approved_at")
    facts = g.get("facts") or {}
    scope = g.get("scope") or {}

    print("模块 %s" % key)
    if legacy and not facts.get("at"):
        print("  闸门 1 事实清单   ! 只有 approved_at=%s，没有署名——补：gate.py facts --by <姓名>" % legacy)
    else:
        print("  闸门 1 事实清单   %s%s" % (
            ("✓ " + fmt(facts)) if facts.get("at") else "✗ 未过",
            ("  %s/%s 条已答" % (facts.get("answered"), facts.get("total")))
            if facts.get("total") else ""))
    print("  闸门 2 骨架确认   %s%s" % (
        ("✓ " + fmt(scope)) if scope.get("at") else "✗ 未过",
        ("  " + scope["what"]) if scope.get("what") else ""))

    for r in ROLES:
        s = so.get(r) or {}
        print("  签字 · %-8s %s%s" % (ROLE_CN[r], ("✓ " + fmt(s)) if s.get("by") else "✗ 未签",
                                     ("  " + s["note"]) if s.get("note") else ""))

    # 双签必须是两个不同的人，且不能是文档作者自己给自己签业务
    b, t = (so.get("business") or {}), (so.get("tech") or {})
    if b.get("by") and t.get("by") and b["by"].strip() == t["by"].strip():
        print("  ! 业务与技术签的是同一个人（%s）——两层门禁退化成一层" % b["by"])
    owner = (d.get("meta") or {}).get("owner") or ""
    if b.get("by") and owner and b["by"].strip() == owner.strip():
        print("  ! 业务签字人就是本模块作者（%s）——自己确认自己的口径" % owner)


def main():
    ap = argparse.ArgumentParser(description="闸门登记与状态")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        # 放在子命令后面写更顺手：gate.py sign --root . --module k --role tech --by 李四
        p.add_argument("--root", required=True, help="工作台目录")
        p.add_argument("--module", required=True, help="模块 key")
        return p

    p = common(sub.add_parser("status", help="看四道门（事实/骨架/业务签/技术签）"))
    p.add_argument("--json", dest="as_json", action="store_true")

    p = common(sub.add_parser("facts", help="闸门 1：事实清单已裁定"))
    p.add_argument("--by", required=True)
    p.add_argument("--total", type=int)
    p.add_argument("--answered", type=int)
    p.add_argument("--note", default="")

    p = common(sub.add_parser("scope", help="闸门 2：骨架/范围已确认"))
    p.add_argument("--by", required=True)
    p.add_argument("--what", required=True, help="确认了什么：段数/规则数/状态数/不写什么")

    p = common(sub.add_parser("sign", help="交付签字：business 或 tech"))
    p.add_argument("--role", required=True, choices=ROLES)
    p.add_argument("--by", required=True)
    p.add_argument("--note", default="")

    p = common(sub.add_parser("revoke", help="撤销某一签（改稿后要重签）"))
    p.add_argument("--role", required=True, choices=ROLES)

    pd = sub.add_parser("doc", help="文档级确认：整份 PRD 看一遍，一个人签（小团队默认）")
    pd.add_argument("--root", required=True)
    pd.add_argument("--by")
    pd.add_argument("--note", default="")
    pd.add_argument("--covers", default="全部模块")
    pd.add_argument("--revoke", action="store_true")

    a = ap.parse_args()
    root = os.path.abspath(os.path.expanduser(a.root))
    if a.cmd == "doc":
        return cmd_doc(root, a)
    fp = path_of(root, a.module)
    d = load(fp)

    if a.cmd == "status":
        if a.as_json:
            print(json.dumps({"gate": d.get("gate"), "signoff": d.get("signoff")},
                             ensure_ascii=False, indent=1))
        else:
            cmd_status(d, a.module)
        return 0

    if a.cmd == "facts":
        if a.total is not None and a.answered is not None and a.answered < a.total:
            sys.exit("✗ 还有 %d 条没答，闸门 1 不能过。先把清单答完。"
                     % (a.total - a.answered))
        d["gate"]["facts"] = {"by": a.by, "at": now(), "note": a.note,
                              "total": a.total, "answered": a.answered}
        # 兼容老字段：check_delivery 与 build_facts 都在读它
        d["gate"]["approved_at"] = d["gate"]["facts"]["at"]
        if a.total is not None:
            d["gate"]["total"] = a.total
        if a.answered is not None:
            d["gate"]["answered"] = a.answered
        save(fp, d)
        print("✓ 闸门 1 已留痕：%s" % fmt(d["gate"]["facts"]))

    elif a.cmd == "scope":
        if len(a.what.strip()) < 8:
            sys.exit("✗ --what 太短。要写清真确认了什么（段数/规则数/状态数/哪些不写）")
        d["gate"]["scope"] = {"by": a.by, "at": now(), "what": a.what.strip()}
        save(fp, d)
        print("✓ 闸门 2 已留痕：%s" % fmt(d["gate"]["scope"]))

    elif a.cmd == "sign":
        prev = d["signoff"].get(a.role) or {}
        other = [r for r in ROLES if r != a.role]
        for r in other:
            o = d["signoff"].get(r) or {}
            if o.get("by") and o["by"].strip() == a.by.strip():
                sys.exit("✗ %s 已经签过%s。业务与技术必须是两个不同的人，"
                         "否则两层门禁退化成一层。" % (a.by, ROLE_CN[r]))
        d["signoff"][a.role] = {"by": a.by, "at": now(), "note": a.note}
        save(fp, d)
        print("✓ %s 已签：%s%s" % (ROLE_CN[a.role], fmt(d["signoff"][a.role]),
                                  "（替换了旧签名 %s）" % prev.get("by") if prev.get("by") else ""))
        left = [ROLE_CN[r] for r in ROLES if not (d["signoff"].get(r) or {}).get("by")]
        if left:
            print("  还差：%s" % "、".join(left))
        else:
            print("  双签齐了。下一步：check_delivery --strict")

    elif a.cmd == "revoke":
        d["signoff"].pop(a.role, None)
        save(fp, d)
        print("✓ 已撤销 %s。改完稿要重新签。" % ROLE_CN[a.role])

    d2 = load(fp)
    if d2.get("gate") or d2.get("signoff"):
        print()
        cmd_status(d2, a.module)
    return 0


if __name__ == "__main__":
    sys.exit(main())
