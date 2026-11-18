#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把改好的模块 JSON 注回单文件 PRD，只替换 window.PRD_DATA 的数据段，前后缀一字不动。

用法:
    python3 inject_prd.py 源.html 模块目录 输出.html
    python3 inject_prd.py 源.html 模块目录 输出.html --overview overview_new.json

约定:
    - 模块目录里放 *.json，每个是一个 module 对象（含 meta.key）
    - 文件名随意，按 meta.key 匹配；.orig / .bak / .tmp 会被跳过
    - --overview 可选，传一个 {"meta": {...}, "overview_html": "..."} 覆盖概览

工作流:
    python3 measure_doc.py 原稿.html            # 找到最肥的段
    # 从原稿拆模块 JSON（见 --split），逐模块改
    python3 inject_prd.py 原稿.html ./mods out.html
    python3 verify_slim.py 原稿.html out.html
"""
import json, os, sys, glob


def main():
    args = [x for x in sys.argv[1:] if not x.startswith('--')]
    if len(args) < 3:
        sys.exit(__doc__)
    src, moddir, dst = args[0], args[1], args[2]

    html = open(src, encoding='utf-8').read()
    anchor = 'window.PRD_DATA = '
    if anchor not in html:
        sys.exit('找不到 window.PRD_DATA: %s' % src)
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
    D = json.loads(html[i:j])

    # 概览覆盖
    if '--overview' in sys.argv:
        ovf = sys.argv[sys.argv.index('--overview') + 1]
        OV = json.load(open(ovf, encoding='utf-8'))
        if 'meta' in OV:
            D['meta'] = OV['meta']
        if 'overview_html' in OV:
            D['overview_html'] = OV['overview_html']
        print('已覆盖 meta / overview_html ← %s' % ovf)

    # 读模块
    newmods = {}
    for p in sorted(glob.glob(os.path.join(moddir, '*.json'))):
        if any(x in os.path.basename(p) for x in ('.orig', '.bak', '.tmp')):
            continue
        try:
            m = json.load(open(p, encoding='utf-8'))
        except Exception as e:
            print('跳过（不是合法 JSON）: %s  %s' % (p, e))
            continue
        k = (m.get('meta') or {}).get('key')
        if not k:
            print('跳过（没有 meta.key）: %s' % p)
            continue
        newmods[k] = m

    if not newmods:
        sys.exit('目录里没有可用的模块 JSON: %s' % moddir)

    # 单模块产物：D 自己就是那个模块，整份换掉；不能包成 modules 结构，
    # 那会改掉数据形状，前端渲染直接崩。
    single = not D.get('modules') and D.get('meta') and D.get('sections')
    if single:
        k0 = D['meta'].get('key')
        if k0 not in newmods:
            sys.exit('单模块文档的 key 是 %s，目录里没有同名 JSON' % k0)
        D = newmods[k0]
        hit = [k0]
    else:
        order = [m['meta']['key'] for m in D['modules']]
        hit = []
        for idx, k in enumerate(order):
            if k in newmods:
                D['modules'][idx] = newmods[k]
                hit.append(k)
        unknown = set(newmods) - set(order)
        if unknown:
            print('警告：这些 key 不在文档里，已忽略 → %s' % ', '.join(sorted(unknown)))
        if not hit:
            sys.exit('没有一个模块 key 能对上，检查 meta.key')

    out = html[:i] + json.dumps(D, ensure_ascii=False, indent=1) + html[j:]

    # 顺带修一处窄栏压字：dialogTable() 的 th 写死 px 会把最后一列压成竖排
    for a, b in [('width:76px">类型', 'width:11%">类型'),
                 ('width:180px">名称', 'width:20%">名称'),
                 ('width:200px">入口', 'width:30%">入口'),
                 ('width:60px">覆盖', 'width:9%">覆盖')]:
        out = out.replace(a, b)

    open(dst, 'w', encoding='utf-8').write(out)
    print('替换模块: %s' % ', '.join(hit))
    print('写出 %s  %d bytes（原 %d）' % (dst, len(out), len(html)))


if __name__ == '__main__':
    main()
