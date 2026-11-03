#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""装完先跑这个：环境对不对，一次说清。

    python3 scripts/doctor.py

不检查业务账号密码——那些每次现要。只查「跑不跑得起来」。
"""

import json
import os
import platform
import shutil
import subprocess
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)

try:
    import _compat as _C
    OK, WARN, BAD = _C.symbol("ok"), "!", _C.symbol("fail")
except Exception:  # noqa: BLE001
    OK, WARN, BAD = "✓", "!", "✗"
rows = []


def _c_py():
    """提示语里的 python 命令名。"""
    try:
        import _compat
        return _compat.python_cmd()
    except Exception:  # noqa: BLE001
        return "python"


def add(level, name, detail):
    rows.append((level, name, detail))


def check_files():
    need = [
        ("SKILL.md", os.path.join(SKILL, "SKILL.md")),
        ("模板 assets/module_prd.html", os.path.join(SKILL, "assets", "module_prd.html")),
        ("样例 assets/example_module.json", os.path.join(SKILL, "assets", "example_module.json")),
        ("契约 assets/module.schema.json", os.path.join(SKILL, "assets", "module.schema.json")),
        ("组件手册 references/prototype-kit.md",
         os.path.join(SKILL, "references", "prototype-kit.md")),
        ("操作卡 references/team-runbook.md",
         os.path.join(SKILL, "references", "team-runbook.md")),
        ("换源指南 references/sources-adapters.md",
         os.path.join(SKILL, "references", "sources-adapters.md")),
        ("两种交付 references/deliver-modes.md",
         os.path.join(SKILL, "references", "deliver-modes.md")),
        ("采集交互 references/interaction.md",
         os.path.join(SKILL, "references", "interaction.md")),
        ("迭代开工 scripts/plan_iteration.py", os.path.join(HERE, "plan_iteration.py")),
        ("闸门登记 scripts/gate.py", os.path.join(HERE, "gate.py")),
        ("双层门禁 references/gates.md", os.path.join(SKILL, "references", "gates.md")),
        ("构建 scripts/build_module_prd.py",
         os.path.join(HERE, "build_module_prd.py")),
        ("验收 scripts/check_delivery.py", os.path.join(HERE, "check_delivery.py")),
        ("建台 scripts/init_run.py", os.path.join(HERE, "init_run.py")),
        ("合并 scripts/merge_modules.py", os.path.join(HERE, "merge_modules.py")),
        ("实拍 scripts/snapshot_page.py", os.path.join(HERE, "snapshot_page.py")),
        ("原型生成 scripts/proto_from_snapshot.py",
         os.path.join(HERE, "proto_from_snapshot.py")),
        ("快照格式 assets/snapshot.schema.json",
         os.path.join(SKILL, "assets", "snapshot.schema.json")),
        ("平台适配 scripts/_compat.py", os.path.join(HERE, "_compat.py")),
        ("实拍/生成依赖 scripts/cdp_boot.py", os.path.join(HERE, "cdp_boot.py")),
        ("内嵌 CDP scripts/vendor_cdp.py", os.path.join(HERE, "vendor_cdp.py")),
    ]
    miss = [n for n, p in need if not os.path.exists(p)]
    add(BAD if miss else OK, "文件完整性",
        "缺 %d 个：%s" % (len(miss), "、".join(miss)) if miss else "%d 项齐全" % len(need))


def check_python():
    v = sys.version_info
    ok = (v.major, v.minor) >= (3, 8)
    add(OK if ok else BAD, "Python", "%d.%d.%d（需要 ≥ 3.8）" % (v.major, v.minor, v.micro))


def check_cdp():
    sys.path.insert(0, HERE)
    try:
        import cdp_boot
        m = cdp_boot.load()
        where = "包内 vendor_cdp" if m.__name__ == "vendor_cdp" else "外部 skill"
        add(OK, "CDP 客户端", where)
    except Exception as e:
        add(BAD, "CDP 客户端", str(e).split("\n")[0])
        return
    if cdp_boot.port_open(9222):
        try:
            v = json.loads(urllib.request.urlopen(
                "http://127.0.0.1:9222/json/version", timeout=2).read())
            add(OK, "Chrome 调试端口", "9222 已就绪 · %s" % v.get("Browser", ""))
        except Exception:
            add(WARN, "Chrome 调试端口", "9222 有响应但读不到版本")
    else:
        add(WARN, "Chrome 调试端口",
            "9222 没开。要实拍时先跑：%s \"%s\" --headed"
            % (_c_py(), os.path.join(HERE, "launch_chrome.py")))


def check_chrome():
    sys.path.insert(0, HERE)
    try:
        import launch_chrome
        p = None
        for c in launch_chrome.CANDIDATES.get(platform.system(), []):
            if os.path.exists(c):
                p = c
                break
        if not p:
            for n in ("google-chrome", "chromium", "chrome", "msedge"):
                p = shutil.which(n)
                if p:
                    break
        add(OK if p else WARN, "Chrome 可执行文件",
            p if p else "没找到。截图会不可用；用 --path 指定，或让 AI 用浏览器控制技能")
    except Exception as e:
        add(WARN, "Chrome 可执行文件", str(e)[:80])


def check_cnb():
    p = shutil.which("cnb") or os.path.expanduser(
        "~/.workbuddy/binaries/node/cli-connector-packages/bin/cnb")
    if os.path.exists(p):
        try:
            r = subprocess.run([p, "--version"], capture_output=True, text=True, timeout=12)
            add(OK, "代码仓库命令行", (r.stdout or r.stderr).strip().split("\n")[0][:60] or p)
        except Exception as e:
            add(WARN, "代码仓库命令行", "存在但跑不起来：%s" % e)
    else:
        add(WARN, "代码仓库命令行",
            "没找到。读后端代码会不可用——先连代码仓库连接器，或用 harvest.py --local 指本地仓库")


def check_tpl():
    """模板能不能渲染：用样例数据跑一次构建，产物丢临时目录。"""
    import tempfile
    ex = os.path.join(SKILL, "assets", "example_module.json")
    if not os.path.exists(ex):
        add(WARN, "模板可渲染", "样例数据缺失，跳过")
        return
    out = os.path.join(tempfile.gettempdir(), "prd_doctor_check.html")
    r = subprocess.run([sys.executable, os.path.join(HERE, "build_module_prd.py"),
                        "--data", ex, "--out", out],
                       capture_output=True, text=True, timeout=120)
    if r.returncode == 0 and os.path.exists(out):
        kb = os.path.getsize(out) / 1024
        add(OK, "模板可渲染", "样例构建成功 %.0f KB" % kb)
        os.remove(out)
    else:
        tail = (r.stderr or r.stdout).strip().split("\n")[-1][:120]
        add(BAD, "模板可渲染", tail)


def check_platform():
    """这台机器有没有会让脚本跑不起来的平台性差异。"""
    try:
        import _compat as C
    except Exception:  # noqa: BLE001
        add(WARN, "平台适配层", "缺 scripts/_compat.py，Windows 上可能乱码")
        return

    osname = platform.system() or "?"
    bits = platform.architecture()[0]
    add(OK, "系统", "%s %s · Python %d 位" % (osname, platform.release()[:28], 64 if bits == "64bit" else 32))
    if bits != "64bit":
        add(WARN, "Python 位数", "32 位 Python 处理大文件容易内存不足，建议换 64 位")

    # 控制台编码：Windows 默认 cp936，✓ ✗ ⚠ 都编不出来
    enc = (getattr(sys.stdout, "encoding", "") or "?").lower()
    if C.IS_WIN and "utf" not in enc:
        add(WARN, "控制台编码", "当前 %s。建议先执行 chcp 65001，"
                                "否则 ✓ ✗ 这类符号会显示成问号（不影响功能）" % enc)
    else:
        add(OK, "控制台编码", enc)

    # 临时目录：脚本要在这里放 token、Chrome profile
    td = C.tmpdir()
    try:
        probe = os.path.join(td, "_prd_doctor_probe.tmp")
        open(probe, "w").write("1")
        os.remove(probe)
        add(OK, "临时目录可写", C.path_hint(td))
    except Exception as exc:  # noqa: BLE001
        add(BAD, "临时目录可写", "%s 写不了：%s" % (C.path_hint(td), exc))

    # 路径里带中文或空格：Chrome 的 file:// 与个别工具会踩
    home = os.path.expanduser("~")
    if any(ch.isspace() for ch in home):
        add(WARN, "用户目录含空格", "%s —— 个别工具对空格支持不好，"
                                   "遇到怪问题可换一个不带空格的工作目录" % C.path_hint(home))
    elif any(ord(ch) > 127 for ch in home):
        add(OK, "用户目录含中文", "能用（脚本内部已做 URL 编码），只是别贴路径给命令行工具")
    else:
        add(OK, "用户目录", C.path_hint(home))


def main():
    print("system-to-prd · 环境自检")
    print("=" * 60)
    check_python()
    check_platform()
    check_files()
    check_cdp()
    check_chrome()
    check_cnb()
    check_tpl()
    print()
    for lv, n, d in rows:
        print(" %s %-16s %s" % (lv, n, d))
    print()
    bad = sum(1 for r in rows if r[0] == BAD)
    warn = sum(1 for r in rows if r[0] == WARN)
    if bad:
        print("结论：%d 项不通过，先修再开工。" % bad)
        return 1
    if warn:
        print("结论：可以开工，但有 %d 项提醒——缺的只是截图 / 读码这类增强能力，"
              "PRD 正文照样能写。" % warn)
        return 0
    print("结论：全绿。")
    return 0


if __name__ == "__main__":
    import _compat as _c   # 控制台编码兜底（Windows 默认 cp936 编不出 ✓ ✗）
    _c.init()
    sys.exit(main())
