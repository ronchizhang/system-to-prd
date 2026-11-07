#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""闸门登记：把「谁、什么时候、认了什么」记进事实台账，供 check_delivery / merge 复核。

    python3 gate.py status --root ./prd-run --module ops-field
    python3 gate.py facts  --root ./prd-run --module ops-field --by 张三 --total 12 --answered 12
    python3 gate.py scope  --root ./prd-run --module ops-field --by 张三 --what "8 段骨架、22 条规则、状态机 7 态"
    python3 gate.py sign   --root ./prd-run --module ops-field --by 张三 --note "这一版可以往下走"

    # 整份一起封，不按模块逐个封
    python3 gate.py doc    --root ./prd-run --by 张三 --note "整份看过，按默认口径推进"
    python3 gate.py doc    --root ./prd-run --revoke

为什么要这个脚本：

  闸门如果只写「approved_at 有值」，那它证明不了任何事——自己填一个时间就算过了。
  所以每道门都记 `by / at / note`。

  **签字只有一个人：产品经理本人。** 它的性质是「封板」而不是「双重确认」——
  意思是「这一版我认了，可以往研发走」。曾经要求业务与技术两个不同的人分别签，
  结果是没人执行，每轮检查都挂着红叉，红叉挂久了就不再传递信息。

  封板还会记一份内容指纹：封完之后谁再改这个模块，签自动失效。只记名字不记内容，
  签一次就能管到底，那这道门是摆设。

写入位置：facts/<key>.facts.json

    {"meta": {...},
     "gate":   {"facts": {"by","at","note","total","answered"},
                "scope": {"by","at","what"}},
     "signoff":{"by", "at", "note", "digest"},
     "facts":  [...]}

老数据里 signoff 还是 {"business": {...}, "tech": {...}}，读的时候取先签的那个，
不要求重新签（见 schema.signer_of）。

旧的 `gate.approved_at` 仍然认（兼容），但 status 会提示补 `by`。
"""

import argparse
import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import schema as S  # noqa: E402

# 签字结构的新旧兼容在 schema.signer_of 里，三个脚本共用一份判断。


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
    """整份封板：一个人、一次、覆盖全部模块。

    为什么要有这条：模块多的时候逐个封太碎，而「整份看一遍」本来就是一个动作。
    一个人、一次、盖住全部模块，只留痕（谁、哪一稿、认了什么），不走不存在的审批流程。
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

    # 记下签字那一刻各模块的内容指纹。稿次对不上能拦，但「改了内容不发新稿」拦不住——
    # 那种情况 draft 没变，签字会一直有效。指纹变了才是真的改过。
    _digests = {}
    _mdir = os.path.join(root, "modules")
    if os.path.isdir(_mdir):
        for _f in sorted(os.listdir(_mdir)):
            if _f.endswith(".json"):
                _digests[_f[:-5]] = S.content_digest(os.path.join(_mdir, _f))

    run["signoff"] = {
        "by": a.by.strip(),
        "at": now(),
        "draft": run.get("draft"),
        "rev": run.get("rev") or 0,
        "note": a.note.strip(),
        "covers": a.covers,
        "digests": _digests,
    }
    tmp = rp + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(run, f, ensure_ascii=False, indent=1)
        f.write("\n")
    os.replace(tmp, rp)

    so = run["signoff"]
    print("✓ 文档级确认已记：%s @ %s" % (so["by"], so["at"]))
    print("  覆盖：%s · %s%s" % (
        so["covers"],
        "第 %s 稿" % so["draft"] if so["draft"] is not None else "未编稿次",
        "（修订 %s）" % so["rev"] if so["rev"] else ""))
    print("  指纹：%d 个模块已记，之后谁改了内容，这条确认就自动失效" % len(_digests))
    print("  说明：%s" % so["note"])
    print()
    print("  闸门 1 / 闸门 2 / 封板 三项按这一条认定，不再逐模块要求签名。")
    print("  改稿（推新稿或加修订）后这条自动失效，要重新确认。")
    return 0


def cmd_status(d, key, root=None):
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

    # status 是「一眼看全」的地方，它必须比 check_delivery 更早说实话：
    # 封板之后又改了内容，这里就得显示失效，不能等交付验收才报。
    _mh = S.content_digest(os.path.join(root, "modules", key + ".json")) if root else None
    s = S.signer_of(so)
    _dg = s.get("digest")
    note = ("  " + s["note"]) if s.get("note") else ""
    if not s.get("by"):
        print("  封板           ✗ 未签")
    elif _dg and _mh and _dg != _mh:
        print("  封板           ! %s —— 签的是旧内容，模块之后被改过，要重新封一次%s"
              % (fmt(s), note))
    else:
        print("  封板           ✓ %s%s" % (fmt(s), note))

    # 文档级确认（写在 run.json，覆盖全部模块）
    if root:
        rp = os.path.join(root, "run.json")
        if os.path.exists(rp):
            try:
                run = json.load(open(rp, encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                run = {}
            ds = run.get("signoff") or {}
            if ds.get("by"):
                if ds.get("draft") != run.get("draft") or (ds.get("rev") or 0) != (run.get("rev") or 0):
                    print("  文档级确认     ! %s —— 记的是第 %s 稿，现为第 %s 稿"
                          % (ds["by"], ds.get("draft"), run.get("draft")))
                else:
                    _sd = ds.get("digests") or {}
                    _chg = [k for k, v in _sd.items()
                            if S.content_digest(os.path.join(root, "modules", k + ".json")) != v]
                    if _chg:
                        print("  文档级确认     ! %s —— 之后这些模块被改过：%s"
                              % (ds["by"], "、".join(sorted(_chg))))
                    else:
                        print("  文档级确认     ✓ %s @ %s（%s）"
                              % (ds["by"], ds["at"],
                                 "第 %s 稿" % ds.get("draft")
                                 if ds.get("draft") is not None else "未编稿次"))


def main():
    ap = argparse.ArgumentParser(description="闸门登记与状态")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        # 放在子命令后面写更顺手：gate.py sign --root . --module k --by 李四
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

    p = common(sub.add_parser("sign", help="封板：这个模块我确认了，可以往下走"))
    p.add_argument("--by", required=True, help="签字人（产品经理本人）")
    p.add_argument("--note", default="")

    p = common(sub.add_parser("revoke", help="撤销封板（要改内容时用）"))

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
            cmd_status(d, a.module, root)
        return 0

    if a.cmd == "facts":
        if a.total is not None and a.answered is not None and a.answered < a.total:
            sys.exit("✗ 还有 %d 条没答，闸门 1 不能过。先把清单答完。"
                     % (a.total - a.answered))
        # 必须成对给。只给一个会把另一项写成 None，不只是显示成「None/33」——
        # 它会把上一次真答完的条数冲掉，闸门留痕就此失真。
        if (a.total is None) != (a.answered is None):
            sys.exit("✗ --total 与 --answered 要成对给（如 --total 33 --answered 33）。\n"
                     "  只给一个会把另一项写成 None，冲掉上次的记录。")
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
        prev = S.signer_of(d.get("signoff") or {})
        # 记下封板那一刻这个模块的内容指纹。只记时间不够：封板之后还能接着改内容，
        # 改完不发新稿，签就永远有效——签一次管到底，那这个门就是个摆设。
        _mp = os.path.join(root, "modules", a.module + ".json")
        d["signoff"] = {"by": a.by, "at": now(), "note": a.note,
                        "digest": S.content_digest(_mp)}
        save(fp, d)
        print("✓ 已封板：%s%s" % (fmt(d["signoff"]),
                                 "（替换了 %s 的旧封板）" % prev.get("by") if prev.get("by") else ""))
        _dg = d["signoff"].get("digest")
        print("  内容指纹：%s —— 封板之后这个模块再被改，这签就自动失效"
              % ((_dg or "")[:12] + "…" if _dg else "未取到（模块文件还没建）"))
        print("  下一步：check_delivery --strict")

    elif a.cmd == "revoke":
        d["signoff"] = {}
        save(fp, d)
        print("✓ 已撤销封板。改完内容记得重新封一次。")

    d2 = load(fp)
    if d2.get("gate") or d2.get("signoff"):
        print()
        cmd_status(d2, a.module, root)
    return 0


if __name__ == "__main__":
    sys.exit(main())
