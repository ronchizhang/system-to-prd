#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把单文件 PRD 拆成每模块一个 JSON，方便逐模块改。

用法:
    python3 split_prd.py 原稿.html ./mods
    python3 split_prd.py 原稿.html ./mods --with-overview     # 同时导出 meta/overview 到 _overview.json

产出:
    ./mods/<meta.key>.json     每个模块一份
    ./mods/_overview.json      仅 --with-overview
"""
import json, os, sys


def main():
    args = [x for x in sys.argv[1:] if not x.startswith('--')]
    if len(args) < 2:
        sys.exit(__doc__)
    src, outdir = args[0], args[1]

    html = open(src, encoding='utf-8').read()
    anchor = 'window.PRD_DATA = '
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

    # 单模块产物没有 modules 这层包裹，D 自己就是一个模块。
    # v7.1 的四个瘦身脚本都只按「合并后的全量」写，拿单模块示例一跑就是 0 个模块——
    # 而实际最常拆的恰恰是单个模块。
    mods = D.get('modules') or ([D] if D.get('meta') and D.get('sections') else [])

    os.makedirs(outdir, exist_ok=True)
    for m in mods:
        k = (m.get('meta') or {}).get('key')
        if not k:
            continue
        p = os.path.join(outdir, k + '.json')
        json.dump(m, open(p, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print('  %-30s %6d bytes' % (k, os.path.getsize(p)))

    if '--with-overview' in sys.argv:
        ov = {'meta': D.get('meta', {}), 'overview_html': D.get('overview_html', '')}
        p = os.path.join(outdir, '_overview.json')
        json.dump(ov, open(p, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print('  %-30s %6d bytes' % ('_overview', os.path.getsize(p)))

    print('共 %d 个模块 → %s' % (len(mods), outdir))


if __name__ == '__main__':
    main()
