#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""校验合并的前置条件。两种用法问的是两个不同的问题。

  1) 越界校验（默认）—— 改完之后，说好不动的模块真没动吗？
     python scripts/check_untouched.py --base prd-run.bak-20261106 --work prd-run \\
         --scope demo-payout-workbench demo-partner-request

  2) 同源校验（--same-origin）—— 迭代副本 B 是从当前全量 A 复制出来的吗？
     python scripts/check_untouched.py --same-origin --base prd-run-iteration --work prd-run \\
         --scope demo-payout-workbench demo-partner-request

     为什么需要问这个：迭代合回的模型是「A 全量只读 + B 补丁」，只有两份，没有第三份基准。
     A 就是分叉点本身，所以不存在「谁改过」的判定问题——但有一个前提必须成立：
     B 确实是从当前这版 A 长出来的。

     一旦 B 是从更早版本复制出来的，合回就是拿旧内容覆盖新内容，且没有任何提示：
     文件级 hash 只比对「范围」不比对「来源」——范围外的没变、范围内的随便变，
     两道都是绿的，而丢的东西不在任何一道里。

     B 里没被改过的模块就是分叉点留下的指纹。它们与 A 完全一致，才能证明同源。

  3) 两种失败的处理办法完全不同，所以文案分开写。
     越界 → 查为什么被改；不同源 → 重做或人工对齐，不要「先合再看着修」。

  4) 忽略缩进/键序等格式差异，只比语义：加 --semantic

退出码：0 通过 / 1 不通过 / 2 路径有问题
"""

import argparse
import hashlib
import json
import os
import sys


def modules_dir(path):
    """--base / --work 既可以给工作台根目录，也可以直接给 modules 目录。"""
    if not os.path.isdir(path):
        sys.exit(f"路径不存在：{path}")
    sub = os.path.join(path, "modules")
    return sub if os.path.isdir(sub) else path


def digest(path, semantic=False):
    raw = open(path, "rb").read()
    if not semantic:
        return hashlib.sha256(raw).hexdigest()
    try:
        data = json.loads(raw.decode("utf-8"))
    except Exception:
        return hashlib.sha256(raw).hexdigest()
    canon = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


def keys_of(d):
    return {f[:-5]: os.path.join(d, f) for f in os.listdir(d) if f.endswith(".json")}


def _rel(a, b):
    """A 侧内容 a 与 B 侧内容 b 的关系。

    不需要第三份基准也能判断一问：这一块到底是「B 在 A 上加的」，还是
    「A 那边也被改过」。靠的是内容包含——我改的时候是在 A 的原文上接着写，
    所以 A 的那部分必然完整出现在 B 里。反过来，A 里有而 B 里没有的片段，
    只可能是收到 B 之后才加进 A 的。
    """
    if a == b:
        return "same"
    if not a:
        return "b_only"          # A 空、B 有：新加的
    if not b:
        return "a_only"          # A 有、B 空：A 后来加的，或我在 B 里删了
    if a in b:
        return "b_extend"        # B 包含 A 全文：在 A 基础上加东西
    if b in a:
        return "a_extend"        # A 包含 B 全文：A 那边加过东西
    return "diverge"             # 两边都动过同一块


def scope_diff(bdir, wdir, scope):
    """scope 内 A 与 B 的逐块差异。拷回只保留 B 的版本，A 那侧的同位改动会丢。

    指纹（scope 外）只能证明「两份整体同源」，它测不到 scope 内——
    而 scope 内恰恰是真正会被覆盖的部分。
    """
    rows = []
    for k in sorted(scope):
        pb, pw = os.path.join(bdir, k + ".json"), os.path.join(wdir, k + ".json")
        if not (os.path.isfile(pb) and os.path.isfile(pw)):
            continue
        try:
            B = json.load(open(pb, encoding="utf-8"))
            A = json.load(open(pw, encoding="utf-8"))
        except Exception:
            continue

        hits = []

        def blocks(doc, tag):
            if tag == "frames":
                return {f.get("id"): (f.get("html") or "")
                        for f in (doc.get("prototype") or {}).get("frames") or []}
            return {s.get("n"): (s.get("html") or "") for s in doc.get("sections") or []}

        for tag, fmt in (("sections", "第%s段"), ("frames", "帧 %s")):
            mb, mw = blocks(B, tag), blocks(A, tag)
            for kk in sorted(set(mb) | set(mw), key=lambda x: str(x)):
                r = _rel(mw.get(kk, ""), mb.get(kk, ""))
                if r != "same":
                    hits.append((fmt % kk, r))

        rb = {r.get("id") for r in B.get("rules") or []}
        ra = {r.get("id") for r in A.get("rules") or []}
        if ra - rb:
            hits.append(("规则 A 有 B 没有：" + "、".join(sorted(x for x in ra - rb if x)), "a_only"))
        if rb - ra:
            hits.append(("规则 B 有 A 没有：" + "、".join(sorted(x for x in rb - ra if x)), "b_only"))

        if hits:
            rows.append((k, hits))
    return rows


def print_scope_diff(rows):
    """只报有风险的块。正常扩写的那些不刷屏，一句汇总带过。"""
    risky = [(k, h) for k, h in rows if any(r in ("a_extend", "a_only", "diverge") for _, r in h)]
    mine = sum(1 for _, h in rows for _, r in h if r in ("b_extend", "b_only"))
    if not rows:
        return False

    print("─" * 60)
    if mine:
        print(f"scope 内 {mine} 处是 B 在 A 基础上扩写，装进去就是你的改动。")
    if not risky:
        return False

    n_risky = sum(1 for _, h in risky for _, r in h if r in ("a_extend", "a_only", "diverge"))
    print(f"⚠ 另有 {n_risky} 处，A 那侧也有 B 没有的内容：")
    for k, hits in risky:
        print(f"  {k}")
        for label, r in hits:
            if r == "a_extend":
                print(f"    {label}   A 有 B 没有的内容   ← 装进去会丢")
            elif r == "a_only":
                print(f"    {label}   A 有、B 没有        ← 装进去会丢")
            elif r == "diverge":
                print(f"    {label}   两边都改过这一块    ← 装进去只剩 B 的版本")
    print("  确认这些是你自己在 B 里删掉的；否则说明 A 在中途被改过，")
    print("  而指纹测不到这种情况（它只看 scope 外）。这时别直接装，先把 A 的那版备份出来。")
    return True


def read_origin(bdir):
    """找 B 目录里的来源身份证。老工作台没有这个文件，返回 (None, None)。

    骨架版（建台时 init_run 立的）不算数：那时模块文件还是骨架，拿它的指纹
    去比对，会把「内容还没填」误判成「全量变了」。第一次出全量才换成正式版。
    """
    for cand in (os.path.join(bdir, "origin.json"),
                 os.path.join(os.path.dirname(bdir), "origin.json")):
        if os.path.isfile(cand):
            try:
                data = json.load(open(cand, encoding="utf-8"))
            except Exception:
                return None, None
            if data.get("state") == "skeleton":
                return None, cand
            return data, cand
    return None, None


def same_origin(bdir, wdir, base, work, scope, a):
    """B（--base，迭代副本）与 A（--work，当前全量）是否同源。

    优先看来源身份证（origin.json）：那是出全量时写下的「这一版由谁组成」，
    B 复制时一起带走，直接比对就是确定答案，没有盲区。
    老工作台没有身份证，退回去看指纹（B 里未改模块与 A 是否一致）——
    间接证据，scope 覆盖全部模块时会失效。
    """
    origin, opath = read_origin(bdir)
    if not a.quiet and opath and not origin:
        print(f"！ {opath} 是建台时立的骨架身份证，还没出过全量，不作数。")
        print("  第一次 merge_modules 出全量时会换成正式身份证。下面按指纹判定。")
    # --semantic 只对字节指纹无效，对身份证也没意义（存的是文件 hash）
    if origin and not a.semantic:
        return _by_ticket(origin, opath, bdir, wdir, work, scope, a)
    return _by_fingerprint(bdir, wdir, base, work, scope, a)


def _by_ticket(origin, opath, bdir, wdir, work, scope, a):
    """按身份证判定：出证之后，全量这边有没有动过。

    这里**不跳过 scope**。身份证记的是「出证那一刻全量的样子」，与本次要改哪几个
    模块无关：只要 A 变过，B 就是基于旧版，合回会丢东西——哪怕变的地方正好在
    scope 内、本来就要被覆盖。这正是指纹模式做不到的那一格。
    """
    rec = origin.get("modules") or {}
    drift, gone, extra, ok = [], [], [], []

    for k in sorted(rec):
        if k not in work:
            gone.append(k)                       # 出证时在，现在没了
        elif digest(work[k]) != rec[k]:
            drift.append(k)                      # 出证之后被改过
        else:
            ok.append(k)

    for k in sorted(work):
        if k not in rec:
            extra.append(k)                      # 出证之后新增

    # scope 内 A 与 B 已经一模一样 → 这次改动看起来已经装进去了。
    # 只用来决定措辞：同样是「变了」，已经合过的 B 该丢，没合过的要重做。
    merged = []
    for k in sorted(scope):
        pb, pw = os.path.join(bdir, k + ".json"), os.path.join(wdir, k + ".json")
        if os.path.isfile(pb) and os.path.isfile(pw) and digest(pb) == digest(pw):
            merged.append(k)

    if not a.quiet:
        print(f"来源身份证  {opath}  （第 {origin.get('draft') or '?'} 稿 · {origin.get('built_at') or '?'}）")
        print(f"当前全量 A  {wdir}  （{len(work)} 个模块）")
        print(f"本次覆盖    {len(scope)} 个：{'、'.join(sorted(scope)) or '无'}")
        print("─" * 60)
        for k in ok:
            mark = "（本次要改）" if k in scope else ""
            print(f"  对得上  {k}{mark}")
        for k in drift:
            if k in merged:
                mark = "  ← 已合入全量（A 与 B 一致）"
            elif k in scope:
                mark = "  ← 在本次范围里，得基于新版重改"
            else:
                mark = ""
            print(f"  变了    {k}   ← 出证之后，全量这边又改过{mark}")
        for k in gone:
            print(f"  已删    {k}   ← 出证时在，全量现在没有")
        for k in extra:
            print(f"  全量新增 {k}   ← 出证之后加的（合完保留即可）")

    bad = bool(drift or gone)
    if bad:
        if not a.quiet:
            print_scope_diff(scope_diff(bdir, wdir, scope))
            print("─" * 60)
            print("✗ 不通过：B 带着旧身份证，全量已经往前走过。")
            if merged and set(merged) >= set(scope):
                print("  看起来这次改动**已经合进全量**了（scope 内 A 与 B 完全一样）。")
                print("  那 B 就该废弃，下次迭代从当前全量重新复制，别拿它再合一次。")
            else:
                if merged:
                    print(f"  其中 {'、'.join(merged)} 已经合进去了；剩下的还没合。")
                print("  没合的那几个：直接合会拿旧内容盖掉全量的新内容。")
                print("  处理：")
                print("    · 从当前全量重新复制一份，把这次改动重做")
                print("    · 或只把那几个没变的模块合回去，动过的逐个确认后手工对齐")
        return 1

    risky = False
    if not a.quiet:
        risky = print_scope_diff(scope_diff(bdir, wdir, scope))

    if not a.quiet:
        if risky:
            print(f"⚠ 有条件通过：身份证对得上（{len(ok)} 个模块），但 scope 内有上面几处要先确认。")
        else:
            print(f"✓ 通过：身份证对得上，出证之后全量有 {len(ok)} 个模块没动过。")
        if extra:
            print(f"  当前全量比出证时多 {len(extra)} 个模块（{'、'.join(extra)}），合完保留。")
        print(f"  可以合：只拷 scope 内那 {len(scope)} 个模块覆盖全量，其余不要动。")
    return 0


def _by_fingerprint(bdir, wdir, base, work, scope, a):
    """按指纹判定（老工作台，没有 origin.json）。scope 全覆盖时会失效。"""
    fp = [k for k in sorted(base) if k not in scope]
    drift, gone, extra, ok = [], [], [], []

    for k in fp:
        if k not in work:
            gone.append(k)                                   # B 有、A 没有
        elif digest(base[k], a.semantic) != digest(work[k], a.semantic):
            drift.append(k)                                  # 两边都有，内容不同
        else:
            ok.append(k)

    for k in sorted(work):
        if k not in base and k not in scope:
            extra.append(k)                                  # A 有、B 没有

    if not a.quiet:
        print(f"迭代副本 B  {bdir}  （{len(base)} 个模块）")
        print(f"当前全量 A  {wdir}  （{len(work)} 个模块）")
        print(f"本次覆盖    {len(scope)} 个：{'、'.join(sorted(scope)) or '无'}")
        print(f"指纹模块    {len(fp)} 个（未改，用来证明同源）")
        print("─" * 60)
        for k in ok:
            print(f"  同源    {k}")
        for k in drift:
            print(f"  不同源  {k}   ← B 与全量都有，内容不一样")
        for k in gone:
            print(f"  不同源  {k}   ← B 里有，当前全量没有")
        for k in extra:
            print(f"  全量新增 {k}   ← 当前全量有，B 里没有（合完保留即可）")

    # extra 不算失败：全量比 B 多出模块，说明 A 正常长过新东西，
    # 合回只覆盖 scope 内，那些新模块不受影响。只有「内容对不上」和
    # 「B 有 A 没有」才真的危险——前者说不清哪个对，后者合完会复活已删的模块。
    bad = bool(drift or gone)
    if bad:
        if not a.quiet:
            print("─" * 60)
            print("✗ 不通过：B 与当前全量不同源。")
            print("  B 不是从这版全量复制出来的。合回去会拿旧内容覆盖新内容，")
            print("  而且覆盖之后看不出来——范围校验只问「动了哪些」，不问「基于哪版」。")
            print("  处理：")
            print("    · 最省事：从当前全量重新复制一份，把这次改动重做一遍")
            print("    · 或逐个确认上面几个模块哪个内容才对，手工对齐后再合")
            print("    · 不要「先合进去再看着修」，那样会连哪句是原样都说不清")
        return 1

    # 指纹只能证明两份整体同源，它测不到 scope 内——而 scope 内才是真正被覆盖的部分。
    risky = False
    if not a.quiet:
        risky = print_scope_diff(scope_diff(bdir, wdir, scope))

    if not fp:
        if not a.quiet:
            print("─" * 60)
            print("⚠ 未验证：scope 覆盖了全部模块，没有指纹可用。")
            print("  这种情况合回去等于整体替换，同源校验使不上力。")
            print("  只能靠「B 是从当前全量复制的」这条纪律，或人工比对一遍。")
        return 0

    if not a.quiet:
        if risky:
            print(f"⚠ 有条件通过：指纹一致（{len(ok)} 个），但 scope 内有上面几处要先确认。")
        else:
            print(f"✓ 通过：B 与当前全量同源，{len(ok)} 个指纹模块一字节一致。")
        if extra:
            print(f"  注意：当前全量比 B 多 {len(extra)} 个模块（{'、'.join(extra)}），")
            print("  那是别的批次合进去的，合完照样保留，别删。")
        print(f"  可以合：只拷 scope 内那 {len(scope)} 个模块覆盖全量，其余不要动。")
    return 0


def main():
    ap = argparse.ArgumentParser(description="校验合并前后的范围与来源")
    ap.add_argument("--base", required=True,
                    help="越界模式：改动前的目录；同源模式：迭代副本 B")
    ap.add_argument("--work", required=True,
                    help="越界模式：改动后的目录；同源模式：当前全量 A")
    ap.add_argument("--scope", nargs="+", default=[], help="允许改动的模块 key")
    ap.add_argument("--same-origin", action="store_true",
                    help="改判：检查 B（--base）是否从当前全量 A（--work）复制而来")
    ap.add_argument("--semantic", action="store_true",
                    help="忽略缩进与键顺序，只比语义（默认严格比字节）")
    ap.add_argument("--quiet", action="store_true", help="只输出结论")
    a = ap.parse_args()

    bdir, wdir = modules_dir(a.base), modules_dir(a.work)
    base, work = keys_of(bdir), keys_of(wdir)
    scope = set(a.scope)

    if a.same_origin:
        return same_origin(bdir, wdir, base, work, scope, a)

    changed, missing, added, clean = [], [], [], []

    for k in sorted(base):
        if k in scope:
            continue
        if k not in work:
            missing.append(k)
            continue
        if digest(base[k]) != digest(work[k], a.semantic):
            changed.append(k)
        else:
            clean.append(k)

    for k in sorted(work):
        if k not in base:
            added.append(k)

    if not a.quiet:
        print(f"基准  {bdir}  （{len(base)} 个模块）")
        print(f"改动后 {wdir}  （{len(work)} 个模块）")
        print(f"范围内（允许改） {len(scope & set(base))} 个："
              f"{'、'.join(sorted(scope & set(base))) or '无'}")
        print("─" * 56)
        for k in clean:
            print(f"  ok    {k}")
        for k in changed:
            print(f"  越界  {k}   ← 不在范围里，但内容变了")
        for k in missing:
            print(f"  丢失  {k}   ← 不在范围里，却被删了")
        for k in added:
            print(f"  新增  {k}   ← 不在基准里，确认是不是这一稿要加的")
        print("─" * 56)

    bad = bool(changed or missing)
    if bad:
        print("不通过：范围外的模块被改动了。")
        print("处理原则：不要试图把改动「合进去」，先查清楚它为什么被改——")
        print("  · 顺手修的 → 从 base 恢复，改动挪到下一稿")
        print("  · 本次必需的连带修改 → 说明范围漏列，补进 scope 并重新登记 C{n}")
        print("  · 工具回写的 → 检查 build_module_prd.py --facts 是不是改了别的模块")
        return 1

    if added:
        print(f"通过，但有 {len(added)} 个新模块，请确认它们确实属于本稿范围。")
    else:
        print(f"通过：范围内 {len(scope & set(base))} 个可改，其余 {len(clean)} 个一字节未动。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
