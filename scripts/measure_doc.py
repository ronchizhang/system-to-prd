#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""量一份 PRD 的「体重」：找出现在哪一段最肥。

用法:
    python3 measure_doc.py 文档.html
    python3 measure_doc.py 文档.html --module demo-payout-workbench   # 只看一个模块的分段
    python3 measure_doc.py 文档.html --top 15                        # 长段落条数
"""
import json, re, sys, statistics

CJK = re.compile(r'[\u4e00-\u9fff]')


def load_prd(path):
    """从单文件 PRD 的 HTML 里取出 window.PRD_DATA。括号配对，不用正则。"""
    html = open(path, encoding='utf-8').read()
    anchor = 'window.PRD_DATA = '
    if anchor not in html:
        sys.exit('找不到 window.PRD_DATA，这不是 system-to-prd 的产物？')
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


def txt(h):
    h = re.sub(r'<[^>]+>', '', h or '').replace('&nbsp;', ' ')
    return re.sub(r'\s+', ' ', h).strip()


def cjk(s):
    return len(CJK.findall(s))


def cols_of(table):
    hd = re.search(r'<tr>\s*((?:<th[^>]*>[\s\S]*?</th>\s*)+)</tr>', table)
    return len(re.findall(r'<th', hd.group(1))) if hd else 0


def main():
    args = sys.argv[1:]
    if not args:
        sys.exit(__doc__)
    path = args[0]
    only = None
    top = 10
    if '--module' in args:
        only = args[args.index('--module') + 1]
    if '--top' in args:
        top = int(args[args.index('--top') + 1])

    D = load_prd(path)
    mods = D.get('modules', [])
    # 单模块产物里没有 modules 这层包裹，D 自己就是一个模块。
    # 不加这一条，量单个模块会得到「模块 0 个」然后除零崩——而「先量一个模块，
    # 再决定要不要整份瘦」恰恰是最常见的用法。
    if not mods and D.get('meta') and D.get('sections'):
        mods = [D]
    print('文档: %s' % path)
    print('标题: %s' % (D.get('meta', {}).get('title', '-')))
    print('模块: %d 个\n' % len(mods))

    total = 0
    rows = []
    for m in mods:
        key = m.get('meta', {}).get('key', '?')
        secs = m.get('sections', [])
        s = [(x.get('n'), x.get('title', ''), cjk(txt(x.get('html')))) for x in secs]
        mt = sum(x[2] for x in s)
        total += mt
        rows.append((key, mt, s))

    brief = cjk(txt(D.get('meta', {}).get('project_brief', '')))
    ov = cjk(txt(D.get('overview_html', '')))
    grand = total + brief + ov
    if not grand:
        sys.exit('这份文档没有可统计的中文正文（模块 %d 个）。'
                 '确认路径是不是 system-to-prd 构建出来的单文件 HTML。' % len(mods))

    print('=== 一、模块占比 ===')
    print('%-28s %7s %7s' % ('模块', '字数', '占全文'))
    for key, mt, _ in rows:
        print('%-28s %7d %6.0f%%' % (key, mt, 100.0 * mt / grand))
    print('%-28s %7d %6.0f%%' % ('概览 + 前言', brief + ov, 100.0 * (brief + ov) / grand))
    print('%-28s %7d' % ('合计', grand))

    print('\n=== 二、分段（找占比 >30% 的那段）===')
    for key, mt, s in rows:
        if only and key != only:
            continue
        print('\n%s  共 %d 字' % (key, mt))
        for n, title, c in s:
            bar = '#' * int(40.0 * c / mt) if mt else ''
            flag = '  <== 优先' if mt and c / mt >= 0.30 else ''
            print('  段%-2s %-18s %6d  %4.0f%% %s%s'
                  % (n, title[:18], c, 100.0 * c / mt if mt else 0, bar, flag))

    print('\n=== 三、表格列数分布（>4 列要砍）===')
    dist = {}
    wide = []
    for m in mods:
        for sec in m.get('sections', []):
            for t in re.findall(r'<table[\s\S]*?</table>', sec.get('html') or ''):
                n = cols_of(t)
                if not n:
                    continue
                dist[n] = dist.get(n, 0) + 1
                if n > 4:
                    first = re.sub(r'<[^>]+>', ' ', t)[:70].strip()
                    wide.append((n, m.get('meta', {}).get('key', ''), sec.get('n'), first))
    tot_t = sum(dist.values()) or 1
    for n in sorted(dist):
        print('  %d 列: %2d 个 (%2.0f%%)' % (n, dist[n], 100.0 * dist[n] / tot_t))
    if wide:
        print('  超过 4 列的：')
        for n, k, sn, f in wide[:12]:
            print('    %d 列 | %s 段%s | %s' % (n, k[:14], sn, f))

    print('\n=== 四、超长段落（>110 字）===')
    longs = []
    for m in mods:
        for sec in m.get('sections', []):
            for p in re.findall(r'<p[^>]*>([\s\S]*?)</p>', sec.get('html') or ''):
                t = txt(p)
                if cjk(t) > 110:
                    longs.append((cjk(t), m.get('meta', {}).get('key', ''), sec.get('n'), t[:60]))
    print('  共 %d 段' % len(longs))
    for n, k, sn, t in sorted(longs, reverse=True)[:top]:
        print('    %4d 字 | %s 段%s | %s' % (n, k[:14], sn, t))

    print('\n=== 五、句长 ===')
    body = ' '.join(txt(x.get('html')) for m in mods for x in m.get('sections', []))
    sents = [x for x in re.split(r'[。！？；]', body) if cjk(x) > 1]
    L = [cjk(x) for x in sents]
    if L:
        print('  句数 %d · 平均 %.1f · 中位 %d · P90 %d · 最长 %d'
              % (len(L), statistics.mean(L), statistics.median(L),
                 sorted(L)[int(len(L) * 0.9)], max(L)))
        print('  超 40 字占 %.0f%%' % (100.0 * sum(1 for x in L if x > 40) / len(L)))


if __name__ == '__main__':
    main()
