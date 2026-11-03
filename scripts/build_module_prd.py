#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把模块 PRD 数据（JSON）注入模板，产出单文件 HTML。

    python3 build_module_prd.py --data module.json --out 字段配置-PRD.html
    python3 build_module_prd.py --data module.json --out x.html --strict

数据 schema 见 references/doc-8sections.md，最小骨架：

{
  "meta": {"module":"…","menu":"一级 / 二级 / 三级","route":"/x/y","env":"测试环境","date":"2026-10-29"},
  "sources": [{"name":"浏览器渲染","status":"已核","detail":"…"}],
  "sections": [{"n":1,"title":"定位","sub":"…","html":"<p>…</p>"}, …,
               {"n":5,"title":"业务规则","rules":true},
               {"n":6,"title":"状态与流转","statemachine":true}],
  "context":  "yaml 文本",
  "entities": "yaml 文本",
  "rules": [{"id":"R-X-01","type":"constraint","statement":"…","confidence":"互证",
             "src":["be","ui"],"evidence":"…","cases":[{"k":"positive","g":"…","w":"…","t":"…"}]}],
  "transitions": {"states":["草稿","启用"],"rows":[{"id":"T1","from":"草稿","to":"启用",
                  "trigger":"提交","guard":"…","label":"提交·校验过","kind":"normal"}]},
  "apis": [{"method":"POST","path":"/x/y","purpose":"…","auth":"…","evidence":"…"}],
  "questions": [{"id":"Q-01","title":"…","why":"…","ask":"…"}],
  "dialogs": [{"type":"弹窗","name":"…","entry":"…","route":"…","covered":true}],
  "layout": "yaml 文本",

  // 只有迭代稿需要：改动台账。id 必须与原型上的 data-chg 同号，
  // 漏一条 schema 就报错——因为漏了不白屏，只会少一张对照卡。
  "changes": [{"id":"C1","no":"①","draft":2,"title":"列表新增一列",
               "where":"字段列表 · 表头",
               "before":["字段名称","状态"],
               "after": ["字段名称","+报名者端可见","状态"],
               "why":"主办方反复问这一列看不看得到，做成列就不用解释了"}]
}
"""

import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
# 模板跟着脚本走，不假设安装位置——团队可能装在用户级或项目级 skills 目录
TPL = os.path.join(HERE, "..", "assets", "module_prd.html")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import schema as S  # noqa: E402  本地契约模块，零外部依赖


def warn(msg):
    print("  ⚠ " + msg, file=sys.stderr)


def check(d, strict):
    """数据体检：结构+语义走 schema.py（唯一契约），这里只补「能过但该提醒」的部分。"""
    errs = S.validate(d)
    warns = []

    # 引擎版本：老版本数据能渲染但合并时会被拒，提前提醒
    if isinstance(d, dict) and d.get("engine") not in (None, S.ENGINE):
        warns.append("engine=%r，当前引擎是 %s —— 合并全量 PRD 时会被拒，请用新版重跑"
                     % (d.get("engine"), S.ENGINE))

    # 能过契约、但质量偏低的情况
    for r in (d.get("rules") or []):
        if len((r.get("statement") or "")) > 160:
            warns.append("%s 的 statement 超过 160 字 —— 一条只该讲一个命题，长的拆开"
                         % r.get("id"))
        if re.search(r"(等等|等[，。]|若干|大概|可能|应该是|类似)", r.get("statement") or ""):
            warns.append("%s 的 statement 含模糊词（等/若干/大概/可能/应该是/类似）"
                         % r.get("id"))
    n_unc = sum(1 for x in (d.get("dialogs") or []) if not x.get("covered"))
    if n_unc:
        warns.append("有 %d 个页面/弹窗标了未覆盖 —— 在全量 PRD 里会显示成缺口" % n_unc)
    if len(d.get("questions") or []) > 12:
        warns.append("待确认 %d 条，偏多 —— 多数应该在闸门 1 当场定掉" % len(d["questions"]))

    # 四块内容
    pf = (d.get("prototype") or {}).get("frames") or []
    if not pf:
        warns.append("没有原型帧 —— 这份 PRD 只有文字没有图")
    elif len(pf) < 1 + len([x for x in (d.get("dialogs") or []) if x.get("covered")]):
        warns.append("原型只有 %d 帧，但清单里 %d 个页面/弹窗标了已覆盖 —— 有态没画"
                     % (len(pf), 1 + len([x for x in (d.get("dialogs") or []) if x.get("covered")])))
    p0 = [f for f in (d.get("facts") or []) if f.get("sev") == "P0"]
    if p0:
        warns.append("事实清单里有 %d 条 P0 需要业务方裁定（id：%s）—— 未裁定前不能出定稿"
                     % (len(p0), "、".join(f.get("id") for f in p0[:6])))

    if errs:
        S.print_errors(errs)
    for w in warns:
        warn(w)

    if errs and strict:
        sys.exit("\n数据不合格（--strict），已终止。修完再来。")
    if errs:
        print("\n  ⚠ 有 %d 个硬错误，仍会生成（去掉 --strict 就是这一档）。交付前必须修。"
              % len(errs), file=sys.stderr)



def _PY():
    """提示语里该写 python 还是 python3 —— Windows 上没有 python3 这个入口。"""
    try:
        import _compat
        return _compat.python_cmd()
    except Exception:  # noqa: BLE001
        return "python3"


def main():
    ap = argparse.ArgumentParser(description="数据 → 单文件模块 PRD")
    ap.add_argument("--data", required=True, help="模块数据 JSON")
    ap.add_argument("--out", required=True, help="输出 HTML")
    ap.add_argument("--facts", help="核查台账 facts/<key>.facts.json。"
                                    "给了就从台账同步事实清单，并写回模块数据，"
                                    "保证只有一份事实源")
    ap.add_argument("--template", default=TPL)
    ap.add_argument("--strict", action="store_true", help="硬错误直接终止")
    a = ap.parse_args()

    if not os.path.exists(a.data):
        sys.exit("✗ 数据文件不存在：%s" % a.data)
    if not os.path.exists(a.template):
        sys.exit("✗ 模板不存在：%s" % a.template)

    try:
        d = json.load(open(a.data, encoding="utf-8"))
    except json.JSONDecodeError as e:
        sys.exit("✗ 数据不是合法 JSON：%s" % e)

    # 事实清单唯一写者是台账；模块数据里的 facts 是它的镜像
    if a.facts:
        if not os.path.exists(a.facts):
            sys.exit("✗ 台账不存在：%s" % a.facts)
        led = json.load(open(a.facts, encoding="utf-8"))
        rows = led.get("facts") or []
        d["facts"] = [S.fact_from_ledger(x) for x in rows]
        json.dump(d, open(a.data, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("从台账同步 %d 条事实，已写回 %s" % (len(rows), os.path.basename(a.data)))

    print("体检数据…")
    check(d, a.strict)

    tpl = open(a.template, encoding="utf-8").read()

    # JSON 里出现 </script> 会提前闭合，统一转义
    payload = json.dumps(d, ensure_ascii=False, indent=1).replace("</", "<\\/")
    inject = "<script>\nwindow.PRD_DATA = %s;\n</script>\n" % payload

    # 插到主脚本之前（模板里第一个 <script> 就是主脚本）
    i = tpl.find("<script>")
    if i < 0:
        sys.exit("✗ 模板里找不到 <script>，模板可能被改坏了")
    html = tpl[:i] + inject + tpl[i:]

    # 标题替换
    title = (d.get("meta") or {}).get("module") or "模块 PRD"
    html = html.replace("<title>模块 PRD</title>", "<title>%s · PRD</title>" % title)

    os.makedirs(os.path.dirname(os.path.abspath(a.out)) or ".", exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        f.write(html)

    n_rule = len(d.get("rules") or [])
    n_case = sum(len(r.get("cases") or []) for r in d.get("rules") or [])
    print("\n→ %s（%.1f KB）" % (a.out, len(html.encode()) / 1024))
    print("  ① 原型 %d 帧 · 文档 %d 段 · 状态机 %d 态 · 实体 %d 个"
          % (len((d.get("prototype") or {}).get("frames") or []),
             len(d.get("sections") or []),
             len(((d.get("transitions") or {}).get("states")) or []),
             len([x for x in (d.get("entities") or "").splitlines() if x and not x.startswith(" ")])))
    print("  ② 用例 %d 条 · ③ 代码栏 大白话 %d / 前后端 %d · ④ 事实 %d（P0 %d）"
          % (len(d.get("testcases") or []),
             len(((d.get("code") or {}).get("plain")) or []),
             len(((d.get("code") or {}).get("fe")) or []) + len(((d.get("code") or {}).get("be")) or []),
             len(d.get("facts") or []),
             len([f for f in (d.get("facts") or []) if f.get("sev") == "P0"])))
    print("  %d 个 case · %d 个接口 · %d 个待确认 · %d 个弹窗/二级页"
          % (n_case, len(d.get("apis") or []),
             len(d.get("questions") or []), len(d.get("dialogs") or [])))
    print("\n下一步：实拍核对")
    print("  %s shot_verify.py --html %s" % (_PY(), a.out))


if __name__ == "__main__":
    import _compat as _c   # 控制台编码兜底（Windows 默认 cp936 编不出 ✓ ✗）
    _c.init()
    main()
