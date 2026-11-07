#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""交付前验收。全绿才算交了。

    python3 check_delivery.py --root ./prd-run --module ops-person-field --strict
    python3 check_delivery.py --root ./prd-run --all        # 合并前查全员

查四类东西，缺一项都不算交付：

  流程留痕   闸门 1 过了没（facts 里有裁定时间）、闸门 2 过了没（待确认全被回答）
  数据合规   契约校验、无 TODO 残留、无示例占位、引擎版本一致
  产物一致   html 存在、比 json 新、无外链、页内数据与 json 逐字节一致
  安全       无明文凭据
"""

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import schema as S  # noqa: E402

OK, WARN, FAIL = "ok", "warn", "fail"
try:
    import _compat as _C
    MARK = {OK: _C.symbol("ok"), WARN: "!", FAIL: _C.symbol("fail")}
except Exception:  # noqa: BLE001
    MARK = {OK: "✓", WARN: "!", FAIL: "✗"}


def rel_ok(v):
    return v and not str(v).startswith("TODO") and len(str(v).strip()) >= 2


def load_json(p):
    try:
        return json.load(open(p, encoding="utf-8")), None
    except FileNotFoundError:
        return None, "文件不存在"
    except json.JSONDecodeError as e:
        return None, "JSON 坏：%s" % e


def extract_prd_data(html):
    """从产物 HTML 里取回页内数据——用来证明 html 确实是这份 json 渲染的。"""
    m = re.search(r"window\.PRD_DATA = (\{.*?\});\s*\n</script>", html, re.S)
    if not m:
        return None
    raw = m.group(1).replace("<\\/", "</")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def canon(d):
    return hashlib.md5(json.dumps(d, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def _dchg_blocks(html):
    """按 <div> 配对切出每个改动块，返回 [(C编号, 块html)]。

    不能按字符串出现次数统计：表头里也写着 data-chg，会被重复计数
    （这一轮统计就因此出过一次错）。必须真配对。
    """
    out = []
    for m in re.finditer(r'<div[^>]*class="[^"]*\bdchg\b[^"]*"[^>]*>', html):
        cm = re.search(r'data-chg="(C\d+)"', m.group(0))
        if not cm:
            continue
        i, depth, j = m.start(), 0, m.start()
        while j < len(html):
            no, nc = html.find("<div", j), html.find("</div>", j)
            if nc < 0:
                break
            if 0 <= no < nc:
                depth += 1
                j = no + 4
            else:
                depth -= 1
                j = nc + 6
                if depth == 0:
                    out.append((cm.group(1), html[i:j]))
                    break
    return out


_NUM_HEAD = re.compile(r"(?:^|<br\s*/?>|</p>|</li>)\s*(?:\d{1,2}[.、)）]|[\u2460-\u2473\u3251-\u325F])")


def _plain(h):
    """转纯文本。块级标签当句末处理——直接抹成空格会把两段连成一句，
    「单句超 50 字」就会虚高一大截（实测差 3 倍）。"""
    h = re.sub(r"</?(?:p|div|li|br|tr|h[1-6])[^>]*>", "。", h)
    h = re.sub(r"<[^>]+>", "", h)
    return re.sub(r"\s+", " ", h).strip()


def _chg_struct(code, blk):
    """结构类问题：改后能不能逐条核对。返回问题描述或 None。"""
    # 先确认有没有「改后」信息。三种都算：显式标了改后、表格里有改后列、
    # 整块本来就只有改后描述（多数块是这种）。
    # 注意：绝不把「缺改前」当问题——这套文档刻意只写改后。
    _has_after = ("<b>改后" in blk or ">改后</" in blk or "<th>改后</th>" in blk
                  or ("改前" not in blk and "改后" not in blk))
    if not _has_after:
        return "%s 只有「改前」，没有说新版长什么样" % code

    if "<table" in blk:
        # 表格行本身就是条目，但表格**之前**那段常被写成散文，一样要能拆
        before = _plain(blk.split("<table")[0])
        if len(before) > 60 and len(re.findall(r"[，,；;]", before)) >= 3:
            return "%s 表格前的说明段能拆成多条，应分条" % code
        return None

    m = re.search(r"<b>改后[：:]\s*</b>(.*)", blk, re.S)
    after = m.group(1) if m else (blk.split("</span>", 1)[-1] if "</span>" in blk else blk)
    txt = _plain(after)

    # 有编号就直接算过，但要查是不是挤在一行
    heads = _NUM_HEAD.findall(after)
    if "<ol" in blk or len(heads) >= 2:
        if len(heads) >= 2 and "<br" not in after and "<li" not in blk:
            return "%s 的编号挤在一行，应逐条换行" % code
        return None

    if len(txt) <= 40 or not re.search(r"[，,；;]", txt):
        return None                      # 一句话说一个变化，本来就不用分条
    segs = [x for x in re.split(r"[。；;]", txt) if x.strip()]
    if len(segs) >= 2:
        return "%s 的改后能数出 %d 条，应分条换行" % (code, len(segs))
    return "%s 的改后能数出 2 条以上，应分条换行" % code


def _chg_style(blk):
    """文案类计数：返回 (超长句数, 顿号串数, 两分号段数)。只汇总不逐条。

    表格要整块剔掉：单元格里是「字段名 → 取值」，不是句子。
    算进去的话一张宽表能刷出几十个「超长句」，数字就没意义了。
    """
    b = re.sub(r"<table[\s\S]*?</table>", " ", blk)
    txt = _plain(b)
    long_sent = sum(1 for s in re.split(r"[。！？]", txt) if len(s.strip()) > 50)
    dun = sum(1 for s in re.split(r"[。！？]", txt) if s.count("、") >= 4)
    semi = sum(1 for p in re.split(r"<br\s*/?>", b)
               if _plain(p).count("；") + _plain(p).count(";") >= 2)
    return long_sent, dun, semi


def check_one(root, key, want_audit=True, hard=False):
    """返回 (items, fatal)。items = [(level, 组, 名称, 说明)]

    hard=True（--strict）时，「签字」「反查」这两组的缺项按 FAIL 算。
    为什么：日常改稿不该被签字拦住；但交付/合并前必须过——这就是第二层门禁。
    """
    items = []
    add = lambda lv, g, n, d="": items.append((lv, g, n, d))
    gate_lv = FAIL if hard else WARN

    # ---------------- 流程留痕 ----------------
    runp = os.path.join(root, "run.json")
    run, err = load_json(runp)
    if not run:
        add(FAIL, "流程", "run.json", err or "缺失")
    else:
        keys = [m["key"] for m in run.get("modules", [])]
        add(OK if key in keys else FAIL, "流程", "模块已登记",
            "" if key in keys else "run.json 里没有这个 key，先用 init_run.py 建")

    mp = os.path.join(root, "modules", key + ".json")
    fp = os.path.join(root, "facts", key + ".facts.json")
    hp = os.path.join(root, "out", key + ".html")
    # 文档级确认：整份 PRD 由一个人看一遍、封一次，覆盖闸门 1/2 与模块封板。
    # 模块级封板仍然认（更精确），但不是必填——封板的意义是「这一版我认了」，
    # 一个人签就够，不搞两个角色互相确认。
    _ds = (run or {}).get("signoff") or {}
    ds_ok = bool(_ds.get("by") and _ds.get("at"))
    ds_txt = ""
    if ds_ok:
        _cd, _cr = (run or {}).get("draft"), (run or {}).get("rev") or 0
        if _ds.get("draft") != _cd or (_ds.get("rev") or 0) != _cr:
            ds_ok = False
            ds_txt = ("签署记的是第 %s 稿%s，现为第 %s 稿%s —— 改过稿要重新确认"
                      % (_ds.get("draft"), "修订 %s" % _ds.get("rev") if _ds.get("rev") else "",
                         _cd, "修订 %s" % _cr if _cr else ""))
        else:
            # 稿次一致还不够：有人改完内容不发新稿，两边稿次都是空的或都没变，
            # 光比稿次永远相等。逐模块比内容指纹，改过就失效。
            _sd = _ds.get("digests") or {}
            _changed = [_k for _k, _v in _sd.items()
                        if S.content_digest(os.path.join(root, "modules", _k + ".json")) != _v]
            if _changed:
                ds_ok = False
                ds_txt = ("签署之后这些模块的内容被改过：%s —— 要重新确认"
                          % "、".join(sorted(_changed)))
            else:
                _dcn = "第 %s 稿" % _cd if _cd is not None else "未编稿次"
                ds_txt = ("文档级确认：%s @ %s（%s，覆盖 %s）"
                          % (_ds["by"], _ds["at"], _dcn, _ds.get("covers") or "全部模块"))

    facts, ferr = load_json(fp)
    gate_ok = False
    if not facts:
        add(FAIL, "流程", "事实台账", ferr or "缺失")
    else:
        g = facts.get("gate") or {}
        gf = g.get("facts") or {}
        # 兼容老写法：只有 approved_at、没有署名
        has_time = bool(gf.get("at") or g.get("approved_at"))
        gate_ok = has_time or ds_ok
        who = gf.get("by")
        if has_time:
            _why1 = ("%s%s，共 %s 条，答 %s 条" % (
                gf.get("at") or g.get("approved_at"),
                "" if who else "（未署名——gate.py facts --by <姓名>）",
                gf.get("total", g.get("total", "?")), gf.get("answered", g.get("answered", "?"))))
        elif ds_ok:
            _why1 = "%s，含本模块 %s 条事实" % (ds_txt, gf.get("total", g.get("total", "?")))
        else:
            _why1 = ("还没有人确认过事实清单。"
                     + ("%s。" % ds_txt if ds_txt else "")
                     + "整份文档看一遍即可：gate.py doc --by <姓名> --note \"…\"")
        add(OK if gate_ok else FAIL, "流程", "闸门 1（事实清单已裁定）", _why1)

        sc = g.get("scope") or {}
        if sc.get("at"):
            _why2 = "%s @ %s" % (sc.get("what"), sc.get("at"))
        elif ds_ok:
            _why2 = "%s，含本模块结构（8 段）" % ds_txt
        else:
            _why2 = ("没有骨架确认留痕。" + ("%s。" % ds_txt if ds_txt else "")
                     + "跑 gate.py scope --by <姓名> --what \"8 段/规则数/状态数/不写什么\"，或整份确认一次")
        add(OK if (sc.get("at") or ds_ok) else FAIL, "流程", "闸门 2（骨架已确认）", _why2)

    d, merr = load_json(mp)
    if not d:
        add(FAIL, "流程", "模块数据", merr or "缺失")
        return items, True

    qs = d.get("questions") or []
    pending = [q.get("id") for q in qs if q.get("status") != "answered"]
    # 未答的问题分两种处理：没整份确认过 → 红（这是真缺口）；整份确认过 → 黄。
    # 确认的含义是「我接受这版按默认口径推进」，不是「问题不存在」——所以降级而不隐藏。
    if not pending:
        add(OK, "流程", "待确认都答完了", "全部已答")
    elif ds_ok:
        add(WARN, "流程", "待确认都答完了",
            "还有 %d 条没答（%s）—— 已按文档级确认接受，按默认口径推进"
            % (len(pending), "、".join(pending)))
    else:
        add(FAIL, "流程", "待确认都答完了",
            "还有 %d 条没答：%s" % (len(pending), "、".join(pending)))

    # ---------------- 数据合规 ----------------
    errs = S.validate(d)
    if errs:
        head = "；".join("%s %s" % (e["path"], e["msg"]) for e in errs[:4])
        add(FAIL, "数据", "契约校验", "%d 处问题：%s%s"
            % (len(errs), head, " …" if len(errs) > 4 else ""))
    else:
        add(OK, "数据", "契约校验", "8 段 / 规则 / 状态机 / 六源 全部合规")

    blob = json.dumps(d, ensure_ascii=False)
    todos = blob.count("__TODO__") + blob.count("TODO ")
    add(OK if todos == 0 else FAIL, "数据", "无 TODO 残留",
        "" if todos == 0 else "还有 %d 处 TODO 没填" % todos)
    samples = len(re.findall(r"【示例", blob))
    add(OK if samples == 0 else FAIL, "数据", "无示例占位",
        "" if samples == 0 else "还有 %d 处示例条目没替换成真实内容" % samples)

    if d.get("engine") != S.ENGINE:
        add(FAIL, "数据", "引擎版本", "数据是 %r，当前 %s——老数据合并会出问题，用新版重跑"
            % (d.get("engine"), S.ENGINE))
    else:
        add(OK, "数据", "引擎版本", S.ENGINE)

    mt = d.get("meta") or {}
    for k in ("route", "env"):
        add(OK if rel_ok(mt.get(k)) else FAIL, "数据", "meta." + k,
            "" if rel_ok(mt.get(k)) else "还是占位值：%r" % mt.get(k))

    ok_src = [s["name"] for s in (d.get("sources") or []) if s.get("status") == "已核"]
    add(OK if len(ok_src) >= 4 else FAIL, "数据", "五源已核数",
        "%d/6（%s）" % (len(ok_src), "、".join(ok_src) or "无"))

    # ---------------- 四块内容齐不齐 ----------------
    pf = (d.get("prototype") or {}).get("frames") or []
    drawn = [f for f in pf if len((f.get("html") or "").strip()) >= 20]
    # 界面帧 vs 生成图：硬约束 11 那套「只写界面真有的字」只约束 ui 帧；
    # flow / diagram / explain 是硬约束 17 允许的图，要求它们像截图一样干净是错的。
    # kind 缺省按 ui 处理，老数据不用补字段。
    ui_frames = [f for f in drawn if (f.get("kind") or "ui") == "ui"]
    add(OK if drawn else FAIL, "内容", "① 原型帧",
        "%d 帧（%d 帧有内容）" % (len(pf), len(drawn)) if drawn
        else "一帧都没有——这份 html 只有文字没有图")
    if pf and not any(f.get("id") == "P1" for f in pf):
        add(WARN, "内容", "主页面帧", "没有 P1（主页面应固定为第一帧）")

    secs = d.get("sections") or []
    add(OK if len(secs) == 8 else FAIL, "内容", "② 叙事 8 段", "%d/8 段" % len(secs))

    fts = d.get("facts") or []
    p0 = [f for f in fts if f.get("sev") == "P0"]
    add(OK if fts else FAIL, "内容", "④ 五源事实清单",
        "%d 条，其中 P0 %d 条" % (len(fts), len(p0)) if fts
        else "没有事实清单——正文每条结论都追不到来源")
    # 已裁定的 P0（cls=fix 且 now 写清了改成什么）没有要问的，不该逼人写「无」来糊弄。
    # 判据与 schema.py 保持一致——两处规则不同步，改了一处另一处还会红。
    no_ask = [f.get("id") for f in p0
              if len((f.get("ask") or "").strip()) < 4
              and not (f.get("cls") == "fix" and len((f.get("now") or "").strip()) >= 10)]
    if p0:
        add(OK if not no_ask else FAIL, "内容", "P0 都写了要定什么",
            "" if not no_ask else "%d 条 P0 没写 ask：%s" % (len(no_ask), "、".join(no_ask[:6])))

    rules = d.get("rules") or []
    linked = [r for r in rules if r.get("facts")]
    add(OK if linked and len(linked) == len(rules) else FAIL, "内容", "规则挂依据",
        "%d/%d 条规则指回了 F-xx" % (len(linked), len(rules)) if linked
        else "一条规则都没挂 facts —— 正文看不出结论从哪来，点了也跳不回核查")

    # 原型不能留着骨架的占位帧
    ph = [f.get("id") for f in drawn if "待画原型" in (f.get("html") or "")]
    if ph:
        add(FAIL, "内容", "原型到位了吗",
            "%d 帧还是骨架占位（%s）—— 这帧没画，只是把提示文字留着"
            % (len(ph), "、".join(ph[:5])))

    # 原型只画界面，解释一律进叙事（硬约束 11）。
    # 说明条是最典型的污染：它长得像界面，其实是设计笔记——界面本身看不清，
    # 而且改动标注一旦挂在说明条上，说明条被删标注就跟着消失。
    # 只查 ui 帧：flow / diagram / explain 本来就是图，图里有说明文字是它的本分（硬约束 17）。
    _gn = []
    for f in ui_frames:
        n = (f.get("html") or "").count('class="px-gnote"')
        if n:
            _gn.append("%s×%d" % (f.get("id"), n))
    add(OK if not _gn else FAIL, "原型", "图上没有说明条",
        "干净——界面上只有界面该有的字" if not _gn else
        "这些帧还留着说明条：%s —— 把内容搬进叙事（字段字典 / 异常边界 / .dchg），原型只留界面"
        % "、".join(_gn))

    # 解释性长文本：界面提示写不到 80 字，写到这个长度基本是在讲设计意图。
    # 生成图放宽到 200 字、不看关键词——图注和图内节点本来就带判断语，用界面的尺子量它没有意义。
    _KW = ("为什么", "口径", "依据", "换句话说", "本质", "容易踩", "不要", "千万别", "按这个做")
    _long = []
    for f in drawn:
        _is_ui = (f.get("kind") or "ui") == "ui"
        _lim = 80 if _is_ui else 200
        for m in re.finditer(r">([^<>]{%d,})<" % _lim, f.get("html") or ""):
            t = m.group(1).strip()
            if _is_ui and not any(k in t for k in _KW):
                continue
            _long.append("%s「%s…」" % (f.get("id"), t[:14]))
    if _long:
        add(WARN, "原型", "长解释没混进界面",
            "%d 处读着像设计笔记：%s —— 确认识别的话是界面提示（两句以内才像产品文案）"
            % (len(_long), "、".join(_long[:4])))
    else:
        add(OK, "原型", "长解释没混进界面", "没有超长说明段落")

    # 原型必须对着真实页面画，不能凭印象
    ui_ok = any(s.get("name") == "浏览器渲染" and s.get("status") == "已核"
                for s in (d.get("sources") or []))
    if drawn and not ui_ok:
        add(FAIL, "内容", "原型有实拍对照吗",
            "有 %d 帧原型，但「浏览器渲染」源没标已核——这图是凭印象画的" % len(drawn))

    # 帧上写了 from 的，快照文件必须真在，否则这条凭据是编的。
    # 只查 ui 帧：生成图没有对应页面，逼它写 from 只会逼人编一个。
    froms = [f.get("from") for f in ui_frames if f.get("from")]
    no_from = [f.get("id") for f in ui_frames if not f.get("from")]
    if froms:
        snap_dir = os.path.join(root, "snapshot")
        missing, badref = [], []
        for ref in froms:
            fn, _, page = ref.partition("#")
            p = os.path.join(snap_dir, fn)
            if not os.path.isfile(p):
                missing.append(fn)
                continue
            try:
                sj = json.load(open(p, encoding="utf-8"))
                pages = {x.get("page") for x in (sj.get("frames") or [])}
                if page and page not in pages:
                    badref.append("%s 里没有 %s" % (fn, page))
            except Exception:  # noqa: BLE001
                badref.append("%s 读不了" % fn)
        if missing:
            add(FAIL, "内容", "原型有实拍快照吗",
                "以下快照文件不存在：%s —— 帧上的 from 指向了不存在的文件"
                % "、".join(sorted(set(missing))[:4]))
        elif badref:
            add(FAIL, "内容", "原型有实拍快照吗", "；".join(badref[:3]))
        else:
            add(OK, "内容", "原型有实拍快照吗",
                "%d 帧带 from，快照与页号都对得上" % len(froms))
    elif no_from:
        add(WARN, "内容", "原型有实拍快照吗",
            "这些界面帧上没有 from：%s —— 用 snapshot_page.py 实拍后生成，"
            "否则查不出这张图是照着页面画的还是凭印象画的"
            % "、".join(no_from[:6]))

    # 事实清单只有一份：模块里的必须和台账一致
    led = (facts or {}).get("facts") or []
    if led:
        a_ids = {x.get("id") for x in led}
        b_ids = {x.get("id") for x in fts}
        if a_ids == b_ids:
            add(OK, "内容", "事实清单 = 台账", "%d 条，编号一致" % len(a_ids))
        else:
            add(FAIL, "内容", "事实清单 = 台账",
                "台账 %d 条 / 模块 %d 条，%s"
                % (len(a_ids), len(b_ids),
                   "少了 " + "、".join(sorted(a_ids - b_ids)[:6]) if a_ids - b_ids
                   else "多了 " + "、".join(sorted(b_ids - a_ids)[:6])))

    # 台账 gate.total 是建台账时写死的：后来补了事实没同步，自检里就会显示成
    # 「含本模块 ? 条事实」这种半截话，读的人不知道是没填还是漏了。
    _g = (facts or {}).get("gate") or {}
    _t = _g.get("total")
    _n = len(fts)
    if _t is not None and _t != _n:
        add(WARN, "数据", "台账条数", "gate.total=%s，实际 %d 条" % (_t, _n))

    # ---------------- 文与图一致 ----------------
    # 正文写「17 列宽表」「9 列结构不变」，图上是另一张表，此前出过「正文 9 列、图上 7 列」。
    # 精度优先，分两条：列名比对（主判据，误报低）、列数比对（只查明确句式）。
    # 不做对象识别就比对会大量误报——一个模块里有列表 7 列、人员明细 17 列、日志 19 列，
    # 正文的「N 列」不都指向主列表，所以只认「列数不变 N 列」「N 列结构」这两种说法。
    _th_of = {}
    for f in drawn:
        ths = [re.sub(r"<[^>]+>", "", x).replace("&nbsp;", " ").strip()
               for x in re.findall(r"<th[^>]*>(.*?)</th>", f.get("html") or "", re.S)]
        # 表头里常嵌改动编号（改①打款账户、改⑥改⑥请款金额），不去掉的话
        # 正文引用「打款账户」永远匹配不上，四条误报全出在这儿。
        ths = [re.sub(r"^(?:改[\u2460-\u24FF\u3251-\u325F\u32B1-\u32BF]+)+", "", t).strip()
               for t in ths]
        _th_of[f.get("id")] = [t for t in ths if t]
    _all_th = {t for v in _th_of.values() for t in v}
    _ui_ids = {f.get("id") for f in ui_frames}
    _sec_txt = "\n".join((s.get("html") or "") for s in secs)

    _bad_name = []
    _cand = []
    # 只认紧邻的两种说法：「XXX」列 / 列「XXX」。
    # 早先用「前后 20 字内有『列』字」——把「这一行」「逐条列着」「页签…列着」全算成列名引用，
    # 五个模块报了 25 处，逐条核完全是误报。列名引用必须是紧挨着的。
    for m in re.finditer(r"「([^」]{2,14})」列(?!着)", _sec_txt):
        _cand.append(m.group(1))
    for m in re.finditer(r"列「([^」]{2,14})」", _sec_txt):
        _cand.append(m.group(1))
    for name in _cand:
        name = name.strip()
        if re.search(r"[<>，。；、：！？（）()\s]", name):   # 带标签或标点：不是列名
            continue
        if name in ("—", "无", "-", "／", "/", "不变", "同前", "这一", "该"):
            continue
        # 合并表头很常见（「请款状态和费用所属月」一格管两列），正文只引其中一段是对的
        if name not in _all_th and not any(name in t for t in _all_th):
            _bad_name.append(name)
    _bad_name = sorted(set(_bad_name))
    if _bad_name:
        add(WARN, "内容", "文与图一致（列名）",
            "正文提到的列名原型表头里没有：%s —— 图上口径改了正文没跟上"
            % "、".join(_bad_name[:5]))
    elif _all_th:
        add(OK, "内容", "文与图一致（列名）", "正文引用的列名都能在表头里找到")

    # 主列表帧 = 界面帧里「只有一个表、th 最多」的那一帧。
    # 限定单表很关键：详情页常常是两三张表拼在一帧里（29 个 th），
    # 拿它当主列表去比「正文说 7 列」必然误报。
    _tbls = {f.get("id"): len(re.findall(r"<table", f.get("html") or "")) for f in drawn}
    _main = None
    for _fid, _ths in _th_of.items():
        if _fid not in _ui_ids or _tbls.get(_fid) != 1:
            continue
        if _main is None or len(_ths) > _main[1]:
            _main = (_fid, len(_ths))
    _bad_num = []
    for _pat in (r"列数(?:还是|仍为|不变)[：: ]?\s*(\d+)\s*列", r"(\d+)\s*列结构"):
        for m in re.finditer(_pat, _sec_txt):
            n = int(m.group(1))
            if _main and n != _main[1]:
                _bad_num.append("%d 列" % n)
    if _bad_num:
        add(WARN, "内容", "文与图一致（列数）",
            "正文说 %s，主列表图上 %s %d 列"
            % ("、".join(sorted(set(_bad_num))), _main[0], _main[1]))

    # ---------------- 改动块：只写改后，且改后能逐条核对 ----------------
    # 这套文档**刻意不写「改前」**：它是增量文档，讲新版长什么样，要对比去看系统。
    # 所以这里绝不把「有没有改前」当通过条件，也不建议作者补改前。
    _blks = _dchg_blocks("\n".join((s.get("html") or "") for s in secs))
    if _blks:
        _sf, _n_long, _n_dun, _n_semi = [], 0, 0, 0
        _forms = set()
        for _c, _b in _blks:
            _p = _chg_struct(_c, _b)
            if _p:
                _sf.append(_p)
            _x, _y, _z = _chg_style(_b)
            _n_long, _n_dun, _n_semi = _n_long + _x, _n_dun + _y, _n_semi + _z
            if "<table" in _b:
                _forms.add("表格")
            elif "<ol" in _b or len(_NUM_HEAD.findall(_b)) >= 2:
                _forms.add("列点")
            else:
                _forms.add("文字")
        if _sf:
            for _p in _sf:
                add(WARN, "内容", "改动块能逐条核对", _p)
        else:
            add(OK, "内容", "改动块能逐条核对", "%d 块，都能按条核对" % len(_blks))
        if len(_forms) > 1:
            add(WARN, "内容", "改动块形态统一",
                "同一模块里混用了 %s —— 读者要在两种排版之间来回换眼，尽量统一"
                % "、".join(sorted(_forms)))
        _tot2 = _n_long + _n_dun + _n_semi
        if _tot2:
            add(WARN, "措辞", "改动块文案密度",
                "本模块 %d 处：单句超 50 字 %d、顿号串 %d、段内两个分号 %d —— 一句一件事"
                % (_tot2, _n_long, _n_dun, _n_semi))
        else:
            add(OK, "措辞", "改动块文案密度", "没有挤在一起的句子")

    want = 1 + len([x for x in (d.get("dialogs") or []) if x.get("covered")])
    if len(drawn) < want:
        add(FAIL, "内容", "弹窗/二级页都画了吗",
            "清单里 %d 个（含主页面）已覆盖，原型只有 %d 帧，缺 %d 个——"
            "弹窗没画，研发只能自己猜"
            % (want, len(drawn), want - len(drawn)))

    # ---------------- 产物一致 ----------------
    if not os.path.exists(hp):
        add(FAIL, "产物", "HTML", "不存在，先跑 build_module_prd.py")
    else:
        add(OK, "产物", "HTML", "%.1f KB" % (os.path.getsize(hp) / 1024))
        if os.path.getmtime(hp) + 1 < os.path.getmtime(mp):
            add(FAIL, "产物", "产物新鲜度", "json 比 html 新——改完数据没重新构建")
        else:
            add(OK, "产物", "产物新鲜度", "晚于数据文件")
        html = open(hp, encoding="utf-8").read()
        inner = extract_prd_data(html)
        if inner is None:
            add(FAIL, "产物", "页内数据", "解析不出 window.PRD_DATA，模板可能被改过")
        elif canon(inner) != canon(d):
            add(FAIL, "产物", "页内数据 = json", "不一致——HTML 被手改过，或者不是这份 json 生成的")
        else:
            add(OK, "产物", "页内数据 = json", "逐字节一致")
        ext = re.findall(r'(?:src|href)="(https?://[^"]+)"', html)
        add(OK if not ext else WARN, "产物", "离线可用",
            "无外链" if not ext else "有 %d 个外链，离线打开会缺资源：%s" % (len(ext), ext[:2]))

        # 样式完整性：补丁 CSS（proto_extra.css 等）里混进一个 </style> 字面量，
        # 会把后面的样式挤出 <style> 块、变成正文里的裸 CSS——页面表现为「一部分样式失效」，
        # 肉眼很难定位。这里三件事一起查：数量配对、每块不空、尾部没漏。
        _so = len(re.findall(r"<style[^>]*>", html))
        _sc = html.count("</style>")
        _blocks = re.findall(r"<style[^>]*>(.*?)</style>", html, re.S)
        _short = [i + 1 for i, b in enumerate(_blocks) if len(b.strip()) < 200]
        _tail = html.rsplit("</style>", 1)[-1] if _sc else html
        _leak = re.search(r"\.[a-zA-Z][\w-]*\s*\{[^}]{0,400}:[^}]{0,400}\}", _tail)
        if _so != _sc:
            add(FAIL, "产物", "样式块完整",
                "开 %d 个 <style>、闭 %d 个 </style>，对不上——某块被提前闭合了" % (_so, _sc))
        elif _short:
            add(FAIL, "产物", "样式块完整",
                "第 %s 块样式不足 200 字符，像是被截断了" % "、".join(str(i) for i in _short[:4]))
        elif _leak:
            add(FAIL, "产物", "样式块完整",
                "最后一个 </style> 之后还有 CSS 规则（%s…）——样式漏进正文了"
                % _leak.group(0)[:36])
        else:
            add(OK, "产物", "样式块完整", "%d 块，长度正常且都在 style 里" % len(_blocks))

    # ---------------- 命名规范（第二道门禁） ----------------
    # 第一道在 schema._check_naming（数据层）。这里再扫产物 HTML，
    # 因为有人会直接改 html，或者把稿次写进模板文案里，数据层看不见。
    ver = (mt.get("version") or "").strip()
    ver_ok = bool(S.VERSION_PAT.match(ver))
    add(OK if ver_ok else FAIL, "命名", "版本写法（产品版本 + 第 N 稿）",
        ver if ver_ok else
        "必须写成「管理后台 V5.0 · <需求名> · 第 N 稿」。稿次不是版本号，不要用 V10.1 表示：%r" % ver)

    allowed = {"V5.0"}          # 当前产品版本；换版时 schema 会按 meta.version 自动放行
    mv = re.match(r"^管理后台 (V\d{1,2}\.\d{1,2})", ver)
    if mv:
        allowed.add(mv.group(1))

    def _bad_versions(text):
        return [x for x in re.findall(r"V\d{1,2}\.\d{1,2}", text) if x not in allowed]

    bad_data = _bad_versions(json.dumps(d, ensure_ascii=False))
    add(OK if not bad_data else FAIL, "命名", "数据里没有 V 稿次",
        "" if not bad_data
        else "稿次被写成了 V 版本号：%s（改成「第 N 稿」）" % "、".join(sorted(set(bad_data))[:5]))

    if os.path.exists(hp):
        prod = open(hp, encoding="utf-8").read()
        bad_prod = _bad_versions(prod)
        add(OK if not bad_prod else FAIL, "命名", "产物里没有 V 稿次",
            "" if not bad_prod
            else "HTML 里有 %d 处：%s —— 数据改了没重建，或有人手改过产物"
            % (len(bad_prod), "、".join(sorted(set(bad_prod))[:5])))
        dup = re.search(r"VV\d[\d.]*", prod)
        add(OK if not dup else FAIL, "命名", "没有 VV 重复",
            "" if not dup else "版本号被加了两次：%s（批量替换时把 V 加重复了）" % dup.group(0))

    # ---------------- 措辞（W1 角色词 / W3 量词 / W4 占位） ----------------
    # 稿次类问题（W2/W5）交给上面的「命名」组，这里不重复报。
    sw = os.path.join(HERE, "scan_wording.py")
    if os.path.exists(sw):
        r = subprocess.run([sys.executable, sw, "--path", mp, "--json", "--warn"],
                           capture_output=True, text=True)
        try:
            hits = [h for h in json.loads(r.stdout or "[]") if h.get("code") in ("W1", "W3", "W4")]
        except Exception:  # noqa: BLE001
            hits = []
        if hits:
            kinds = {}
            for h in hits:
                kinds[h["code"]] = kinds.get(h["code"], 0) + 1
            add(FAIL, "措辞", "角色词 / 量词 / 占位",
                "、".join("%s×%d" % (k, v) for k, v in sorted(kinds.items()))
                + "（跑 scan_wording.py --path %s 看具体位置）" % os.path.basename(mp))
        else:
            add(OK, "措辞", "角色词 / 量词 / 占位", "无命中")
    else:
        add(WARN, "措辞", "scan_wording.py", "脚本不存在，跳过")

    # ---------------- 迭代（交付 B 专用） ----------------
    # 现状 PRD 不标改动；迭代 PRD 必须标，而且要能证明「说了要改的都标了」。
    # 这里只查当前模块；范围本身是否登记过，用 plan_iteration.py --check。
    mode = (run or {}).get("mode")
    if mode == "iterate":
        scope = (run or {}).get("scope") or []
        mine = [x for x in scope if x.get("key") == key]
        draft = (run or {}).get("draft")
        ver_draft = re.search(r"第\s*(\d{1,3})\s*稿", (mt.get("version") or ""))
        add(OK if draft and ver_draft and int(ver_draft.group(1)) == draft else FAIL,
            "迭代", "稿次与 run.json 一致",
            ("第 %s 稿" % draft) if draft and ver_draft and int(ver_draft.group(1)) == draft
            else "run.json=第 %s 稿，meta.version=%s —— 稿次没跟上"
                 % (draft, ver_draft.group(0) if ver_draft else "没有稿次"))

        proto_html = " ".join((f.get("html") or "") for f in (d.get("prototype") or {}).get("frames") or [])
        doc_html = " ".join((s.get("html") or "") for s in secs)
        pc = set(re.findall(r'data-chg=\\?["\'](C\d{1,3})', proto_html))
        dc = set(re.findall(r'data-chg=\\?["\'](C\d{1,3})', doc_html))

        # 编号 → 稿次（属性顺序不固定，先框住整个标签再分别取）
        _seen = {}
        for _tag in re.finditer(r"<[^>]*\bdata-chg=\"(C\d{1,3})\"[^>]*>", proto_html + doc_html):
            _dm = re.search(r'data-draft="(\d{1,2})"', _tag.group(0))
            _seen.setdefault(_tag.group(1), int(_dm.group(1)) if _dm else 0)
        _cur = sorted([c for c, dd in _seen.items() if draft and dd == draft],
                      key=lambda x: int(x[1:]))
        _old = sorted([c for c, dd in _seen.items() if not draft or dd != draft],
                      key=lambda x: int(x[1:]))

        if mine:
            add(OK if pc else FAIL, "迭代", "范围内的改动画了吗",
                "%s 处：%s" % (len(pc), "、".join(sorted(pc, key=lambda x: int(x[1:]))))
                if pc else
                "本模块在本次范围内（%s），但原型里一个 data-chg 都没有 —— 说了要改，图上没标"
                % "、".join("%s %s" % (x.get("kind", ""), x.get("what", "")) for x in mine))
            want = {c for x in mine for c in (x.get("chg") or [])}
            miss = sorted(want - pc, key=lambda x: int(x[1:]))
            if miss:
                add(FAIL, "迭代", "范围编号都落到图上了",
                    "这些编号在原型里找不到：%s" % "、".join(miss))
            elif want:
                add(OK, "迭代", "范围编号都落到图上了", "%d 个编号都能在原型里找到" % len(want))
            # 原型与叙事必须同号：只在图上标、正文不提，读者不知道这处为什么改
            only_p = sorted(pc - dc, key=lambda x: int(x[1:]))
            if only_p:
                add(WARN, "迭代", "原型与叙事同号",
                    "这些编号只在原型里出现，正文没写：%s（正文补一段 .dchg 说明为什么改）"
                    % "、".join(only_p))
            else:
                add(OK, "迭代", "原型与叙事同号", "原型 %d 处 / 叙事 %d 处，编号一致"
                    % (len(pc), len(dc)))

            # 本稿 vs 累积：编号是跨稿累积的，只报「有改动」等于没说这一稿动了什么。
            # 业务方当场把「20 处改动」读成「这一稿改了 20 处」，所以要能筛出本稿。
            _need = [x for x in mine if x.get("kind") != "删除"]
            if _cur:
                add(OK, "迭代", "本稿改动筛得出来",
                    "本稿 %d 处（%s）；前稿累积 %d 处"
                    % (len(_cur), "、".join(_cur), len(_old)))
            elif _need:
                add(FAIL, "迭代", "本稿改动筛得出来",
                    "范围里说本稿要改，但没有任何标注的 data-draft 等于第 %s 稿 —— "
                    "标记要么漏写稿次，要么标的是前几稿的旧改动" % draft)
            else:
                add(OK, "迭代", "本稿改动筛得出来", "本稿只有删除，没有新增标注")
        else:
            # 范围是「本稿改哪些」，不是「这条需求线一共改过哪些」。
            # 前几稿改过的模块不在 scope 里是正常的，不该报；只有本稿还往上加标注才叫漏登。
            add(WARN if _cur else OK, "迭代", "范围外的模块",
                "本模块不在本次 scope 里，但本稿还有 %d 处新标注（%s）—— 要么补进 scope，要么撤掉"
                % (len(_cur), "、".join(_cur)) if _cur
                else ("本模块本次不改（前稿标注 %d 处，属历史）" % len(_old) if _old
                      else "本模块本次不改，原型干净"))

        # 锚点：data-goto 指向的 id 必须真存在，跳空比没有链接更糟
        if os.path.exists(hp):
            prod_all = open(hp, encoding="utf-8").read()
            gotos = set(re.findall(r'data-goto=\\?["\']([^"\'\\]+)', prod_all))
            ids = set(re.findall(r'id=\\?["\']([^"\'\\]+)', prod_all))
            dead = sorted(gotos - ids)
            # 锚点不是越多越好：改动徽标点一下已经会跳到叙事并连线（data-chg）。
            # data-goto 只在「正文里提到的东西在另一处」时才有意义——附录、跨段引用。
            # 没写附录的模块没有锚点是正常的，不该报成一个待办。
            has_ref = "附录" in " ".join(re.sub(r"<[^>]+>", "", s.get("html") or "") for s in secs)
            if dead:
                add(FAIL, "迭代", "锚点都能跳", "这些锚点目标不存在：%s" % "、".join(dead[:5]))
            elif not gotos and has_ref:
                add(WARN, "迭代", "锚点都能跳",
                    "正文引用了附录，却没有 data-goto —— 读者得自己翻到附录，补一个锚点即可")
            elif not gotos:
                add(OK, "迭代", "锚点都能跳", "没有跨处引用，不需要锚点")
            else:
                add(OK, "迭代", "锚点都能跳", "%d 个锚点全部有落点" % len(gotos))

    # ---------------- 反查（第二层：从产物回到数据） ----------------
    # 第一层查「数据对不对」，方向是数据 → 产物。这一层反着来：产物里到底有没有。
    # 两层缺一不可——数据全合规但渲染丢了，第一层全绿，读的人看到的却是空的。
    prod = ""
    if os.path.exists(hp):
        prod = open(hp, encoding="utf-8").read()

    rids = [r.get("id") for r in (d.get("rules") or []) if r.get("id")]
    lost = [i for i in rids if i not in prod] if prod else rids
    add(FAIL if (lost and prod) else (WARN if lost else OK), "反查", "规则都在产物里",
        "%d 条规则全部渲染出来了" % len(rids) if not lost else
        ("产物里找不到这些规则：%s —— 数据写了没渲染，或模板漏了" % "、".join(lost[:6])
         if prod else "没有产物 HTML，没法反查"))

    fts_d = d.get("facts") or []
    cited = set()
    for r in (d.get("rules") or []):
        cited |= set(r.get("facts") or [])
    cited |= set(re.findall(r"F-\d{1,3}",
                            " ".join((s.get("html") or "") for s in (d.get("sections") or []))))
    p0 = [f for f in fts_d if f.get("sev") == "P0"]
    dead = [f.get("id") for f in p0 if f.get("id") not in cited]
    add(OK if not dead else gate_lv, "反查", "P0 事实都被引用",
        "%d 条 P0 都指回了正文" % len(p0) if not dead else
        "这些 P0 核了却没有一条规则/段落引用：%s —— 读者找不到它影响了什么" % "、".join(dead[:6]))

    answered = [q for q in (d.get("questions") or []) if q.get("status") == "answered"]
    thin = [q.get("id") for q in answered if len((q.get("answer") or "").strip()) < 6]
    add(OK if not thin else gate_lv, "反查", "答案不是空话",
        "%d 条已答都写了结论" % len(answered) if not thin else
        "这些已答项答案不到 6 个字，等于没答：%s" % "、".join(thin[:6]))

    frames = (d.get("prototype") or {}).get("frames") or []
    labels = " ".join(((f.get("name") or "") + " " + (f.get("note") or "")) for f in frames)
    # 二级页常常整块拆到独立模块（如「合作方请款审批」自己就是一个模块），
    # 只查本模块会把「已经画了、只是画在隔壁」判成漏画。所以本模块找不到时，
    # 再到工程里其他模块的帧名里找一遍——找到了就是覆盖了，只是不在这份文件里。
    other = ""
    mod_dir = os.path.join(root, "modules")
    if os.path.isdir(mod_dir):
        for fn in sorted(os.listdir(mod_dir)):
            if not fn.endswith(".json") or fn == key + ".json":
                continue
            try:
                od, _e = load_json(os.path.join(mod_dir, fn))
                od = od or {}
            except Exception:
                continue
            for f in ((od.get("prototype") or {}).get("frames") or []):
                other += " " + (f.get("name") or "") + " " + (f.get("note") or "")
    def _hit(name):
        """名字带括号补充说明时要宽松匹配：「合作方请款详情（三个页签）」对不上帧名，
        但「合作方请款详情」能对上。只取括号前那一段做子串比较，别退化成任意词命中。"""
        if name in labels or name in other:
            return True
        for seg in re.split(r"[（(]", name):
            seg = seg.strip()
            if len(seg) >= 4 and (seg in labels or seg in other):
                return True
        return False

    miss_dlg = [x.get("name") for x in (d.get("dialogs") or [])
                if x.get("covered") and x.get("name") and not _hit(x.get("name"))]
    elsewhere = [x.get("name") for x in (d.get("dialogs") or [])
                 if x.get("covered") and x.get("name")
                 and x.get("name") not in labels and _hit(x.get("name"))]
    add(OK if not miss_dlg else gate_lv, "反查", "弹窗清单对得上帧",
        ("标了 covered 的弹窗都能在帧里找到"
         + ("（%d 个在别的模块里画：%s）" % (len(elsewhere), "、".join(elsewhere)) if elsewhere else ""))
        if not miss_dlg else
        "这些弹窗标了 covered，但帧名和说明里都没有：%s" % "、".join(miss_dlg[:5]))

    # ---------------- 叙事骨架（v5.3） ----------------
    # 「六段各写什么」大部分只能人判，但有三条机器一定判得了，而且这次都真出过错：
    #   ① S1 说「共 N 处改动」，第 4 段就得有 N 个改动点块。一个模块少写 4 条正文，
    #      门禁原来一条都不报——总览还是「16 处」，读者点进去什么都没有。
    #   ② S1 索引（.ci 里的 chg-jump）列了编号，正文却找不到块：点过去是空的。
    #   ③ S3 / S7 是不是真换成了对照表 / 四列表。老写法是一串 <ol> 与 <ul> 要点，
    #      读的人得自己对两遍流程，且「两条同时不满足时先弹哪个」写不出来。
    if mode == "iterate":
        _sec = {x.get("n"): (x.get("html") or "") for x in secs}
        _s1, _s3, _s4, _s7 = (_sec.get(1, ""), _sec.get(3, ""), _sec.get(4, ""), _sec.get(7, ""))
        _txt = lambda h: re.sub(r"<[^>]+>", "", h)

        _decl = re.search(r"(?:一共|共)\s*(\d+)\s*处改动", _txt(_s1))
        _blks = set(re.findall(r'<div class="(?:dchg|dwip)[^"]*"[^>]*data-chg="(C\d+)"', _s4))
        if _decl:
            _n = int(_decl.group(1))
            add(OK if len(_blks) == _n else FAIL, "叙事骨架", "S1 说几处，第 4 段就写几处",
                ("%d 处：%s" % (len(_blks), "、".join(sorted(_blks, key=lambda x: int(x[1:])))))
                if len(_blks) == _n else
                "S1 写「%d 处改动」，第 4 段只有 %d 个改动点块 —— 缺的那些是「只有编号没有正文」，"
                "读者点过去是空的" % (_n, len(_blks)))

        _ci = set(re.findall(r'class="chg-jump"[^>]*data-chg="(C\d+)"', _s1))
        _miss = sorted(_ci - _blks, key=lambda x: int(x[1:]))
        if _ci:
            add(FAIL if _miss else OK, "叙事骨架", "索引里的编号正文都有",
                "%d 个编号都能落到正文块" % len(_ci) if not _miss else
                "这些编号在索引里能点，但正文没有对应块：%s —— 点过去是空的，"
                "读者不知道这处为什么改" % "、".join(_miss[:8]))

        _t3 = _txt(_s3)
        _cmp = ("改造前" in _t3 and "改造后" in _t3)
        add(OK if _cmp else WARN, "叙事骨架", "S3 是改前 / 改后对照表",
            "有「改造前 / 改造后」两列" if _cmp else
            "S3 没写成「步骤 × 改造前 × 改造后 × 差异」——散文式流程，读者要自己对两遍才看出差在哪")

        _t7 = _txt(_s7)
        _quad = ("触发" in _t7) and ("禁止" in _t7 or "兜底" in _t7)
        add(OK if _quad else WARN, "叙事骨架", "S7 是四列表",
            "情形 / 触发条件 / 系统行为 / 禁止做法·兜底" if _quad else
            "S7 还是要点式清单——「两条同时不满足时先弹哪个」这种问题，清单写法答不出来")

        _t1 = _txt(_s1)
        _need = [k for k in ("访问路径", "功能权限", "数据权限") if k not in _t1]
        add(OK if not _need else WARN, "叙事骨架", "S1 五要素齐",
            "数据范围 / 访问路径 / 功能权限 / 数据权限 / 归属字段" if not _need else
            "S1 缺：%s —— 定位段写成「本页面用于管理 XX」就是五个槽全空" % "、".join(_need))

    # ---------------- 读者友好（v5.4） ----------------
    # 需求文档写给做决定的人看。正文里出现接口地址、字段名、常量名、实现词，
    # 业务方看不懂就不再逐条读，评审会变成点头，做出来才发现理解错了。
    # 这三条都是「文档已经到了能读」的底线，但只有第一条能机器判死。
    _TECH_MAP = re.compile(r'<table[^>]*class="[^"]*tech-map[^"]*"[\s\S]*?</table>', re.I)
    _TAG = re.compile(r"<[^>]+>")
    _PATH = re.compile(r"/[A-Za-z][\w{}$.\-]*(?:/[\w{}$.\-]+)*")
    _API = re.compile(r"\b(?:GET|POST|PUT|DELETE|PATCH)\s+/[\w/{}\-.$]+|/demobackstage/[\w/]+")
    _CAMEL = re.compile(r"\b[a-z][a-z0-9]*[A-Z][A-Za-z0-9]*\b")
    _SNAKE = re.compile(r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b")
    _CONST = re.compile(r"\bConstant\.[A-Za-z_]+|\b[A-Z][A-Z0-9]{2,}(?:_[A-Z0-9]+)+\b")
    _IMPL = ["落库", "入库", "幂等", "序列化", "反序列化", "schema", "Schema", "轮询",
             "回调", "补丁", "DTO", "VO", "DAO", "SQL", "JWT", "事务", "并发", "缓存",
             "灰度", "接口返回", "表结构", "字段值"]

    _narr = {x.get("n"): (x.get("html") or "") for x in secs}
    _body_all = "".join(_narr.values())
    _vis = _TAG.sub("", _TECH_MAP.sub("", _body_all))
    _np = _PATH.sub(" ", _vis)

    _api_hit = len(_API.findall(_vis))
    add(OK if _api_hit == 0 else FAIL, "读者友好", "正文没有接口地址",
        "正文零接口地址" if _api_hit == 0 else
        "正文里有 %d 处接口地址（POST /xxx、/demobackstage/…）—— 业务方不调接口，"
        "把地址挪进附录 B，正文写「谁点了什么、系统做了什么」" % _api_hit)

    _other = len(_CAMEL.findall(_np)) + len(_SNAKE.findall(_np)) + len(_CONST.findall(_np)) \
             + sum(_np.count(w) for w in _IMPL)
    add(OK if _other == 0 else WARN, "读者友好", "正文没有字段名与实现词",
        "零命中" if _other == 0 else
        "%d 处（字段名 / 常量名 / 落库·幂等·schema 这类实现词）—— 换成界面上那一列的字，"
        "和「它保证了什么」（存下来 / 重复点也只生效一次 / 对方回话）" % _other)

    # 技术细节删掉之后必须有地方可查。两条路都行：
    #   ① 第 7 段末的附录 B（table.tech-map）—— 适合只给对照表、不解释的
    #   ② 代码逻辑栏的 fe/be 对照 —— 更适合要顺带讲清楚的
    # 两者有其一即通过；都空才是问题：技术细节被删干净了，研发反查无处可查。
    _s7 = _narr.get(7, "")
    _has_map = 'tech-map' in _s7
    _has_code = bool((d.get("code") or {}).get("fe") or (d.get("code") or {}).get("be"))
    add(OK if (_has_map or _has_code) else FAIL, "读者友好", "技术细节有处可查",
        ("附录 B（%s）" % ("有" if _has_map else "无")
         + " · 代码栏对照（%s）" % ("有" if _has_code else "无"))
        if (_has_map or _has_code) else
        "正文技术细节清掉了，但没留反查的地方 —— 补附录 B（table.tech-map）"
        "或在「代码逻辑」栏写前后端对照")

    # 分栏后的两块：用例与代码。缺了不算致命，但要说清楚缺什么——
    # 「文档讲业务、用例归一处、代码单独一栏」这个结构一旦破了，读者又要在三套语言里切换。
    _tcs = d.get("testcases") or []
    add(OK if _tcs else WARN, "读者友好", "测试用例已归到一处",
        "%d 条，分 %d 组" % (len(_tcs), len({x.get("group") for x in _tcs})) if _tcs else
        "还没有规整的用例 —— 用例散在用例库里，改一条规则没人知道要重跑哪些")

    # 挂不上规则是允许的（筛选、分页、导出这类页面通用行为），但要写明为什么；
    # 空着不写才当成「漏挂」——否则 32 条用例里 9 条永远黄着，黄久了就没人看了。
    _norule = [x.get("id") for x in _tcs if not (x.get("rules") or []) and not x.get("norule")]
    _explained = [x for x in _tcs if not (x.get("rules") or []) and x.get("norule")]
    if _tcs:
        add(OK if not _norule else WARN, "读者友好", "用例都挂到了规则上",
            "每条都标了守哪条规则" + ("；另有 %d 条写明了不挂的原因" % len(_explained) if _explained else "")
            if not _norule else
            "这 %d 条既没挂规则、也没写为什么：%s —— 不写原因，规则改了也筛不出要重写谁"
            % (len(_norule), "、".join(_norule[:6])))

    _code = d.get("code") or {}
    _plain = _code.get("plain") or []
    _febe = (_code.get("fe") or []) + (_code.get("be") or [])
    add(OK if (_plain and _febe) else WARN, "读者友好", "代码栏有大白话 + 技术对照两段",
        "大白话 %d 条 · 前后端对照 %d 条" % (len(_plain), len(_febe)) if (_plain and _febe) else
        "代码栏缺一半 —— 只有技术对照，业务方看不了；只有大白话，研发动不了手")

    _ent = (d.get("entities") or "").strip()
    add(OK if _ent else WARN, "读者友好", "有实体关系（谁生成谁）",
        "有，第 6 段自动渲染成层级" if _ent else
        "没写 entities —— 出问题时不知道顺着哪条单据线往上找")

    _t2 = _TAG.sub("", _narr.get(2, ""))
    _scene = ("典型场景" in _t2) or ("前提" in _t2 and "页面显示" in _t2)
    add(OK if _scene else WARN, "读者友好", "第 2 段末有典型场景表",
        "有" if _scene else
        "没有典型场景表 —— 复杂逻辑靠形容词讲不清，给 case：谁 / 做什么 / 系统怎么反应 / 看的人据此做什么")

    # ---------------- 签字（第二层的第二半：人） ----------------
    # 机器只能证明「有没有签」，证明不了「签得对不对」。所以要求两个不同的人，
    # 且业务签字不能是本模块作者——自己确认自己的口径，等于没有第二层。
    so = (facts or {}).get("signoff") or {}
    sg = S.signer_of(so)
    # 封板只证明「有人认过」，不证明「认的是现在这一版」。逐份比内容指纹：
    # 封完又改了内容，那签就不算数——不管稿次动没动。
    _mhash = S.content_digest(mp)
    _dg = sg.get("digest")
    stale = bool(_dg and _mhash and _dg != _mhash)
    signed = (bool(sg.get("by")) and not stale) or ds_ok
    if sg.get("by") and not stale:
        _why3 = "%s @ %s%s" % (sg.get("by"), sg.get("at") or "—",
                               "  " + sg["note"] if sg.get("note") else "")
    elif ds_ok:
        # 整份封板还有效。分两种：模块那个封板失效了，或者压根没做过模块封板——
        # 后者不能说「已失效」，那会让人以为自己的签丢了。
        if sg.get("by"):
            _why3 = "%s（模块封板已失效，按整份确认记）" % ds_txt
        else:
            _why3 = "%s（按整份确认记，未走模块封板）" % ds_txt
    elif stale:
        _why3 = ("%s 封的是旧内容——这个模块在封板之后被改过。"
                 "重新封一次：gate.py sign --by <姓名>" % sg.get("by"))
    else:
        _why3 = ("还没有人封板。gate.py sign --by <姓名> 封这个模块，"
                 "或 gate.py doc --by <姓名> 封整份")
    add(OK if signed else gate_lv, "签字", "已封板", _why3)

    # ---------------- 安全 ----------------
    if want_audit:
        ap = os.path.join(HERE, "audit_no_secrets.py")
        if os.path.exists(ap):
            r = subprocess.run([sys.executable, ap, "--path", root],
                               capture_output=True, text=True)
            clean = r.returncode == 0
            add(OK if clean else FAIL, "安全", "无明文凭据",
                "" if clean else (r.stdout or r.stderr).strip().split("\n")[-1][:120])
        else:
            add(WARN, "安全", "凭据审计", "audit_no_secrets.py 不存在，跳过")

    return items, any(i[0] == FAIL for i in items)


def render(items, title, strict):
    print("=" * 72)
    print(title)
    print("=" * 72)
    grp = None
    n_fail = n_warn = 0
    for lv, g, name, detail in items:
        if g != grp:
            print("\n[%s]" % g)
            grp = g
        if lv == FAIL:
            n_fail += 1
        elif lv == WARN:
            n_warn += 1
        print("  %s %-26s %s" % (MARK[lv], name, detail))
    print()
    if n_fail:
        print("结论：%d 项未通过%s，不能交付。" % (n_fail, "（--strict）" if strict else ""))
    elif n_warn:
        print("结论：通过，但有 %d 项提醒。建议处理掉再交。" % n_warn)
    else:
        print("结论：全绿，可以交付。")
    return n_fail, n_warn



def _PY():
    """提示语里该写 python 还是 python3 —— Windows 上没有 python3 这个入口。"""
    try:
        import _compat
        return _compat.python_cmd()
    except Exception:  # noqa: BLE001
        return "python3"


def main():
    ap = argparse.ArgumentParser(description="模块 PRD 交付验收")
    ap.add_argument("--root", required=True)
    ap.add_argument("--module", help="模块 key")
    ap.add_argument("--all", action="store_true", help="检查工作台里全部模块")
    ap.add_argument("--strict", action="store_true", help="有未通过项就退出非 0")
    ap.add_argument("--no-audit", action="store_true", help="跳过凭据审计")
    a = ap.parse_args()

    root = os.path.abspath(os.path.expanduser(a.root))
    if not os.path.isdir(root):
        sys.exit("✗ 目录不存在：%s" % root)

    keys = []
    if a.all:
        run, err = load_json(os.path.join(root, "run.json"))
        if not run:
            sys.exit("✗ " + (err or "run.json 缺失"))
        keys = [m["key"] for m in run.get("modules", [])]
    elif a.module:
        keys = [a.module]
    else:
        sys.exit("✗ 给 --module <key> 或 --all")

    total_fail = 0
    for k in keys:
        items, fatal = check_one(root, k, want_audit=not a.no_audit, hard=a.strict)
        f, w = render(items, "模块 %s · 交付验收" % k, a.strict)
        total_fail += f
        print()

    if len(keys) > 1:
        print("=" * 72)
        print("汇总：%d 个模块，%d 项未通过" % (len(keys), total_fail))
        if total_fail == 0:
            print("可以合并：%s merge_modules.py --root %s --out 全量PRD.html"
                  % (_PY(), root))

    if total_fail and a.strict:
        sys.exit(1)


if __name__ == "__main__":
    import _compat as _c   # 控制台编码兜底（Windows 默认 cp936 编不出 ✓ ✗）
    _c.init()
    main()
