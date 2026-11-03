#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""给一个模块初始化工作台。同事拿到目录后只做三件事：填 facts、回答问题、填 module。

    # 一个人负责一个模块（最常见）
    python3 init_run.py --root ./prd-run --project "示例后台" \
        --module "管理后台|报名管理 / 报名字段配置|ops-person-field|张三"

    # 一次给整个团队铺开
    python3 init_run.py --root ./prd-run --project "示例后台" \
        --module "管理后台|报名管理 / 报名字段配置|ops-person-field|张三" \
        --module "管理后台|客户中心 / 客户列表|ops-customer|李四"

    # 看现有工作台里谁交了、谁没交
    python3 init_run.py --root ./prd-run --list

产出的目录：

    prd-run/
    ├── run.json                 项目级登记：引擎版本、模块分配、创建时间
    ├── 怎么干活.md               操作卡（从 skill 手册复制，离线也能看）
    ├── modules/<key>.json        ← 唯一要人工填的文件
    ├── facts/<key>.facts.json    ← 五源事实台账（闸门 1）
    └── out/<key>.html            ← 构建产物，不许手改
"""

import argparse
import datetime as dt
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def _PY():
    """提示语里该写 python 还是 python3 —— Windows 上没有 python3 这个入口。"""
    try:
        import _compat
        return _compat.python_cmd()
    except Exception:  # noqa: BLE001
        return "python3"

SKILL = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import schema as S  # noqa: E402

TODO = "<!-- __TODO__ "


def now():
    return dt.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def skeleton_module(sysname, menu, key, owner, project):
    """骨架：8 段标题与结构全部就位，正文留 TODO。build 能跑通、能看见成品形态，
    但 check_delivery 会因为残留 TODO 拒绝交付——先看得见，再往里填。"""
    parts = menu.split("/")
    module = parts[-1].strip()
    first = parts[0].strip() if parts else module

    sec_titles = [(n, t) for n, t in S.SECTION_PLAN]
    sections = []
    for n, t in sec_titles:
        s = {"n": n, "title": t, "sub": "", "html": ""}
        if n == 5:
            s["rules"] = True
        elif n == 6:
            s["statemachine"] = True
        else:
            s["html"] = (TODO + "%d %s：这一段要写的内容见 references/doc-8sections.md -->\n"
                         "<p>待填写。</p>" % (n, t))
        sections.append(s)

    return {
        "schema": S.SCHEMA_ID,
        "engine": S.ENGINE,
        "meta": {
            "key": key,
            "system": sysname,
            "module": module,
            "menu": " / ".join(x.strip() for x in parts),
            "route": "TODO 填真实路由，如 /activity/xxx/list",
            "env": "TODO 测试环境域名，如 测试环境 test1demo",
            "customer": "",
            "date": dt.date.today().isoformat(),
            "version": "v0.1 草稿",
            "owner": owner,
        },
        "sources": [
            {"name": n, "status": "未核", "detail": TODO + "%s：写清核了什么、拿到什么数字 -->" % n}
            for n in ("浏览器渲染", "后端接口", "前端代码", "后端代码", "用例库", "业务确认")
        ],
        "sections": sections,
        "context": TODO + "为什么这样设计（业务前提、不能改的约束）。"
                   "这段是防止 AI 把设计改错的关键，见 references/doc-8sections.md -->\n",
        "entities": TODO + "实体、字段、枚举、状态。YAML 文本 -->\n",
        "rules": [{
            "id": "R-XXX-MOD-00",
            "type": "principle",
            "confidence": "确立",
            "src": ["biz"],
            "statement": "【示例·替换或删除】一句话只讲一个命题，不用代词，不写「等」",
            "evidence": "具体到接口 / 文件:行 / 用例标题，不写「实测」两字了事",
            "cases": [{"k": "positive", "g": "前置条件", "w": "动作", "t": "可判定的预期"}],
            "note": "示例条目。真规则从 facts 台账里逐条搬过来，编号 R-{系统}-{模块}-{序号}",
        }],
        "transitions": {
            "states": ["草稿", "启用"],
            "rows": [{"id": "T1", "from": "草稿", "to": "启用", "trigger": "提交",
                      "guard": "TODO 什么条件下才允许", "label": "提交", "kind": "normal"}],
            "caption": "",
            "confidence": "TODO 哪几条有实证、哪几条是推论",
            "note": "",
        },
        "apis": [{"method": "POST", "path": "TODO /demo/xxx/list",
                  "purpose": "TODO", "auth": "TODO 要不要权限点", "evidence": "TODO"}],
        "questions": [{"id": "Q-01", "title": "TODO 第一个待确认问题",
                       "why": "TODO 为什么拿不准，冲突在哪", "ask": "TODO 要对方定什么",
                       "status": "open"}],
        "dialogs": [{"type": "弹窗", "name": "TODO 本模块下的弹窗/二级页",
                     "entry": "TODO 点哪个按钮打开", "route": "", "covered": False}],
        "layout": TODO + "界面结构：列数、控件顺序、尺寸。AI 写代码缺这段会自己编布局 -->\n",

        # ① 原型：团队只写 px- 组件 class，不写 style（契约会拒）
        "prototype": {
            "viewport": "1440x900",
            "note": TODO + "这一组帧要交代的事：哪些是示例数据、哪里被裁掉了 -->",
            "frames": [{
                "id": "P1",
                "name": module,
                "state": "默认态",
                "route": "TODO 这一态的真实路由",
                "from": "",
                "note": TODO + "看图时必须说明的事 -->",
                "html": '<div class="px">'
                        '<div class="px-top"><div class="px-logo">DEMO <i>ADMIN</i></div>'
                        '<div class="px-tmenu"><span class="on">' + module + '</span></div>'
                        '<div class="px-tright"><div class="px-av">运</div></div></div>'
                        '<div class="px-body"><div class="px-main">'
                        '<div class="px-h1">' + module + '</div>'
                        '<div class="px-card"><div class="px-card-bd">'
                        '<div class="px-empty">待画原型 —— 先跑 snapshot_page.py 实拍，再 proto_from_snapshot.py 生成；'
                        'px- 组件拼，不要写 style</div>'
                        '</div></div></div></div></div>',
            }],
        },

        # ④ 核查：三条示例，全部带【示例】标记，check_delivery 会拦住不让交付
        "facts": [
            {"id": "F-01", "title": "【示例·替换或删除】某处写法与代码不符",
             "area": "字段类型", "cls": "fix", "sev": "P0", "src": ["be", "api"],
             "old": "PRD 里原来的写法", "now": "接口 / 代码里实际是什么（写全，能直接抄进正文）",
             "note": "为什么信这个、和哪条冲突", "ask": "要不要按实际改？",
             "evidence": "接口路径 + 返回 / 文件:行号 / 用例标题", "rules": []},
            {"id": "F-02", "title": "【示例·替换或删除】某块内容 PRD 完全没写",
             "area": "其他设置", "cls": "add", "sev": "P1", "src": ["fe", "ui"],
             "old": "", "now": "页面 / 代码里有、但要补进 PRD 的那块内容",
             "note": "漏在哪、影响谁", "ask": "",
             "evidence": "chunk 文件名 / 实拍页签", "rules": []},
            {"id": "F-03", "title": "【示例·替换或删除】某条现有写法核过是对的",
             "area": "命名", "cls": "ok", "sev": "P2", "src": ["ima", "ui"],
             "old": "", "now": "核过一致的那条规则",
             "note": "用哪几个源对上的", "ask": "",
             "evidence": "用例标题 + 实拍", "rules": []},
        ],
    }


def skeleton_facts(key, module):
    return {
        "meta": {
            "title": "%s · 五源核查事实清单" % module,
            "h1": module,
            "key": key,
            "engine": S.ENGINE,
            "sources": [
                {"k": "ui", "name": "浏览器渲染", "status": "未核", "detail": "TODO"},
                {"k": "api", "name": "后端接口", "status": "未核", "detail": "TODO"},
                {"k": "fe", "name": "前端代码", "status": "未核", "detail": "TODO"},
                {"k": "be", "name": "后端代码", "status": "未核", "detail": "TODO"},
                {"k": "ima", "name": "用例库", "status": "未核", "detail": "TODO"},
                {"k": "biz", "name": "业务确认", "status": "未核", "detail": "TODO"},
            ],
        },
        "gate": {
            "asked_at": None,
            "approved_at": None,
            "answered": 0,
            "total": 0,
            "decision": "",
        },
        "facts": [],
    }


RUNBOOK = """# 怎么干活

> 兜底版（没找到 skill 里的 `references/team-runbook.md`）。引擎：`{engine}`

## 你只填两个文件

| 文件 | 填什么 | 怎么用 |
|:--|:--|:--|
| `facts/<key>.facts.json` | 五源核查发现的事实清单（唯一事实源） | `build_facts.py` → 拿给对方过闸门 1 |
| `modules/<key>.json` | ①原型帧 ②叙事 8 段 ③AI 读用的 entities/context ④事实清单镜像 | `build_module_prd.py` → 四视图单页 PRD |

`out/<key>.html` **自动生成，不许手改**。

## 单页 PRD 里有四块，缺一块都不算交付

| 块 | 数据在 | 谁看 |
|:--|:--|:--|
| ① 原型图 | `prototype.frames[]`，每帧一段 px- 组件 HTML | 所有人先看图 |
| ② 叙事 | `sections[]` + `rules[]` + `transitions` | 业务 / PM / 测试 |
| ③ AI 读 | `context` / `entities` / `layout` + 上面两块自动导出 | 研发 AI |
| ④ 核查 | `facts[]`，每条写原说法/实际/判断/要你定 | 对方裁定时逐条过 |

## 原型是抓出来的，不是画出来的

```bash
# ① 开一个带调试端口的浏览器，用你自己的账号登录一遍
{py} ../scripts/launch_chrome.py

# ② 实拍：真实页面 → snapshot/<key>.json（同时存截图）
{py} ../scripts/snapshot_page.py --base https://test1x.example.com \\
    --url /a/b --key <key> --page p1 --name 列表
#   弹窗加 --open "按钮文案"，页签加 --tab "页签名"，批量写 plan.json

# ③ 快照 → 原型帧，直接写进 modules/<key>.json
{py} ../scripts/proto_from_snapshot.py --snapshot snapshot/<key>.json \\
    --data modules/<key>.json --write
```

每步会打印抽到了什么。看到「什么都没抽到」就是没抓到，重来。

## 四条红线

1. **不改模板**。HTML 长什么样由引擎决定，你只填数据。
2. **不手改 out 里的 HTML**。重新构建会覆盖。
3. **拿不准写进 facts 的 ask 或 questions**，不许编。编的比留白的危害大得多。
4. **原型不许凭印象画**。走上面三步；手改 html 可以，但帧上的 `from` 必须留着，
   验收会拿它去查快照在不在——查不到判「凭印象画」。

原型也不许写 `style=`——只准用 `px-` 组件 class，否则每个人画出来都不一样，合并后排版会散。

## 交付前

```bash
{py} build_module_prd.py --data modules/<key>.json --facts facts/<key>.facts.json --out out/<key>.html --strict
{py} check_delivery.py --root . --module <key> --strict
```

全绿才算交付。交的时候带上 `snapshot/`（原型图的依据）。
""".format(engine=S.ENGINE, py=_PY())


def parse_module(spec):
    parts = [x.strip() for x in spec.split("|")]
    if len(parts) < 3:
        sys.exit("✗ --module 格式：\"系统|一级 / 二级 / 三级|key[|负责人]\"，实际 %r" % spec)
    while len(parts) < 4:
        parts.append("")
    return parts[0], parts[1], parts[2], parts[3]


def do_list(root):
    p = os.path.join(root, "run.json")
    if not os.path.exists(p):
        sys.exit("✗ %s 下没有 run.json，不是工作台目录" % root)
    run = json.load(open(p, encoding="utf-8"))
    print("项目：%s · 引擎 %s · 建 %s" % (run.get("project"), run.get("engine"), run.get("created")))
    print()
    print("%-22s %-10s %-16s %-8s %-8s %s" % ("key", "负责人", "模块", "数据", "产物", "闸门"))
    for m in run.get("modules", []):
        k = m["key"]
        mp = os.path.join(root, "modules", k + ".json")
        fp = os.path.join(root, "facts", k + ".facts.json")
        hp = os.path.join(root, "out", k + ".html")
        gate = "—"
        if os.path.exists(fp):
            g = json.load(open(fp, encoding="utf-8")).get("gate") or {}
            gate = "过" if g.get("approved_at") else "待过"
        d = "有" if os.path.exists(mp) else "缺"
        h = "有" if os.path.exists(hp) else "缺"
        print("%-22s %-10s %-16s %-8s %-8s %s" % (k, m.get("owner") or "-", m["module"], d, h, gate))




def main():
    ap = argparse.ArgumentParser(description="初始化模块 PRD 工作台")
    ap.add_argument("--root", required=True, help="工作台根目录")
    ap.add_argument("--project", default="", help="项目名")
    ap.add_argument("--module", action="append", default=[],
                    help='"系统|菜单路径|key[|负责人]"，可多次')
    ap.add_argument("--list", action="store_true", help="列出工作台现状")
    ap.add_argument("--force", action="store_true", help="覆盖已存在的模块文件")
    a = ap.parse_args()

    root = os.path.abspath(os.path.expanduser(a.root))
    if a.list:
        do_list(root)
        return

    if not a.module:
        sys.exit("✗ 至少给一个 --module")

    mods = [parse_module(x) for x in a.module]
    for _, _, key, _ in mods:
        if not key:
            sys.exit("✗ 模块 key 不能为空")
        if not all(c.isalnum() or c in "-_" for c in key):
            sys.exit("✗ 模块 key 只能用字母数字和 -_：%r" % key)

    for sub in ("modules", "facts", "out", "资源"):
        os.makedirs(os.path.join(root, sub), exist_ok=True)

    runp = os.path.join(root, "run.json")
    if os.path.exists(runp):
        run = json.load(open(runp, encoding="utf-8"))
        if run.get("engine") != S.ENGINE:
            print("⚠ 工作台是旧引擎建的（%s），当前 %s。新老数据不能合并，建议新建目录。"
                  % (run.get("engine"), S.ENGINE))
    else:
        run = {"project": a.project or os.path.basename(root), "engine": S.ENGINE,
               "created": now(), "modules": []}

    have = {m["key"] for m in run["modules"]}
    made = []
    for sysname, menu, key, owner in mods:
        module = menu.split("/")[-1].strip()
        note = ""
        if key in have and not a.force:
            note = "已存在，跳过（要覆盖加 --force）"
        else:
            mp = os.path.join(root, "modules", key + ".json")
            fp = os.path.join(root, "facts", key + ".facts.json")
            if not os.path.exists(mp) or a.force:
                json.dump(skeleton_module(sysname, menu, key, owner, run["project"]),
                          open(mp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
            if not os.path.exists(fp) or a.force:
                json.dump(skeleton_facts(key, module),
                          open(fp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
            made.append(key)
            note = "已建"
        if key not in have:
            run["modules"].append({"key": key, "system": sysname, "menu": menu,
                                   "module": module, "owner": owner})
        print("  %-22s %-8s %s" % (key, note or "存在", menu))

    run["engine"] = S.ENGINE
    run["updated"] = now()
    json.dump(run, open(runp, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    # 操作卡：优先复制 skill 里的团队手册，拿不到就写简版
    rb_src = os.path.join(SKILL, "references", "team-runbook.md")
    rb_dst = os.path.join(root, "怎么干活.md")
    if os.path.exists(rb_src) and not os.path.exists(rb_dst):
        shutil.copyfile(rb_src, rb_dst)
        with open(rb_dst, "a", encoding="utf-8") as f:
            f.write("\n\n---\n\n> 本文件由 `init_run.py` 从 skill 复制，引擎 `%s`，%s\n"
                    % (S.ENGINE, now()))
    elif not os.path.exists(rb_dst):
        open(rb_dst, "w", encoding="utf-8").write(RUNBOOK)

    print()
    print("工作台：%s" % root)
    print("模块数：%d（本次新建 %d）" % (len(run["modules"]), len(made)))
    print()
    print("下一步：")
    print("  1. 读 怎么干活.md")
    print("  2. 填 facts/<key>.facts.json → %s build_facts.py --data ... --out 事实清单.html" % _PY())
    print("  3. 填 modules/<key>.json   → %s build_module_prd.py --data ... --out out/<key>.html --strict" % _PY())
    print("  4. 交付前 → %s check_delivery.py --root %s --module <key> --strict"
          % (_PY(), root))


if __name__ == "__main__":
    import _compat as _c   # 控制台编码兜底（Windows 默认 cp936 编不出 ✓ ✗）
    _c.init()
    main()
