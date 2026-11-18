#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""措辞体检：把「写文档时反复犯的那几类错」扫出来。

    python3 scripts/scan_wording.py --path modules/demo-refund.json
    python3 scripts/scan_wording.py --path . --quiet
    python3 scripts/scan_wording.py --path . --json

为什么要有这个脚本：
这些错不是「不会写」，是「写着写着就滑回去了」。写在文档里的规范，靠每次开工前想起来——
想不起来就犯。所以把它做成一条能跑的命令，交付前跑一次，红了就改。

检查项（每条都对应一次真实返工）：

  W1 角色词    把系统名当角色名用。「管理后台」是系统，「运营」不是使用者。
  W2 稿次写法  用 V3.0 / V10.1 表示「第 N 稿」。
  W3 量词入标签 「0 位打款成功学员」被拆成 0 + 「位，打款成功学员」。
  W4 占位残留  TODO / __TODO__ / 【示例
  W5 双 V 重复 VV5.0（批量替换把 V 加两次）
  W6 旧口径残留 改了说法，但别处还留着旧说法（--term 旧=新 指定）
  W7 禁用词    「友好提示 / 视情况而定 / 类似 / 尽可能」这类，出现即说明没想清楚

  R1 段落过长  一段超 110 字（读者一眼扫不到结论）
  R2 表格过宽  一张表超 4 列（每格只能写半句，反而最啰嗦）
  R3 全散文   模块正文超 1500 字却一张表都没有（该进表的东西写成了段落）
  R4 长句      单句超 80 字（硬约束 18 的上限是 50，这里只抓明显失控的）
  R5 论证标题  小标题里带「为什么」（那是设计说明，不是规格）

  T1 接口地址  正文里出现 POST /xxx、/demobackstage/…——读者是业务方，不是研发
  T2 字段名    驼峰 / 下划线字段名（paymentMethod、local_clearing_system）
  T3 常量枚举名 Constant.DEMO_FLAG、DEMO_LOCK_FORMAT
  T4 实现词    落库 / 幂等 / 序列化 / schema / 轮询 / 回调 …

T 类只扫叙事正文与原型帧，且豁免 <table class="tech-map">（附录 B 就是放这些的地方）。
页面路径不受 T1 影响：能在地址栏敲出来的是页面，要靠程序调的是接口，只有后者算泄漏。

W6 的由来：业务方纠偏一次口径（比如「结算申请单是运营发起」），我只改了正文，
context、边界表、原型文案里还留着旧说法，被指出第二次。改口径必须全文扫，所以做成命令：

    python3 scripts/scan_wording.py --path modules/demo-pay.json \
        --term "运营发起=教务发起" --term "运营审核=审批人审批"

退出码：有命中 → 1；加 --warn 一律返回 0（只提示不拦）。
"""

import argparse
import json
import os
import re
import sys

# 系统名 / 产品名里合法包含「运营」的词，扫的时候先剔除，避免误报
SYSTEM_WORDS = ["管理后台", "管理后台PRD", "管理后台 PRD", "管理后台V5.0", "管理后台 V5.0"]

ROLE_RE = re.compile(r"运营")
VER_RE = re.compile(r"V(\d{1,2})\.(\d{1,2})")
DUP_RE = re.compile(r"VV\d[\d.]*")

# 量词/标点跑到标签开头的典型形态：>位，xxx< / >个，xxx< / >名，xxx<
UNIT_RE = re.compile(r">\s*(位|个|名|条|笔|张)\s*[，,、]\s*[^<]{1,12}<")

TODO_RE = re.compile(r"__TODO__|TODO\s|【示例")

# W7 禁用词：出自《后台 PRD 文案写法拆解》第五节。
# 不收「等」——它是合法虚词，靠机器判断「枚举后的等」会大量误报；
# 改成只收「等」贴着顿号/逗号并列的那种形态。
BANNED = [
    ("友好提示", "提示文案没定 —— 直接给文案原文"),
    ("合理展示", "展示规则没定 —— 写清显示什么、怎么截断"),
    ("视情况而定", "分支没列完 —— 列出全部分支及优先级"),
    ("根据实际情况", "分支没列完 —— 列出全部分支及优先级"),
    ("结合实际", "分支没列完 —— 列出全部分支及优先级"),
    ("类似", "没给路径 —— 写「参照【模块】-【页面】-【组件】」，再写差异点"),
    ("同上", "没给路径 —— 写出具体位置"),
    ("尽可能", "无法验收 —— 给具体阈值，或删掉"),
    ("适当", "无法验收 —— 给具体阈值，或删掉"),
    ("优化体验", "无法验收 —— 写清改什么行为"),
    ("支持多种格式", "格式没定 —— 列出扩展名"),
    ("做好兼容", "把技术决策推给开发 —— 写场景和数据量，或标「需技术评估」"),
    ("性能要好", "把技术决策推给开发 —— 写场景和数据量，或标「需技术评估」"),
]
BANNED_RE = [(re.compile(re.escape(w)), w, h) for w, h in BANNED]

# ── T 类：技术标识只许进附录 B（硬约束 15） ────────────────────────────
#
# 为什么单独做一套检查：这类词不是作者不知道要改，是「写着写着就顺手把后端字段名抄上去了」。
# 业务方看不懂 → 不再逐条读 → 评审变成点头 → 做出来才发现理解错了。
#
# 只扫叙事正文和原型帧。apis / entities 这些结构化字段里本来就该有接口和字段名，扫了全是误报。
TECH_IN_NARRATIVE = (".sections[", ".prototype.frames[")
# 附录 B 是唯一豁免区：按 table 边界剥（table 不嵌套，比按 div 配对稳）
TECH_MAP_RE = re.compile(r'<table[^>]*class="[^"]*tech-map[^"]*"[\s\S]*?</table>', re.I)
TAG_RE = re.compile(r"<[^>]+>")
# 路径整体摘掉再查字段名，否则 /studentManage/addPerson 会被当成驼峰字段
PATH_RE = re.compile(r"/[A-Za-z][\w{}$.\-]*(?:/[\w{}$.\-]+)*")
API_CALL_RE = re.compile(r"\b(?:GET|POST|PUT|DELETE|PATCH)\s+/[\w/{}\-.$]+")
GATEWAY_RE = re.compile(r"/demobackstage/[\w/]+")
SNAKE_RE = re.compile(r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b")
CAMEL_RE = re.compile(r"\b[a-z][a-z0-9]*[A-Z][A-Za-z0-9]*\b")
CONST_RE = re.compile(r"\bConstant\.[A-Za-z_]+|\b[A-Z][A-Z0-9]{2,}(?:_[A-Z0-9]+)+\b")
IMPL_WORDS = ["落库", "入库", "幂等", "序列化", "反序列化", "schema", "Schema",
              "轮询", "回调", "补丁", "DTO", "VO", "DAO", "SQL", "JWT",
              "事务", "并发", "缓存", "灰度", "接口返回", "表结构", "字段值"]

TECH = [
    ("T1", API_CALL_RE, "接口地址不进正文 —— 写成「谁点了什么、系统做了什么」，地址放附录 B"),
    ("T1", GATEWAY_RE, "接口地址不进正文 —— 业务方不需要知道调哪个网关，放附录 B"),
    ("T2", CAMEL_RE, "字段名不进正文 —— 写界面上那一列/那一项的字"),
    ("T2", SNAKE_RE, "字段名不进正文 —— 写界面上那一列/那一项的字"),
    ("T3", CONST_RE, "常量/枚举名不进正文 —— 换成业务说法（项目名、状态名）"),
]

PRODUCT_VER = "V5.0"   # 当前产品版本；只有它允许写成 Vn.m

# 旧口径 → 新口径。--term 指定，用来查「改了一处、别处还留着」。
# 不剔引号：引号里的旧说法也要人看一眼（可能是忘了回去改的反例引用）。
TERMS = []


QUOTED_RE = re.compile(r"「[^」]{0,80}」|“[^”]{0,80}”|\"[^\"\n]{0,80}\"")


def strip_quoted(s):
    """引号里的是「提到某个词」，不是「用某个词」——例如「不得写成『运营发起结算申请』」。"""
    return QUOTED_RE.sub("", s)


def strip_system_words(s):
    for w in SYSTEM_WORDS:
        s = s.replace(w, "")
    return s


def scan_text(text, path, out):
    """扫一段文本，命中就往 out 里追加 (code, path, snippet, hint)。"""
    t = strip_quoted(strip_system_words(text))

    for m in ROLE_RE.finditer(t):
        i = m.start()
        out.append(("W1", path, t[max(0, i - 30):i + 30].replace("\n", " ").strip(),
                    "「运营」不是角色。写清是谁：教务 / 交付团队 / 财务 / 出纳 / 系统"))

    for m in VER_RE.finditer(text):
        if m.group(0) == PRODUCT_VER:
            continue
        i = m.start()
        out.append(("W2", path, text[max(0, i - 26):i + 26].replace("\n", " ").strip(),
                    "稿次写「第 %s 稿」，不要写成 %s" % (m.group(1), m.group(0))))

    for m in DUP_RE.finditer(text):
        out.append(("W5", path, m.group(0), "版本号被加了两次（批量替换的典型后果）"))

    for m in UNIT_RE.finditer(text):
        out.append(("W3", path, m.group(0), "量词和标点不要进标签：标签只留「打款成功学员」，量词归数字那侧或删掉"))

    for m in TODO_RE.finditer(text):
        i = m.start()
        out.append(("W4", path, text[max(0, i - 20):i + 20].replace("\n", " ").strip(), "占位没填"))

    # W7 禁用词：出现即说明这句话还没想清楚（规范第五节）
    for rx, w, hint in BANNED_RE:
        for m in rx.finditer(text):
            i = m.start()
            out.append(("W7", path, text[max(0, i - 24):i + 24].replace("\n", " ").strip(), hint))

    # T1–T4 技术标识：只有正文与原型帧要查，附录 B（table.tech-map）豁免。
    # 原型帧的 route 是页面地址，不是接口——页面路径本来就允许留在文档里（硬约束 15 只禁接口地址），
    # 而且 v6 起 route 不再显示在页面上，只作页签提示。所以整条跳过。
    if path.endswith(".route"):
        pass
    elif any(k in path for k in TECH_IN_NARRATIVE):
        body = TECH_MAP_RE.sub("", text)
        visible = TAG_RE.sub("", body)          # 只看看得见的字，class 名不算泄漏
        nopath = PATH_RE.sub(" ", visible)
        for code, rx, hint in TECH:
            src = visible if code == "T1" else nopath
            for m in rx.finditer(src):
                i = m.start()
                out.append((code, path, src[max(0, i - 26):i + 26].replace("\n", " ").strip(), hint))
        for w in IMPL_WORDS:
            for m in re.finditer(re.escape(w), nopath):
                i = m.start()
                out.append(("T4", path, nopath[max(0, i - 26):i + 26].replace("\n", " ").strip(),
                            "实现词不进正文 —— 换成「它保证了什么」：存下来 / 重复点也只生效一次 / 对方回话"))

    # W6 旧口径残留：改了口径，别处还留着旧说法。
    # 不剔引号 —— 引号里的旧说法也要人看一眼（多半是忘了回去改的反例引用）。
    for old, new in TERMS:
        for m in re.finditer(re.escape(old), text):
            i = m.start()
            out.append(("W6", path, text[max(0, i - 26):i + 26].replace("\n", " ").strip(),
                        "旧口径「%s」还在，改成「%s」" % (old, new)))


def walk_json(obj, path, out):
    if isinstance(obj, dict):
        for k, v in obj.items():
            walk_json(v, "%s.%s" % (path, k), out)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            walk_json(v, "%s[%d]" % (path, i), out)
    elif isinstance(obj, str):
        scan_text(obj, path, out)


def scan_file(p, out):
    ext = os.path.splitext(p)[1].lower()
    if ext == ".json":
        try:
            d = json.load(open(p, encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            out.append(("W0", p, str(e)[:60], "读不了这个 json"))
            return
        walk_json(d, os.path.basename(p), out)
        # module.json 才做 R 类：需要整模块视角（表格数、段落长度分布）
        if isinstance(d, dict) and d.get("meta", {}).get("key") and d.get("sections"):
            scan_module_readability(d, out, d["meta"]["key"])
    else:  # md / html / txt：整篇当文本扫
        try:
            s = open(p, encoding="utf-8", errors="ignore").read()
        except Exception:  # noqa: BLE001
            return
        scan_text(s, os.path.basename(p), out)


def iter_files(root, scan_log=False):
    if os.path.isfile(root):
        yield root
        return
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames
                       if d not in ("__pycache__", "归档", "snapshot", "node_modules", ".git")]
        for fn in filenames:
            # 台账/日志是历史记录，不是交付物：默认不扫（--all 可以扫）
            if not scan_log and fn.startswith(("CHANGELOG", "FILELOG")):
                continue
            if fn.lower().endswith((".json", ".md", ".html")):
                yield os.path.join(dirpath, fn)


# ── R 类：可读性（硬约束 20）────────────────────────────────────────
#
# 为什么放在措辞体检里而不是另起一个脚本：这些错和 W/T 类同源——写着写着就滑回去。
# 分成两个命令，团队只会跑一个。
#
# 三条判据来自 2026-11-18 对第 23 稿的实测：正文 59,306 → 35,439 字（-40%），
# 五个模块的表格从大量 5–6 列收到 88% 落在 2–3 列。降幅来源不是删词，
# 是「一句一逻辑 + 一张窄表」替代「一段散文 + 一张宽表」。
P_RE = re.compile(r"<p[^>]*>([\s\S]*?)</p>")
TABLE_RE = re.compile(r"<table[\s\S]*?</table>")
TH_ROW_RE = re.compile(r"<tr>\s*((?:<th[^>]*>[\s\S]*?</th>\s*)+)</tr>")
CJK_RE = re.compile(r"[\u4e00-\u9fff]")
# 「不是 A 而是 B」：立假靶子。真有人会搞错 A 才留，否则直接说 B
NEG_PAIR_RE = re.compile(r"不(?:是|在于)[^。！？；]{0,24}(?:而是|而在于)")
WHY_HEAD_RE = re.compile(r"<h[34][^>]*>[^<]{0,30}为什么")

R_LIMIT = {"para": 110, "cols": 4, "sentence": 80, "module_no_table": 1500}


def cjk_len(s):
    return len(CJK_RE.findall(s or ""))


def scan_module_readability(mod, out, tag):
    """模块级：段落长度、表格列数、全散文、长句、论证标题。tag 用来标是哪个模块。"""
    secs = mod.get("sections") or []
    total = 0
    tables = 0
    for sec in secs:
        h = sec.get("html") or ""
        n = sec.get("n")
        total += cjk_len(TAG_RE.sub("", h))

        for p in P_RE.findall(h):
            t = TAG_RE.sub("", p).strip()
            if cjk_len(t) > R_LIMIT["para"]:
                out.append(("R1", "%s 段%s" % (tag, n), t[:44],
                            "段落 %d 字，超上限 %d。拆成一短句 + 一张表，或拆成两条"
                            % (cjk_len(t), R_LIMIT["para"])))

        for tb in TABLE_RE.findall(h):
            tables += 1
            if "tech-map" in tb[:120]:      # 附录 B 是字段对照表，列多是对的
                continue
            hd = TH_ROW_RE.search(tb)
            if not hd:
                continue
            cols = len(re.findall(r"<th", hd.group(1)))
            if cols > R_LIMIT["cols"]:
                head = TAG_RE.sub(" ", tb[:160]).strip()[:40]
                out.append(("R2", "%s 段%s" % (tag, n), "%d 列 | %s" % (cols, head),
                            "表格 %d 列。先砍这四类：控件列、论证列（为什么）、示例列、可合并列"
                            % cols))

        for m in NEG_PAIR_RE.finditer(TAG_RE.sub("", h)):
            i = m.start()
            seg = TAG_RE.sub("", h)
            out.append(("R5", "%s 段%s" % (tag, n), seg[max(0, i - 18):m.end() + 18].strip(),
                        "「不是 A 而是 B」立的是假靶子 —— 直接说 B"))

        if WHY_HEAD_RE.search(h):
            out.append(("R5", "%s 段%s" % (tag, n), WHY_HEAD_RE.search(h).group(0)[:38],
                        "小标题里的「为什么」是设计说明，不是规格 —— 删掉或并进结论"))

    if total > R_LIMIT["module_no_table"] and tables == 0:
        out.append(("R3", tag, "%d 字 0 张表" % total,
                    "全是散文。改成「一句话 + 一张表」，表格是规格的主力载体"))

    # R4 长句：只扫段落，不扫表格（表内用分号并列是正常的）
    for sec in secs:
        for p in P_RE.findall(sec.get("html") or ""):
            t = TAG_RE.sub("", p)
            for sent in re.split(r"[。！？；]", t):
                if cjk_len(sent) > R_LIMIT["sentence"]:
                    out.append(("R4", "%s 段%s" % (tag, sec.get("n")), sent.strip()[:44],
                                "单句 %d 字。上限 50（硬约束 18），超 80 基本是一句话塞了三件事"
                                % cjk_len(sent)))


CODE_NAME = {"W0": "读不了", "W1": "角色词", "W2": "稿次写法",
             "W3": "量词入标签", "W4": "占位残留", "W5": "双 V", "W6": "旧口径残留", "W7": "禁用词",
             "T1": "接口地址", "T2": "字段名", "T3": "常量枚举名", "T4": "实现词",
             "R1": "段落过长", "R2": "表格过宽", "R3": "全散文", "R4": "长句", "R5": "论证标题"}


def main():
    ap = argparse.ArgumentParser(description="措辞体检")
    ap.add_argument("--path", required=True, help="json 文件，或目录（递归扫 .json/.md/.html）")
    ap.add_argument("--json", dest="as_json", action="store_true", help="输出 JSON，便于其它脚本消费")
    ap.add_argument("--warn", action="store_true", help="只提示，不返回非 0")
    ap.add_argument("--max", type=int, default=60, help="每个检查项最多打印多少条（默认 60）")
    ap.add_argument("--all", dest="scan_all", action="store_true", help="连台账（CHANGELOG/FILELOG）一起扫")
    ap.add_argument("--term", action="append", default=[], metavar="旧=新",
                    help="查旧口径残留，可多次给：--term \"运营发起=教务发起\"")
    a = ap.parse_args()

    for t in a.term:
        if "=" not in t:
            sys.exit("✗ --term 要写成 旧=新，实际：%r" % t)
        old, _, new = t.partition("=")
        if old.strip():
            TERMS.append((old.strip(), new.strip()))

    root = os.path.abspath(os.path.expanduser(a.path))
    if not os.path.exists(root):
        sys.exit("✗ 路径不存在：%s" % root)

    out = []
    for p in iter_files(root, a.scan_all):
        scan_file(p, out)

    if a.as_json:
        print(json.dumps([{"code": c, "file": f, "context": s, "hint": h} for c, f, s, h in out],
                         ensure_ascii=False, indent=1))
    else:
        if not out:
            print("✓ 措辞体检通过：没有角色词、V 稿次、量词入标签、占位残留、技术标识、超长段落/宽表"
                  + ("、旧口径残留" if TERMS else ""))
        else:
            by = {}
            for c, f, s, h in out:
                by.setdefault(c, []).append((f, s, h))
            print("措辞体检发现 %d 处：" % len(out))
            for c in sorted(by):
                items = by[c]
                print("\n[%s %s] %d 处" % (c, CODE_NAME.get(c, ""), len(items)))
                for f, s, h in items[:a.max]:
                    print("  · %s  …%s…" % (f or "?", s))
                    print("     → %s" % h)
                if len(items) > a.max:
                    print("  … 还有 %d 处（--max 调大）" % (len(items) - a.max))

    if out and not a.warn:
        sys.exit(1)


if __name__ == "__main__":
    main()
