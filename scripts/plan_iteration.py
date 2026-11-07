#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""迭代开工侦察与登记：这次改哪个终端、哪个产品版本、第几稿、改哪些模块。

    python3 plan_iteration.py --root ./prd-xpay              # 侦察报告（只读）
    python3 plan_iteration.py --root ./prd-xpay --check      # 一致性门禁，不过退出码 1
    python3 plan_iteration.py --root ./prd-xpay --set \
        --terminal 管理后台 --product "管理后台 V5.0" --draft 14 \
        --scope "demo-payout-workbench|修改|缺字段只提示不阻断" \
        --scope "demo-partner-request|修改|协议由单值改为集合"

为什么要有这个脚本：

  稿次和版本号是最容易搞错的两个数字。人记不住上一稿是第几稿，从文件名猜又会把
  产品版本（V5.0）当成稿次。所以让脚本去数：run.json 的 draft、各模块 meta.version 里的
  「第 N 稿」、根目录产物文件名里的「第N稿」，三者取最大 +1。

  改动范围也要留痕：scope 落进 run.json，check_delivery.py 的「迭代」组据此判断
  「说了要改的模块，原型里到底有没有标」。

scope 写法（三到四段，竖线分隔）：

    key|改动类型|一句话|C3,C4        # 完整
    key|一句话                       # 类型默认「修改」，编号自动分配

编号自动分配规则：扫全部模块里已出现的 data-chg="C数字"，取最大 +1 往后排。
**全局递增，不按模块重新起 1**——跨模块撞号会让「改③」指两件事。
"""

import argparse
import json
import os
import re
import sys

DRAFT_RE = re.compile(r"第\s*(\d{1,3})\s*稿")
PRODUCT_RE = re.compile(r"^(?P<sys>[^·]+?)\s+(?P<v>V\d{1,2}\.\d{1,2})\s*(?:·|$)")
CHG_RE = re.compile(r"""data-chg=\\?["'](C\d{1,3})\\?["']""")
# 改动编号属于哪一稿：标签上同时有 data-chg 和 data-draft。
# 属性顺序不固定，所以先框住整个标签再分别取，不能写死成一条正则。
CHG_TAG_RE = re.compile(r"<[^>]*\bdata-chg=[^>]*>")
CHG_DRAFT_RE = re.compile(r"""data-draft=\\?["'](\d{1,2})\\?["']""")


def chg_drafts(blob):
    """{编号: 稿次}，没写稿次的记 0。"""
    out = {}
    for t in CHG_TAG_RE.finditer(blob):
        s = t.group(0)
        m = CHG_RE.search(s)
        d = CHG_DRAFT_RE.search(s)
        if m:
            out.setdefault(m.group(1), int(d.group(1)) if d else 0)
    return out
TERMINALS = ("管理后台", "机构端", "学员端")
KIND = ("新增", "修改", "删除")


def load(p, default=None):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default
    except json.JSONDecodeError as e:
        print("！JSON 坏了：%s（%s）" % (p, e))
        sys.exit(2)


def save(p, data):
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
        f.write("\n")
    os.replace(tmp, p)


def drafts_in(text):
    return [int(x) for x in DRAFT_RE.findall(text or "")]


def scan(root):
    """把工作台里所有和「第几稿 / 哪个版本 / 哪个终端」有关的线索都数一遍。"""
    run = load(os.path.join(root, "run.json"), {}) or {}
    mods, mod_drafts, products, systems = [], [], {}, {}
    chg_max = 0

    mdir = os.path.join(root, "modules")
    if os.path.isdir(mdir):
        for fn in sorted(os.listdir(mdir)):
            if not fn.endswith(".json"):
                continue
            d = load(os.path.join(mdir, fn), {}) or {}
            meta = d.get("meta") or {}
            ver = (meta.get("version") or "").strip()
            ds = drafts_in(ver)
            p = PRODUCT_RE.match(ver)
            prod = ("%s %s" % (p.group("sys").strip(), p.group("v"))) if p else None
            if prod:
                products[prod] = products.get(prod, 0) + 1
            sysn = meta.get("system")
            if sysn:
                systems[sysn] = systems.get(sysn, 0) + 1
            blob = json.dumps(d, ensure_ascii=False)
            for c in CHG_RE.findall(blob):
                chg_max = max(chg_max, int(c[1:]))
            mods.append({
                "key": meta.get("key") or fn[:-5],
                "file": fn,
                "module": meta.get("module"),
                "system": sysn,
                "version": ver,
                "product": prod,
                "draft": meta.get("draft") or (max(ds) if ds else None),
                "rev": meta.get("rev"),
                "rules": len(d.get("rules") or []),
                "chg": sorted({c for c in CHG_RE.findall(blob)}, key=lambda x: int(x[1:])),
                "chg_drafts": chg_drafts(blob),
            })
            mod_drafts += ds

    # 产物文件名里的「第N稿」。
    # 两处要看：①工作台内部（含 90-共享 这类子目录）；②工作台的**上一级**顶层——
    # 交付物习惯放在项目根，和 prd-xxx/ 并排。只扫内部会得出「文件名还没带修订号」的假告警，
    # 因为真正的产物在上一层，扫不到。上一级只收顶层且带产品关键字的，避免把隔壁项目的稿子算进来。
    name_drafts, name_files = [], []
    def take(fn, base, prefix):
        if fn.endswith((".html", ".md", ".json")) and "第" in fn:
            ds = drafts_in(fn)
            if ds:
                name_drafts.append(max(ds))
                name_files.append(os.path.join(prefix, fn) if prefix else fn)

    for dirpath, _dirs, files in os.walk(root):
        if os.sep + "out" in dirpath or os.sep + "snapshot" in dirpath:
            continue
        for fn in files:
            take(fn, dirpath, os.path.relpath(dirpath, root).replace(".", ""))

    parent = os.path.dirname(root.rstrip(os.sep))
    prod_hint = (run.get("product") or "").split()[-1] if run.get("product") else ""
    hint = prod_hint if re.match(r"^[\u4e00-\u9fa5]{2,6}$", prod_hint or "") else ""
    if parent and parent != root:
        try:
            for fn in os.listdir(parent):
                if not os.path.isfile(os.path.join(parent, fn)):
                    continue
                if hint and hint not in fn:
                    continue
                take(fn, parent, "..")
        except OSError:
            pass

    run_draft = run.get("draft")
    cands = [x for x in ([run_draft] if isinstance(run_draft, int) else []) + mod_drafts + name_drafts]
    cur = max(cands) if cands else 0

    return {
        "root": root,
        "run": run,
        "mode": run.get("mode"),
        "terminal": run.get("terminal"),
        "product": run.get("product"),
        "draft": run_draft,
        "rev": run.get("rev"),
        "modules": mods,
        "products": products,
        "systems": systems,
        "name_files": name_files,
        "max_seen": cur,
        "suggest_draft": cur + 1,
        "next_chg": chg_max + 1,
        "scope": run.get("scope") or [],
    }


def report(s):
    out = []
    w = out.append
    w("工作台  %s" % s["root"])
    mode = s["mode"]
    label = {"asis": "交付 A · 现状 PRD", "iterate": "交付 B · 迭代 PRD"}.get(mode)
    w("模式    %s" % (label or "未登记（新工作台用 --set 登记；只是扫描现状就不用登记）"))

    sys_txt = "、".join("%s×%d" % (k, v) for k, v in s["systems"].items()) or "无"
    w("终端    %s" % (("%s（模块里出现：%s）" % (s["terminal"], sys_txt)) if s["terminal"] else sys_txt))

    if s["products"]:
        w("产品版本 %s" % "、".join("%s（%d 个模块）" % (k, v) for k, v in s["products"].items()))
    else:
        w("产品版本 未登记")

    # 稿次：把三个来源分开写，读者能看出为什么是这个数
    per_mod = sorted({m["draft"] for m in s["modules"] if m["draft"]})
    w("稿次    现有最大 第 %s 稿  ← run.json=%s / 模块=%s / 文件名=%s"
      % (s["max_seen"] or "?", s["draft"] if s["draft"] else "—",
         per_mod or "—", sorted(set(drafts_in(" ".join(s["name_files"])))) or "—"))
    if s["draft"]:
        w("        → 本稿为 第 %d 稿%s（已登记）"
          % (s["draft"], "修订 %s" % s["rev"] if s.get("rev") else ""))
    else:
        w("        → 本次应为 第 %d 稿（登记：--set --draft %d）" % (s["suggest_draft"], s["suggest_draft"]))

    w("模块    %d 个" % len(s["modules"]))
    cur = s["draft"]
    for m in s["modules"]:
        cd = m.get("chg_drafts") or {}
        if cd:
            n_cur = sum(1 for d in cd.values() if cur and d == cur)
            n_old = len(cd) - n_cur
            mark = "   标注 %d（本稿 %d / 前稿 %d）" % (len(cd), n_cur, n_old)
            if cur and not n_cur:
                mark += "  ← 本稿还没标新的"
        else:
            mark = ""
        w("        %-24s %-6s %2d 规则%s"
          % (m["key"], m.get("module") or "",
             m.get("rules") or 0, mark))
    if s["scope"]:
        w("范围    %d 项（check_delivery 会按这个查标注）：" % len(s["scope"]))
        for it in s["scope"]:
            w("        %-24s %s %s  %s"
              % (it.get("key"), it.get("kind") or "修改", "/".join(it.get("chg") or []) or "无编号",
                 it.get("what") or ""))
    else:
        # 范围草稿：把工作台里每个模块列一行，勾完直接当 --scope 传回去。
        # 「基于上次产出列改动范围」不能靠人从空白想——先给候选，人才谈得上删改。
        w("范围    未登记。草稿（勾选后改成一条 --scope，类型 新增/修改/删除）：")
        for i, m in enumerate(s["modules"]):
            w('        --scope "%s|修改|<一句话>|%s"'
              % (m["key"], ("C%d" % (s["next_chg"] + i)) if not m["chg"] else ""))
        w("        （留空编号会自动分配；范围外的不动）")
    w("下一个改动编号  C%d（全局递增，扫全部模块得出的）" % s["next_chg"])
    return "\n".join(out)


def check(s):
    """返回 [(level, msg)]，level ∈ ok/warn/fail"""
    r = []
    add = lambda lv, m: r.append((lv, m))

    if not s["modules"]:
        add("fail", "modules/ 里没有模块数据，先跑 init_run.py")
        return r

    mode = s["mode"]
    if mode not in ("asis", "iterate"):
        add("fail", "run.json 没登记 mode。做迭代 PRD：--set --mode iterate --terminal … --product …；"
                     "只是扫描现状：--set --mode asis。两种交付不能混，必须显式写下来")
        return r
    if mode == "asis":
        dirty = [m["key"] for m in s["modules"] if m["chg"]]
        add("warn" if dirty else "ok",
            "现状 PRD 里不该有改动标注" + ("：%s 有 data-chg" % "、".join(dirty) if dirty else "（干净）"))
        return r

    # ---- 四要素齐全 ----
    for f, label in (("terminal", "改哪个终端"), ("product", "产品版本"), ("draft", "第几稿")):
        v = s.get(f)
        add("ok" if v else "fail", "%s：%s" % (label, v if v else "未填 —— 迭代 PRD 必须显式登记"))
    if not s["scope"]:
        add("fail", "改动范围：未登记 scope —— 没列范围就写，等于事后补理由")

    # ---- 终端与模块一致 ----
    if s["terminal"]:
        if s["terminal"] not in TERMINALS:
            add("fail", "terminal=%r 不在 管理后台/机构端/学员端 里" % s["terminal"])
        wrong = [m["key"] for m in s["modules"] if m["system"] and m["system"] != s["terminal"]]
        if wrong:
            add("warn", "这些模块的 meta.system 与 terminal 不一致：%s（跨端迭代就分两个工作台）"
                % "、".join(wrong))

    # ---- 产品版本：模块之间必须一致，且与 run.json 一致 ----
    if len(s["products"]) > 1:
        add("fail", "模块里的产品版本不一致：%s" % "、".join(s["products"]))
    if s["product"]:
        if not re.match(r"^\S.*\sV\d{1,2}\.\d{1,2}$", s["product"]):
            add("fail", "product=%r 应写成「管理后台 V5.0」——带 V 和两位版本号" % s["product"])
        else:
            bad = [m["key"] for m in s["modules"] if m["product"] and m["product"] != s["product"]]
            if bad:
                add("fail", "这些模块的 meta.version 首段不是 %r：%s" % (s["product"], "、".join(bad)))

    # ---- 稿次一致 ----
    d = s["draft"]
    if isinstance(d, int):
        bad = [(m["key"], m["draft"]) for m in s["modules"] if m["draft"] != d]
        if bad:
            add("fail", "稿次不一致（run.json=第 %d 稿）：%s" % (d, "、".join("%s=第 %s 稿" % b for b in bad)))
        else:
            add("ok", "稿次：run.json 与 %d 个模块都是第 %d 稿" % (len(s["modules"]), d))
        # 只报「超前」的：稿次更小的是历史归档（第 10/11/12 稿留在目录里是对的），
        # 全部报「不符」会让这条告警永远亮着，用久了就没人看了。
        for fn in s["name_files"]:
            ds = drafts_in(fn)
            if ds and max(ds) > d:
                add("warn", "产物文件名稿次比 run.json 超前：%s（登记的是第 %d 稿）" % (fn, d))
        if d < s["max_seen"]:
            add("fail", "稿次倒退：登记第 %d 稿，但工作台里已有第 %d 稿" % (d, s["max_seen"]))

    # ---- 修订序号：同一稿内的修正，不推稿次，但三处要一致 ----
    # 修订不推稿次，因为改的是表达与证据、不是业务结论；一旦推成新稿，读者会以为又多了一版需求。
    # 但「修订 1」必须能被脚本读到：run.json.rev、模块 meta.rev、产物文件名的 -修订N。
    rv = s.get("rev")
    if rv:
        if not isinstance(rv, int):
            add("fail", "rev=%r 不是整数" % rv)
        else:
            bad = [(m["key"], m["rev"]) for m in s["modules"] if m["rev"] != rv]
            if bad:
                add("fail", "修订号不一致（run.json=修订 %d）：%s"
                    % (rv, "、".join("%s=%s" % (k, v if v else "无") for k, v in bad)))
            else:
                add("ok", "修订：run.json 与 %d 个模块都是第 %s 稿修订 %d"
                    % (len(s["modules"]), s["draft"], rv))
            # 只看「本稿 + 本修订」那一批：
            #   · 稿次更小的是历史归档（第 10/11/12 稿），不要求带修订号；
            #   · 稿次相同但修订号更小的是上一修订（修订 1），也是历史，不该被要求改成修订 2。
            def _rev_of(fn):
                m = re.search(r"修订\s*(\d{1,2})", fn)
                return int(m.group(1)) if m else 0
            cur_files = [fn for fn in s["name_files"] if s["draft"] in drafts_in(fn)]
            newer = [fn for fn in cur_files if _rev_of(fn) == rv or (_rev_of(fn) == 0 and rv == 0)]
            older = [fn for fn in cur_files if 0 < _rev_of(fn) < rv]
            tagged = [fn for fn in newer if "修订" in fn]
            wrong = [fn for fn in newer if ("修订%d" % rv) not in fn.replace(" ", "")]
            if wrong:
                add("warn", "本稿产物文件名的修订号不对：%s（应为 -修订%d）"
                    % ("、".join(wrong), rv))
            elif not tagged:
                add("warn", "本稿产物文件名还没带「-修订%d」——同目录里未修订的第 %s 稿会和它混在一起"
                    % (rv, s["draft"]))
            if older:
                add("warn", "旧的修订版还留在目录里：%s —— 建议移到 90-共享/归档/，"
                    "否则递文件时容易拿错" % "、".join(older))
    else:
        stray = [m["key"] for m in s["modules"] if m["rev"]]
        if stray:
            add("fail", "这些模块写了 meta.rev，run.json 却没有 rev：%s" % "、".join(stray))

    # ---- scope 指向真实模块 + 编号唯一 ----
    keys = {m["key"] for m in s["modules"]}
    seen, dup = {}, []
    for it in s["scope"]:
        k = it.get("key")
        if k not in keys:
            add("fail", "scope 里的 %r 不在 modules/ 里" % k)
        if it.get("kind") and it["kind"] not in KIND:
            add("warn", "scope %s 的改动类型 %r 不在 新增/修改/删除 里" % (k, it["kind"]))
        what = (it.get("what") or "").strip()
        if not what:
            add("fail", "scope %s 没写改动说明（what）——「改了什么」必须一句话说清" % k)
        elif "<" in what or "一句话" in what:
            add("fail", "scope %s 的改动说明还是草稿占位：%r" % (k, what))
        for c in it.get("chg") or []:
            if not re.match(r"^C\d{1,3}$", c):
                add("fail", "scope %s 的编号 %r 不合规（应形如 C3）" % (k, c))
            if c in seen and seen[c] != k:
                dup.append("%s 同时出现在 %s 与 %s" % (c, seen[c], k))
            seen[c] = k
    if dup:
        add("fail", "改动编号跨模块撞号：%s ——「改③」会指两件事" % "；".join(dup))

    # 范围里标了编号 → 模块数据里要真有这个编号
    for it in s["scope"]:
        m = next((x for x in s["modules"] if x["key"] == it.get("key")), None)
        if not m:
            continue
        if it.get("chg") and not m["chg"]:
            add("warn", "%s 在范围里但没有 data-chg 标注 —— 说了要改，图上没标" % m["key"])
        miss = [c for c in (it.get("chg") or []) if c not in m["chg"]]
        if miss:
            add("warn", "%s 缺这些编号的标注：%s" % (m["key"], "、".join(miss)))

    # 标注必须带稿次：不带就分不出「本稿改的」和「前几稿累积的」，
    # 总览「本次改动」会永远等于累计值。schema 会拦，这里提前提醒更省一轮。
    no_draft = {m["key"]: [c for c, d in (m.get("chg_drafts") or {}).items() if not d]
                for m in s["modules"] if m.get("chg_drafts")}
    no_draft = {k: v for k, v in no_draft.items() if v}
    if no_draft:
        add("warn", "这些标注没写 data-draft（分不出本稿）：%s"
            % "；".join("%s %s" % (k, "、".join(v[:6])) for k, v in no_draft.items()))

    # 本稿要改的模块，得真有属于本稿的标注
    if s["draft"]:
        for it in s["scope"]:
            if it.get("kind") == "删除":
                continue
            m = next((x for x in s["modules"] if x["key"] == it.get("key")), None)
            if not m or not m.get("chg_drafts"):
                continue
            if not any(d == s["draft"] for d in m["chg_drafts"].values()):
                add("warn", "%s 在范围里，但没有一处标注属于第 %d 稿 —— "
                    "新改动要写 data-draft=\"%d\"" % (m["key"], s["draft"], s["draft"]))

    return r


def parse_scope(raw):
    parts = [x.strip() for x in (raw or "").split("|")]
    if len(parts) < 2 or not parts[0]:
        print("！--scope 至少要写 key|一句话，实际：%r" % raw)
        sys.exit(2)
    key = parts[0]
    if len(parts) >= 4:
        kind, what, chg = parts[1], parts[2], parts[3]
    elif len(parts) == 3:
        kinds = [p for p in parts[1:] if p in KIND]
        rest = [p for p in parts[1:] if p not in KIND]
        kind = kinds[0] if kinds else "修改"
        what = " ".join(rest)
        chg = ""
    else:
        kind, what, chg = "修改", parts[1], ""
    if kind not in KIND:
        print("！改动类型只能是 新增/修改/删除，实际：%r" % kind)
        sys.exit(2)
    return {"key": key, "kind": kind, "what": what,
            "chg": [c for c in re.split(r"[,，\s]+", chg) if c]}


def main():
    ap = argparse.ArgumentParser(description="迭代开工：识别稿次、登记终端/版本/范围")
    ap.add_argument("--root", default=".", help="工作台目录（含 run.json）")
    ap.add_argument("--check", action="store_true", help="一致性门禁，不过退出码 1")
    ap.add_argument("--json", action="store_true", help="机器可读")
    ap.add_argument("--set", action="store_true", help="把 mode/terminal/product/draft/scope 写进 run.json")
    ap.add_argument("--mode", choices=("asis", "iterate"), help="交付 A 现状 / 交付 B 迭代")
    ap.add_argument("--terminal", help="管理后台 / 机构端 / 学员端")
    ap.add_argument("--product", help="产品版本，如「管理后台 V5.0」")
    ap.add_argument("--draft", type=int, help="第几稿；不填则按工作台最大值 +1")
    ap.add_argument("--rev", type=int,
                    help="同一稿内的修订序号（修订不推稿次）。推新稿时自动清零，要保留就显式再给")
    ap.add_argument("--scope", action="append", help="key|类型|一句话|C3,C4（可多次）")
    a = ap.parse_args()

    root = os.path.abspath(a.root)
    if not os.path.isdir(root):
        print("！目录不存在：%s" % root)
        return 2

    s = scan(root)

    if a.set:
        runp = os.path.join(root, "run.json")
        run = s["run"] or {}
        if not run:
            print("！%s 不存在，先用 init_run.py 建工作台" % runp)
            return 2
        run["mode"] = a.mode or "iterate"
        if a.terminal:
            run["terminal"] = a.terminal
        if a.product:
            run["product"] = a.product
        # 稿次：显式给了就用；已经登记过就保持（重复 --set 不该一路往后涨）；
        # 都没有才按工作台最大值 +1 建议
        prev_draft = run.get("draft") if isinstance(run.get("draft"), int) else None
        run["draft"] = a.draft or prev_draft or s["suggest_draft"]

        # 修订序号：同稿内的修正，不推稿次。
        # 推了新稿，上一稿的「修订 2」就失去意义（它已经是新稿的基线），所以自动清零；
        # 要保留必须显式 --rev。同稿重复 --set 时保住已有的，不然一登记就丢。
        if prev_draft is not None and run["draft"] != prev_draft:
            run.pop("rev", None)
        if a.rev is not None:
            run["rev"] = a.rev

        scope = []
        nxt = s["next_chg"]
        for raw in a.scope or []:
            it = parse_scope(raw)
            if not it["chg"]:
                it["chg"] = ["C%d" % nxt]
                nxt += 1
            scope.append(it)
        if scope:
            old = {(x.get("key"), x.get("what")): x for x in (run.get("scope") or [])}
            for it in scope:
                old[(it["key"], it["what"])] = it
            run["scope"] = list(old.values())
        save(runp, run)
        print("已登记 → %s" % runp)
        s = scan(root)

    if a.json:
        print(json.dumps({k: v for k, v in s.items() if k != "run"}, ensure_ascii=False, indent=1))
    else:
        print(report(s))

    if a.check:
        print("\n" + "-" * 58)
        res = check(s)
        mark = {"ok": "✓", "warn": "!", "fail": "✗"}
        for lv, msg in res:
            print(" %s %s" % (mark[lv], msg))
        bad = [x for x in res if x[0] == "fail"]
        print("-" * 58)
        if bad:
            print("✗ %d 项不合规。先补齐再写 PRD。" % len(bad))
            return 1
        print("✓ 通过：终端 / 产品版本 / 稿次 / 改动范围 四项一致。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
