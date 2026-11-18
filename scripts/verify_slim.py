#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""结构等价校验：瘦身只许改字，不许动骨架。

用法:
    python3 verify_slim.py 原稿.html 改后.html
    python3 verify_slim.py 原稿.html 改后.html --ignore-xref F-99,R-XYZ-01

检查项（任一不过即退出码 1）:
    1. 模块数、模块顺序、meta.key 一致
    2. 每模块 sections 数一致
    3. data-chg 多重集一致（改动点一个不能少、也不能多）
    4. data-xa 集合零丢失（引用不许丢）
    5. rules / testcases / facts / questions 条数一致
    6. 新稿里没有裸露的占位符（@@KEY@@ / %(KEY)s）或未闭合表格
"""
import json, re, sys
from collections import Counter


def load_prd(path):
    html = open(path, encoding='utf-8').read()
    anchor = 'window.PRD_DATA = '
    if anchor not in html:
        sys.exit('找不到 window.PRD_DATA: %s' % path)
    i = html.index(anchor) + len(anchor)
    depth = 0
    instr = False
    esc = False
    j = i
    while j < len(html):
        c = html[j]
        if instr:
            if esc:
                esc = False
            elif c == '\\':
                esc = True
            elif c == '"':
                instr = False
        else:
            if c == '"':
                instr = True
            elif c == '{':
                depth += 1
            elif c == '}':
                depth -= 1
                if depth == 0:
                    j += 1
                    break
        j += 1
    return json.loads(html[i:j])


def body_of(m):
    return ' '.join(x.get('html') or '' for x in m.get('sections', []))


def main():
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    a, b = sys.argv[1], sys.argv[2]
    ignore = set()
    if '--ignore-xref' in sys.argv:
        ignore = set(x.strip() for x in sys.argv[sys.argv.index('--ignore-xref') + 1].split(',') if x.strip())

    A, B = load_prd(a), load_prd(b)
    # 单模块产物没有 modules 包裹：把 D 自己当成唯一的模块，否则两边都是空列表，
    # 「模块数一致 / 顺序一致」全部空过，校验就成了摆设。
    def norm(D):
        mods = D.get('modules')
        if mods:
            return mods
        return [D] if (D.get('meta') and D.get('sections')) else []
    ma, mb = norm(A), norm(B)
    fails = []

    if len(ma) != len(mb):
        fails.append('模块数不一致: %d → %d' % (len(ma), len(mb)))

    for x, y in zip(ma, mb):
        ka = x.get('meta', {}).get('key', '?')
        kb = y.get('meta', {}).get('key', '?')
        if ka != kb:
            fails.append('模块顺序错位: %s vs %s' % (ka, kb))
            continue

        sa, sb = len(x.get('sections', [])), len(y.get('sections', []))
        if sa != sb:
            fails.append('%s 段数: %d → %d' % (ka, sa, sb))

        ba, bb = body_of(x), body_of(y)
        ca = Counter(re.findall(r'data-chg="(C\d+)"', ba))
        cb = Counter(re.findall(r'data-chg="(C\d+)"', bb))
        if ca != cb:
            lost = {k: v for k, v in ca.items() if cb.get(k, 0) != v}
            fails.append('%s 改动点标注不一致: %s' % (ka, lost))

        xa = set(re.findall(r'data-xa="([^"]+)"', ba)) - ignore
        xb = set(re.findall(r'data-xa="([^"]+)"', bb))
        lost = sorted(xa - xb)
        if lost:
            fails.append('%s 引用丢失: %s' % (ka, ', '.join(lost)))

        for field in ('rules', 'testcases', 'facts', 'questions'):
            na, nb = len(x.get(field, [])), len(y.get(field, []))
            if na != nb:
                fails.append('%s %s 条数: %d → %d' % (ka, field, na, nb))

        # 裸露占位符 / 未闭合表格
        if re.search(r'@@\w+@@|%\(\w+\)s', bb):
            fails.append('%s 有残留占位符: %s'
                         % (ka, re.findall(r'@@\w+@@|%\(\w+\)s', bb)[:3]))
        if bb.count('<table') != bb.count('</table>'):
            fails.append('%s table 标签未闭合' % ka)
        # div 只比「差值是否变了」：原稿可能本来就有历史遗留的不平衡，
        # 那不是我改出来的，不该拦住我；我要抓的是自己新引入的不平衡。
        da = len(re.findall(r'<div\b', ba)) - ba.count('</div>')
        db = len(re.findall(r'<div\b', bb)) - bb.count('</div>')
        # 原稿可能本来就不平衡（历史遗留），所以只拦「变差」：
        # 绝对值变大，或本来是平的变成不平。从 -1 修成 0 是好事，放行。
        if abs(db) > abs(da) or (da == 0 and db != 0):
            fails.append('%s div 标签平衡被破坏: 差值 %d → %d' % (ka, da, db))

    # 概览侧
    if 'overview_html' in A and 'overview_html' in B:
        pass  # 概览允许自由重写

    if fails:
        print('不合格（%d 项）:' % len(fails))
        for f in fails:
            print('  ✗ ' + f)
        return 1

    print('通过：模块数、段结构、改动点标注、交叉引用、规则/用例/事实条数 全部一致。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
