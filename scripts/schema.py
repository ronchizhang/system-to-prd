#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
module.json 的数据契约（唯一真相）与零依赖校验器。

为什么不用 jsonschema 库：团队机器上不一定装了，而这个 skill 必须开箱能跑。
这里实现 JSON Schema 的常用子集，够用且报错更贴近业务（会说「第 5 段应该是业务规则」而不是
「/sections/4 不满足 const 约束」）。

导出可读契约：python3 schema.py --dump ../assets/module.schema.json
"""

import json
import os
import re
import sys

SCHEMA_ID = "module/1.0"
ENGINE = "system-to-prd@2.0"

# ---------------------------------------------------------------- 枚举

CONF = {"互证", "双证", "单源", "确立"}                 # 证据强度；确立=业务方直接裁定，不需他源佐证
SRC = {"ui", "api", "fe", "be", "ima", "biz"}         # 六个来源
SRC_STATUS = {"已核", "部分", "未核", "不可达"}
RULE_TYPE = {"principle", "constraint", "validation", "transition",
             "calculation", "permission", "display", "layout"}
CASE_KIND = {"positive", "negative", "edge", "conflict"}
TRANS_KIND = {"normal", "back", "danger", "draft"}
DLG_TYPE = {"二级页", "弹窗", "抽屉", "分步"}
FACT_CLS = {"fix", "add", "conflict", "risk", "ask", "ok"}
# fix 需改 / add 补漏 / conflict 多源冲突 / risk 有隐患 / ask 待裁定 / ok 核过一致
FACT_SEV = {"P0", "P1", "P2"}
VIEWPORT = {"1440x900", "1280x800", "1920x1080", "390x844"}

# 第 5 段必须是业务规则、第 6 段必须是状态与流转（顺序固定，不允许换）
SECTION_PLAN = [
    (1, "定位"),
    (2, "业务背景与典型场景"),
    (3, "主流程"),
    (4, "字段字典与约束"),
    (5, "业务规则"),
    (6, "状态与流转"),
    (7, "异常与边界"),
    (8, "待确认"),
]

SCHEMA = {
    "type": "object",
    "required": ["schema", "engine", "meta", "sources", "sections",
                 "rules", "transitions", "apis", "questions", "dialogs",
                 "context", "entities", "layout", "prototype", "facts"],
    "additionalProperties": False,
    "properties": {
        "schema": {"type": "string", "const": SCHEMA_ID},
        "engine": {"type": "string", "const": ENGINE,
                   "hint": "生成器版本。合并全量 PRD 时要求全员一致，防止有人用旧版 skill"},
        "meta": {
            "type": "object",
            "required": ["key", "module", "menu", "route", "system", "env", "date", "version"],
            "additionalProperties": False,
            "properties": {
                "key": {"type": "string", "pattern": r"^[a-z][a-z0-9\-]{2,40}$",
                        "hint": "全局唯一模块 key，如 ops-person-field。合并时用它排序与去重"},
                "system": {"type": "string", "enum": ["管理后台", "主办方端", "报名者端"]},
                "module": {"type": "string", "minLength": 2, "hint": "模块名，如 报名字段配置"},
                "menu": {"type": "string", "minLength": 2, "hint": "三级菜单全路径，如 报名管理 / 报名字段配置"},
                "route": {"type": "string", "minLength": 3},
                "env": {"type": "string", "minLength": 3, "hint": "必须写明是测试环境"},
                "customer": {"type": "string"},
                "date": {"type": "string", "pattern": r"^\d{4}-\d{2}-\d{2}$"},
                "version": {"type": "string", "minLength": 2},
                # 同一稿内的修订序号。修订不推稿次——改的是表达与证据，不是业务结论；
                # 一旦推成新稿，读者会以为又多了一版需求。但它必须在三处一致：
                # meta.version 的「（修订 N）」、meta.rev、产物文件名的「-修订N」。
                "rev": {"type": "integer", "minimum": 1, "maximum": 99},
                "draft": {"type": "integer", "minimum": 1,
                          "hint": "本稿稿次（整数）。改动编号是累积的，没有它分不出「本稿改的」和「前几稿累积的」"},
                "owner": {"type": "string", "hint": "负责人，团队协作时用于回溯"},
            },
        },
        "sources": {
            "type": "array", "minItems": 6, "maxItems": 6,
            "hint": "六源必须齐全（浏览器渲染/后端接口/前端代码/后端代码/用例库/业务确认），顺序不限",
            "items": {
                "type": "object",
                "required": ["name", "status", "detail"],
                "additionalProperties": False,
                "properties": {
                    "name": {"type": "string", "minLength": 2},
                    "status": {"type": "string", "enum": sorted(SRC_STATUS)},
                    "detail": {"type": "string", "minLength": 8,
                               "hint": "写清核了什么、拿到什么数字。只写「已核」不算"},
                },
            },
        },
        "sections": {
            "type": "array", "minItems": 8, "maxItems": 8,
            "hint": "固定 8 段，顺序不可改；第 5 段 rules / 第 6 段 statemachine 由数据渲染，html 留空",
            "items": {
                "type": "object",
                "required": ["n", "title", "html"],
                "additionalProperties": False,
                "properties": {
                    "n": {"type": "integer"},
                    "title": {"type": "string", "minLength": 2},
                    "sub": {"type": "string"},
                    "html": {"type": "string"},
                    "rules": {"type": "boolean"},
                    "statemachine": {"type": "boolean"},
                },
            },
        },
        "context": {"type": "string", "minLength": 20,
                    "hint": "YAML 文本：为什么这样设计。防止 AI 做错误优化"},
        "entities": {"type": "string", "minLength": 20,
                     "hint": "YAML 文本：实体、字段、枚举、状态"},
        "rules": {
            "type": "array", "minItems": 1,
            "items": {
                "type": "object",
                "required": ["id", "type", "confidence", "src", "statement", "evidence", "cases"],
                "additionalProperties": False,
                "properties": {
                    "id": {"type": "string", "pattern": r"^R-[A-Z0-9]+-[A-Z0-9]+-\d{2}$",
                           "hint": "R-{系统}-{模块}-{序号}，如 R-OPS-FIELD-01"},
                    "type": {"type": "string", "enum": sorted(RULE_TYPE)},
                    "confidence": {"type": "string", "enum": sorted(CONF)},
                    "src": {"type": "array", "minItems": 1,
                            "items": {"type": "string", "enum": sorted(SRC)}},
                    "statement": {"type": "string", "minLength": 10,
                                  "hint": "一句话只讲一个命题，不用代词，不写「等」"},
                    "evidence": {"type": "string", "minLength": 6,
                                 "hint": "具体到接口/文件/用例标题，不写「实测」两字了事"},
                    "cases": {
                        "type": "array", "minItems": 1,
                        "items": {
                            "type": "object",
                            "required": ["k", "g", "w", "t"],
                            "additionalProperties": False,
                            "properties": {
                                "k": {"type": "string", "enum": sorted(CASE_KIND)},
                                "g": {"type": "string", "minLength": 4, "hint": "前置 given"},
                                "w": {"type": "string", "minLength": 2, "hint": "动作 when"},
                                "t": {"type": "string", "minLength": 4, "hint": "预期 then，必须可判定"},
                            },
                        },
                    },
                    "note": {"type": "string"},
                    "facts": {"type": "array", "items": {"type": "string"},
                              "hint": "这条规则的依据是哪几条 F-xx。填了叙事里就能点回核查"},
                },
            },
        },
        "transitions": {
            "type": "object",
            "required": ["states", "rows"],
            "additionalProperties": False,
            "properties": {
                "states": {"type": "array", "minItems": 2, "items": {"type": "string"}},
                "rows": {
                    "type": "array", "minItems": 1,
                    "items": {
                        "type": "object",
                        "required": ["id", "from", "to", "trigger", "guard", "label", "kind"],
                        "additionalProperties": False,
                        "properties": {
                            "id": {"type": "string", "pattern": r"^T\d+$"},
                            "from": {"type": "string"},
                            "to": {"type": "string"},
                            "trigger": {"type": "string", "minLength": 2},
                            "guard": {"type": "string"},
                            "label": {"type": "string", "minLength": 2, "hint": "图上标的字，≤8 字最好"},
                            "kind": {"type": "string", "enum": sorted(TRANS_KIND)},
                            "api": {"type": "string"},
                        },
                    },
                },
                "caption": {"type": "string"},
                "confidence": {"type": "string"},
                "note": {"type": "string"},
            },
        },
        "apis": {
            "type": "array", "minItems": 1,
            "items": {
                "type": "object",
                "required": ["method", "path", "purpose", "auth", "evidence"],
                "additionalProperties": False,
                "properties": {
                    "method": {"type": "string", "enum": ["GET", "POST", "PUT", "DELETE"]},
                    "path": {"type": "string", "minLength": 4},
                    "purpose": {"type": "string", "minLength": 2},
                    "auth": {"type": "string", "minLength": 2},
                    "evidence": {"type": "string", "minLength": 4},
                },
            },
        },
        "questions": {
            "type": "array", "minItems": 1,
            "hint": "至少一条。一条都没有，通常意味着核查不够深",
            "items": {
                "type": "object",
                "required": ["id", "title", "why", "ask"],
                "additionalProperties": False,
                "properties": {
                    "id": {"type": "string", "pattern": r"^Q-\d{2}$"},
                    "title": {"type": "string", "minLength": 4},
                    "why": {"type": "string", "minLength": 10},
                    "ask": {"type": "string", "minLength": 4},
                    "status": {"type": "string", "enum": ["open", "answered"],
                               "hint": "闸门 2 通过后，被回答的题要改成 answered 并补 answer"},
                    "answer": {"type": "string"},
                },
            },
        },
        "dialogs": {
            "type": "array", "minItems": 1,
            "hint": "本模块下的二级页/弹窗/抽屉。一个没有，说明边界没探清",
            "items": {
                "type": "object",
                "required": ["type", "name", "entry", "route", "covered"],
                "additionalProperties": False,
                "properties": {
                    "type": {"type": "string", "enum": sorted(DLG_TYPE)},
                    "name": {"type": "string", "minLength": 2},
                    "entry": {"type": "string", "minLength": 2},
                    "route": {"type": "string"},
                    "covered": {"type": "boolean"},
                },
            },
        },
        "layout": {"type": "string", "minLength": 10,
                   "hint": "界面结构（列数、控件顺序、尺寸），AI 写代码时缺这段会自己编布局"},

        # ---------------- ① 原型 ----------------
        "prototype": {
            "type": "object",
            "required": ["viewport", "frames"],
            "additionalProperties": False,
            "hint": "本模块的原型帧。主页面 + 每个弹窗/二级页各一帧，缺了等于没画",
            "properties": {
                "viewport": {"type": "string", "enum": sorted(VIEWPORT),
                             "hint": "设计尺寸。后台统一 1440x900，手机端 390x844"},
                "note": {"type": "string"},
                "frames": {
                    "type": "array", "minItems": 1,
                    "hint": "至少 1 帧：主页面。有弹窗/二级页的，每个再补一帧",
                    "items": {
                        "type": "object",
                        "required": ["id", "name", "html"],
                        "additionalProperties": False,
                        "properties": {
                            "id": {"type": "string", "pattern": r"^P\d{1,2}$",
                                   "hint": "P1 主页面、P2 新增、P3 弹窗……页签按这个顺序排"},
                            "name": {"type": "string", "minLength": 2,
                                     "hint": "页面态名，如 字段列表 / 新增字段"},
                            "state": {"type": "string",
                                      "hint": "这个态是什么：默认态 / 空态 / 校验失败 / 弹窗打开"},
                            "route": {"type": "string"},
                            "from": {"type": "string",
                                     "hint": "这帧的实拍来源：snapshot/<key>.json#p1。"
                                             "填了就必须有对应快照和截图，"
                                             "验收会查——这是「不许凭印象画」的凭据"},
                            "note": {"type": "string",
                                     "hint": "看图时必须交代的事：哪些是示例数据、哪里被裁掉了"},
                            "html": {"type": "string", "minLength": 20,
                                     "hint": "原型 HTML 片段。只用 px- 组件 class，不写 style，"
                                             "否则每个人画出来都不一样"},
                        },
                    },
                },
            },
        },

        # ---------------- ④ 核查 ----------------
        # ---- 以下两块是 v6.0 新增：文档分栏后，用例与代码各归各位 ----
        # 为什么不再塞进叙事：读者是三类人（业务 / 测试 / 研发），
        # 原来把三套语言混在一段里，谁都读不顺。分开以后正文只剩业务语言。
        "testcases": {
            "type": "array",
            "hint": "测试用例规整。从 用例库库取回后统一成一种形态，一条一个功能点，"
                    "标出它验证的是哪条业务规则。没有就留空数组，别编",
            "items": {
                "type": "object",
                "required": ["id", "group", "title", "pre", "steps", "expect"],
                "additionalProperties": False,
                "properties": {
                    "id": {"type": "string", "minLength": 3,
                           "hint": "沿用用例库编号（如 TC-WDR-012）；没有编号就用 TC-<模块缩写>-序号"},
                    "group": {"type": "string", "minLength": 2,
                              "hint": "功能点分组：列表 / 筛选 / 详情 / 导出 …，同一组排在一起"},
                    "title": {"type": "string", "minLength": 4, "hint": "这条用例验什么，一句话"},
                    "pre": {"type": "string", "hint": "前提：什么数据、什么账号、什么状态；没有写「无」"},
                    "steps": {"type": "array", "minItems": 1, "items": {"type": "string"},
                              "hint": "操作步骤，一步一句，不夹断言"},
                    "expect": {"type": "string", "minLength": 4,
                               "hint": "预期结果，必须可判定（看到什么、变成什么状态）"},
                    "rules": {"type": "array", "items": {"type": "string"},
                              "hint": "这条用例守的是哪几条 R-xxx。填了就能从规则点过来"},
                    "norule": {"type": "string",
                               "hint": "确实没有对应规则时写为什么（如「页面通用行为：筛选与分页」）。"
                                       "空着不写会被门禁当成漏挂"},
                    "src": {"type": "string", "hint": "用例来源：用例库 / 业务口述 / 本次补写"},
                    "gap": {"type": "string",
                            "hint": "用例与现状不一致、或本次改动后必须重写的地方，写在这里"},
                },
            },
        },
        "code": {
            "type": "object",
            "hint": "代码逻辑。上半段用大白话讲「这个数谁算的、什么时候算、失败会怎样」，"
                    "下半段给研发的对照（页面 → 组件 → 接口 → 字段）。两块都要，"
                    "因为业务方看上半段就能判断对不对，研发看下半段就能动手",
            "additionalProperties": False,
            "properties": {
                "plain": {
                    "type": "array", "minItems": 1,
                    "hint": "大白话段：一段一件事，说清「谁算的 / 什么时候算 / 算不出来怎么办」",
                    "items": {
                        "type": "object",
                        "required": ["q", "a"],
                        "additionalProperties": False,
                        "properties": {
                            "q": {"type": "string", "minLength": 4,
                                  "hint": "业务方真的会问的那句话：这个金额是谁算的？"},
                            "a": {"type": "string", "minLength": 8, "hint": "大白话回答，不用技术词"},
                        },
                    },
                },
                "fe": {
                    "type": "array",
                    "hint": "前端对照：页面 / 组件 / 取数 / 校验时机",
                    "items": {
                        "type": "object",
                        "required": ["where", "what"],
                        "additionalProperties": False,
                        "properties": {
                            "where": {"type": "string", "minLength": 2, "hint": "页面或组件位置"},
                            "what": {"type": "string", "minLength": 4, "hint": "这个位置做什么、数据从哪来"},
                            "path": {"type": "string", "hint": "文件或路由，可留空"},
                        },
                    },
                },
                "be": {
                    "type": "array",
                    "hint": "后端对照：接口 / 表 / 关键判断",
                    "items": {
                        "type": "object",
                        "required": ["where", "what"],
                        "additionalProperties": False,
                        "properties": {
                            "where": {"type": "string", "minLength": 2, "hint": "接口或表名"},
                            "what": {"type": "string", "minLength": 4, "hint": "它做什么、返回什么判定"},
                            "path": {"type": "string", "hint": "代码位置，可留空"},
                        },
                    },
                },
                "notes": {"type": "array", "items": {"type": "string"},
                          "hint": "技术侧遗留风险：并发、超时、精度… 一条一句"},
            },
        },

        "facts": {
            "type": "array", "minItems": 1,
            "hint": "五源事实清单。正文每条规则的 facts 都指向这里；没有这张表，结论就追不到来源",
            "items": {
                "type": "object",
                "required": ["id", "title", "area", "cls", "sev", "src", "now"],
                "additionalProperties": False,
                "properties": {
                    "id": {"type": "string", "pattern": r"^(F|Q)-\d{2}$",
                           "hint": "F-xx 是观察到的事实，Q-xx 是要人回答的问题；两者同表并列"},
                    "title": {"type": "string", "minLength": 4,
                              "hint": "一句话说清这条事实是什么，不要写「关于xx的问题」"},
                    "area": {"type": "string", "minLength": 2, "hint": "归属对象：字段类型 / 校验 / 权限…"},
                    "cls": {"type": "string", "enum": sorted(FACT_CLS),
                            "hint": "fix 现有写法要改 / add 漏了要补 / conflict 多源打架 / "
                                    "risk 有隐患 / ask 要裁定 / ok 核过一致"},
                    "sev": {"type": "string", "enum": sorted(FACT_SEV),
                            "hint": "P0 不裁定就没法开工；P1 影响写法；P2 表述优化"},
                    "src": {"type": "array", "minItems": 1,
                            "items": {"type": "string", "enum": sorted(SRC)},
                            "hint": "这条事实是哪个源给的。至少一个，别写「综合」"},
                    "old": {"type": "string", "hint": "原说法。cls=miss 时可空"},
                    "now": {"type": "string", "minLength": 8,
                            "hint": "实际是什么。写到能直接抄进正文的程度"},
                    "note": {"type": "string", "hint": "判断：为什么信这个、冲突在哪"},
                    "ask": {"type": "string", "hint": "要业务方定什么。P0 必填"},
                    "evidence": {"type": "string",
                                 "hint": "证据原文：接口路径+返回、文件+行号、用例标题"},
                    "rules": {"type": "array", "items": {"type": "string"},
                              "hint": "这条事实影响了哪些规则编号"},
                },
            },
        },
    },
}


# ---------------------------------------------------------------- 校验器

class Errors(list):
    def add(self, path, msg, hint=""):
        self.append({"path": path, "msg": msg, "hint": hint})


def _fmt(path):
    return path or "(根)"


def _check(node, sch, path, errs):
    t = sch.get("type")
    hint = sch.get("hint", "")

    if "const" in sch:
        if node != sch["const"]:
            errs.add(path, "必须是 %r，实际 %r" % (sch["const"], node), hint)
            return

    if t == "object":
        if not isinstance(node, dict):
            errs.add(path, "应该是对象，实际是 %s" % type(node).__name__, hint)
            return
        for k in sch.get("required", []):
            if k not in node:
                errs.add(path + "." + k, "缺少必填字段", hint)
        props = sch.get("properties", {})
        if sch.get("additionalProperties") is False:
            for k in node:
                if k not in props:
                    errs.add(path + "." + k, "不允许的字段（契约里没这个字段，别自己加）")
        for k, v in node.items():
            if k in props:
                _check(v, props[k], path + "." + k, errs)

    elif t == "array":
        if not isinstance(node, list):
            errs.add(path, "应该是数组，实际是 %s" % type(node).__name__, hint)
            return
        n = len(node)
        if "minItems" in sch and n < sch["minItems"]:
            errs.add(path, "至少 %d 项，实际 %d 项" % (sch["minItems"], n), hint)
        if "maxItems" in sch and n > sch["maxItems"]:
            errs.add(path, "最多 %d 项，实际 %d 项" % (sch["maxItems"], n), hint)
        if "items" in sch:
            for i, it in enumerate(node):
                _check(it, sch["items"], "%s[%d]" % (path, i), errs)

    elif t == "string":
        if not isinstance(node, str):
            errs.add(path, "应该是字符串，实际是 %s" % type(node).__name__, hint)
            return
        if "minLength" in sch and len(node.strip()) < sch["minLength"]:
            errs.add(path, "太短（%d < %d 字）" % (len(node.strip()), sch["minLength"]), hint)
        if "pattern" in sch and not re.match(sch["pattern"], node):
            errs.add(path, "格式不对：%r 不匹配 %s" % (node, sch["pattern"]), hint)
        if "enum" in sch and node not in sch["enum"]:
            errs.add(path, "%r 不在允许值内：%s" % (node, " / ".join(sch["enum"])), hint)

    elif t == "integer":
        if not isinstance(node, int) or isinstance(node, bool):
            errs.add(path, "应该是整数，实际 %r" % (node,), hint)

    elif t == "boolean":
        if not isinstance(node, bool):
            errs.add(path, "应该是 true/false，实际 %r" % (node,), hint)


def validate(data):
    """返回 Errors。空表示通过。"""
    errs = Errors()
    _check(data, SCHEMA, "", errs)
    if isinstance(data, dict) and not errs:
        errs.extend(_semantic(data))
    return errs


def _semantic(d):
    """结构合法之后的业务校验——这些是 schema 表达不了的，也是团队最容易偷懒的地方。"""
    e = Errors()

    # 1. 段序固定
    for (n, title), sec in zip(SECTION_PLAN, d.get("sections") or []):
        if sec.get("n") != n:
            e.add("sections[%d].n" % (n - 1), "第 %d 段编号应为 %d，实际 %r" % (n - 1, n, sec.get("n")))
        if sec.get("title") != title:
            e.add("sections[%d].title" % (n - 1),
                  "第 %d 段标题应为「%s」，实际「%s」" % (n, title, sec.get("title")),
                  "8 段顺序与标题是固定的，不允许改")

    # 2. 第 5 段必须由 rules 渲染、第 6 段由状态机渲染
    secs = d.get("sections") or []
    if len(secs) >= 6:
        if not secs[4].get("rules"):
            e.add("sections[4].rules", "第 5 段（业务规则）必须声明 rules:true，由规则数据渲染")
        if not secs[5].get("statemachine"):
            e.add("sections[5].statemachine", "第 6 段（状态与流转）必须声明 statemachine:true")
        for i in (4, 5):
            if (secs[i].get("html") or "").strip():
                e.add("sections[%d].html" % i, "这一段由数据渲染，html 必须留空", "手写会与规则数据不一致")

    # 3. 前 4 段、后 2 段必须有内容
    for i in (0, 1, 2, 3, 6, 7):
        if i < len(secs) and len((secs[i].get("html") or "").strip()) < 30:
            e.add("sections[%d].html" % i,
                  "第 %d 段内容太少（<30 字）" % (i + 1), "确实不涉及的，写「本期不涉及」并说明原因")

    # 4. 规则 id 唯一
    ids = [r.get("id") for r in d.get("rules") or []]
    dup = sorted({x for x in ids if ids.count(x) > 1})
    if dup:
        e.add("rules[].id", "规则编号重复：%s" % ", ".join(dup))

    # 5. 标了「互证」的必须真有 ≥2 源；单源不许自称互证
    for i, r in enumerate(d.get("rules") or []):
        c, src = r.get("confidence"), r.get("src") or []
        if c == "互证" and len(set(src)) < 2:
            e.add("rules[%d].confidence" % i,
                  "%s 标互证但只有 %d 个来源" % (r.get("id"), len(set(src))),
                  "互证=至少两个独立来源说法一致")
        if c == "双证" and len(set(src)) < 2:
            e.add("rules[%d].confidence" % i, "%s 标双证但只有 1 个来源" % r.get("id"))
        if c == "确立" and "biz" not in src:
            e.add("rules[%d].confidence" % i,
                  "%s 标「确立」但没有业务确认来源" % r.get("id"),
                  "只有业务方当面裁定的事实才能标确立")

    # 6. 状态机的 from/to 必须在 states 里
    tr = d.get("transitions") or {}
    states = set(tr.get("states") or [])
    for i, row in enumerate(tr.get("rows") or []):
        for side in ("from", "to"):
            if row.get(side) not in states:
                e.add("transitions.rows[%d].%s" % (i, side),
                      "%r 不在 states 列表里" % row.get(side),
                      "states 与 rows 必须互相闭合，否则图上会画出孤立节点")

    # 7. 主页面必须被覆盖（弹窗可以留缺口，但主页面不行）
    dl = d.get("dialogs") or []
    main_unc = [x.get("name") for x in dl
                if not x.get("covered") and x.get("type") == "二级页"]
    if main_unc and len(main_unc) == len([x for x in dl if x.get("type") == "二级页"]):
        e.add("dialogs", "所有二级页都标了未覆盖", "主页面至少要被本 PRD 覆盖")

    # 注：六源「已核」数量属于流程进度，由 check_delivery.py 把关，不在这里拦。
    # 否则骨架数据连预览图都构建不出来，同事看不到目标形态。

    # 9. 待确认条目被回答过的要留痕
    for i, q in enumerate(d.get("questions") or []):
        if q.get("status") == "answered" and len((q.get("answer") or "").strip()) < 4:
            e.add("questions[%d].answer" % i, "%s 标了已答但没写答案" % q.get("id"))

    # 10. 原型帧
    pf = (d.get("prototype") or {}).get("frames") or []
    pids = [x.get("id") for x in pf]
    dup = sorted({x for x in pids if pids.count(x) > 1})
    if dup:
        e.add("prototype.frames[].id", "原型帧编号重复：%s" % ", ".join(dup))
    for i, f in enumerate(pf):
        if len((f.get("html") or "").strip()) < 20:
            e.add("prototype.frames[%d].html" % i,
                  "%s 的 html 是空的" % f.get("id"),
                  "有帧没内容等于没画；本模块真的没有这一态就删掉这帧")
        elif "style=" in (f.get("html") or ""):
            e.add("prototype.frames[%d].html" % i,
                  "%s 里写了内联 style" % f.get("id"),
                  "原型只允许用 px- 组件 class，写内联样式会让每个人画出来都不一样")
        # from 是实拍凭据，格式必须是 <文件>.json#<页号>
        if f.get("from") and not re.match(r"^[\w.\-]+\.json#p\d{1,3}$", f["from"]):
            e.add("prototype.frames[%d].from" % i,
                  "%s 的 from 格式不对：%r" % (f.get("id"), f["from"]),
                  "应写成 snapshot/<key>.json#p1 —— 指向这次实拍的快照与页号")

    # 11. 事实清单：P0 必须说清要定什么
    fts = d.get("facts") or []
    fids = [x.get("id") for x in fts]
    dupf = sorted({x for x in fids if fids.count(x) > 1})
    if dupf:
        e.add("facts[].id", "事实编号重复：%s" % ", ".join(dupf))
    for i, f in enumerate(fts):
        # P0 的作用是「不裁定开不了工」，所以没裁定就要写清问什么。
        # 但 cls=fix 且 now 已经写明白「改成什么」的，是**已裁定**——它没有要问的，
        # 硬要求 ask 只会逼人写一句「无」来糊弄门禁，门禁就退化成格式检查。
        decided = (f.get("cls") == "fix" and len((f.get("now") or "").strip()) >= 10)
        if f.get("sev") == "P0" and not decided and len((f.get("ask") or "").strip()) < 4:
            e.add("facts[%d].ask" % i, "%s 是 P0 但没写要业务方定什么" % f.get("id"),
                  "P0 不裁定就开不了工，必须写清问什么；如果已经定了，用 cls=fix 并把改成什么写进 now")
        if f.get("cls") == "ask" and len((f.get("ask") or "").strip()) < 4:
            e.add("facts[%d].ask" % i, "%s 标了待定但没写要定什么" % f.get("id"))
        if f.get("cls") == "fix" and len((f.get("old") or "").strip()) < 4:
            e.add("facts[%d].old" % i, "%s 标了需改但没写原说法" % f.get("id"),
                  "「需改」必须写出原来错在哪，否则改完无法复核")
        if f.get("cls") == "conflict" and len((f.get("old") or "").strip()) < 4:
            e.add("facts[%d].old" % i, "%s 标了冲突但没写冲突的另一方说法" % f.get("id"),
                  "冲突条目必须两边都写出来")

    # 12. 规则 ↔ 事实 双向引用必须闭合，否则页面上点了跳空
    rules = d.get("rules") or []
    rid_set = {r.get("id") for r in rules}
    fid_set = set(fids)
    for i, f in enumerate(fts):
        for x in f.get("rules") or []:
            if x not in rid_set:
                e.add("facts[%d].rules" % i, "%s 引用了不存在的规则 %s" % (f.get("id"), x))
    for i, r in enumerate(rules):
        for x in r.get("facts") or []:
            if x not in fid_set:
                e.add("rules[%d].facts" % i, "%s 引用了不存在的事实 %s" % (r.get("id"), x))

    # 13. 命名规范：产品版本用 V，稿次用「第 N 稿」——两者不能共用一个 V
    #     这条是硬门禁，不是提醒。历史上出现过「管理后台 5.0 · V10.1」这种写法，
    #     读起来像「5.0 的第十个子版本」，实际 V10.1 只是文档改到第 10 稿。
    _check_naming(d, e)

    # 14. 改动标注必须带稿次
    #     编号是全局累积的（C1…C23 横跨十几稿）。没有稿次，读者看到「20 处改动」
    #     会理解成「这一稿改了 20 处」，实际本稿只改了 3 处——这是被业务方
    #     当场指出的错读，所以做成门禁而不是建议。
    _check_chg_draft(d, e)

    return e


CHG_TAG_RE = re.compile(r"<[^>]*\bdata-chg=\"(C\d{1,3})\"[^>]*>")


def _chg_scopes(d):
    """所有可能出现改动标注的 HTML 片段：(说明, 字符串)"""
    out = []
    for i, s in enumerate(d.get("sections") or []):
        if s.get("html"):
            out.append(("sections[%d].html（第 %s 段）" % (i, s.get("n")), s["html"]))
    for i, f in enumerate((d.get("prototype") or {}).get("frames") or []):
        if f.get("html"):
            out.append(("prototype.frames[%d].html（%s）" % (i, f.get("id")), f["html"]))
    return out


def _check_chg_draft(d, e):
    """改动标注三件事：meta.draft 要和版本一致、每条标注要带稿次、稿次不能超过本稿。"""
    meta = d.get("meta") or {}
    draft = meta.get("draft")
    m = re.search(r"第 (\d{1,2}) 稿", meta.get("version") or "")
    if not m:
        return                      # 版本没写稿次（现状 PRD），不做改动稿次校验
    cur = int(m.group(1))

    if draft is None:
        e.add("meta.draft",
              "meta 没有 draft，读的人分不出「本稿改的」和「前几稿累积的」",
              "meta.draft 写本稿稿次（整数 %d），与 version 里的「第 %d 稿」一致" % (cur, cur))
        return
    if int(draft) != cur:
        e.add("meta.draft",
              "meta.draft=%s 与 version 里的「第 %d 稿」不一致" % (draft, cur),
              "两个数字必须相等，否则同一页会出现两套稿次")

    bad_noattr, bad_over = [], []
    seen_drafts = {}
    for where, html in _chg_scopes(d):
        for tag in CHG_TAG_RE.finditer(html):
            code = tag.group(1)
            t = tag.group(0)
            dm = re.search(r'data-draft="(\d{1,2})"', t)
            if not dm:
                bad_noattr.append("%s %s" % (code, where))
            else:
                seen_drafts.setdefault(code, {}).setdefault(int(dm.group(1)), []).append(where)
                if int(dm.group(1)) > int(draft):
                    bad_over.append("%s 标 data-draft=%s，超过本稿 %s" % (code, dm.group(1), draft))

    if bad_noattr:
        e.add("data-draft",
              "有 %d 处改动标注没写稿次（%s）" % (len(bad_noattr), "、".join(bad_noattr[:4])),
              "每个带 data-chg 的元素都要写 data-draft=\"本稿稿次\"。"
              "不写就分不出这一处是本稿改的还是前几稿累积的")
    if bad_over:
        e.add("data-draft",
              "有 %d 处稿次超过本稿（%s）" % (len(bad_over), "；".join(bad_over[:3])),
              "标注只能是这一稿或更早的改动，写成未来稿次说明稿次算错了")

    # 同一编号只能有一个稿次。原型标 9 稿、叙事标 13 稿，读者会以为这是两件事
    mixed = {k: sorted(v) for k, v in seen_drafts.items() if len(v) > 1}
    if mixed:
        k = sorted(mixed)[0]
        e.add("data-draft",
              "%s 在不同位置标了 %s 个稿次：%s"
              % (k, len(mixed[k]), "、".join("第 %d 稿" % x for x in mixed[k])),
              "同一处改动只能属于一稿。后续又改了它，就把所有标注一起改成新稿次")


# 产品版本 + 稿次的三段式。产品版本可以是任意 Vn.m（后台会换版），稿次必须是「第 N 稿」
VERSION_PAT = re.compile(r"^\S.{0,23} V\d{1,2}\.\d{1,2} · .+ · 第 \d{1,2} 稿(（修订 \d{1,2}）)?$")
VER_RE = re.compile(r"V(\d{1,2})\.(\d{1,2})")


def _check_naming(d, e):
    """命名门禁：Vn.m 只能表示产品版本，文档稿次一律写「第 N 稿」。"""
    meta = d.get("meta") or {}
    ver = (meta.get("version") or "").strip()
    if ver and not VERSION_PAT.match(ver):
        e.add("meta.version",
              "版本写法不合规：%r" % ver,
              "必须写成「管理后台 V5.0 · <需求名> · 第 N 稿」——产品版本用 V，稿次用「第 N 稿」，"
              "不要把稿次也写成 V10.1")

    # 修订序号必须三处一致：version 里的「（修订 N）」、meta.rev、产物文件名。
    # 只在标题里写「修订 1」而 rev 空着，下一个脚本读 rev 就以为没修订过；
    # 反过来 rev=1 而标题没写，读者从标题看不出这是修订版。
    rev_m = re.search(r"（修订 (\d{1,2})）", ver)
    ver_rev = int(rev_m.group(1)) if rev_m else None
    meta_rev = meta.get("rev")
    if ver_rev is not None and not meta_rev:
        e.add("meta.rev", "版本号写着「（修订 %d）」，meta.rev 却是空的" % ver_rev,
              "补 \"rev\": %d。修订序号要能被脚本读到，不能只写在标题里" % ver_rev)
    elif meta_rev and ver_rev is None:
        e.add("meta.version", "meta.rev = %s，版本号里却没写「（修订 %s）」" % (meta_rev, meta_rev),
              "标题与字段必须一致，否则文件名、run.json、正文三处会各说一套")
    elif ver_rev is not None and meta_rev and int(meta_rev) != ver_rev:
        e.add("meta.rev", "修订序号对不上：版本号写 %d，meta.rev 写 %s" % (ver_rev, meta_rev),
              "改成同一个数")

    # 允许出现的 Vn.m：meta.version 里的产品版本号（如 V5.0）。
    # 产品换版时这里自动跟着走，不需要改代码。
    allowed = set()
    mm = re.match(r"^管理后台 (V\d{1,2}\.\d{1,2})", ver)
    if mm:
        allowed.add(mm.group(1))
    allowed.add("V5.0")   # 当前产品版本，兼容还没改到三段式的老模块

    hits, doubled = [], []
    def walk(o, path):
        if isinstance(o, dict):
            for k, v in o.items():
                walk(v, "%s.%s" % (path, k))
        elif isinstance(o, list):
            for i, v in enumerate(o):
                walk(v, "%s[%d]" % (path, i))
        elif isinstance(o, str):
            if re.search(r"VV\d", o):
                doubled.append((path, re.search(r"VV\d[\d.]*", o).group(0)))
            for m in VER_RE.finditer(o):
                if m.group(0) in allowed:
                    continue
                hits.append((path, m.group(0)))
    walk(d, "")

    if doubled:
        p, tok = doubled[0]
        e.add((p or "meta.version").lstrip("."),
              "版本号写重复了：%r（%d 处）" % (tok, len(doubled)),
              "批量替换容易把 V 加两次，出现 VV5.0 这种")
    if hits:
        p, _ = hits[0]
        sample = "；".join(sorted({t for _, t in hits})[:5])
        e.add((p or "meta.version").lstrip("."),
              "有 %d 处把稿次写成了 V 版本号（%s）" % (len(hits), sample),
              "稿次一律写「第 N 稿」；只有产品版本能写 V5.0。"
              "这一条是门禁：出现在正文里同样会打回，不只是 meta.version")



def fact_from_ledger(x):
    """把核查台账（facts/<key>.facts.json）里的一条，转成 PRD 渲染要的字段名。

    台账用 new / proof（沿用 facts_field.py 的历史字段名，改不动也不必改），
    PRD 数据用 now / evidence（读起来更准）。只在这一处做映射。
    """
    return {
        "id": x.get("id", ""),
        "title": x.get("title", ""),
        "area": x.get("area", ""),
        "cls": x.get("cls", "ok"),
        "sev": x.get("sev", "P2"),
        "src": list(x.get("src") or []),
        "old": x.get("old") or "",
        "now": x.get("now") or x.get("new") or "",
        "note": x.get("note") or "",
        "ask": x.get("ask") or "",
        "evidence": x.get("evidence") or x.get("proof") or "",
        "rules": list(x.get("rules") or []),
    }


def dump_schema(path):
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"$schema": "http://json-schema.org/draft-07/schema#",
                   "$id": SCHEMA_ID, "engine": ENGINE, **SCHEMA},
                  f, ensure_ascii=False, indent=2)
    return path


def print_errors(errs, limit=40):
    if not errs:
        return
    print("✗ 数据契约校验未通过，%d 处：" % len(errs))
    for x in errs[:limit]:
        print("  · %s" % _fmt(x["path"]))
        print("      %s" % x["msg"])
        if x.get("hint"):
            print("      → %s" % x["hint"])
    if len(errs) > limit:
        print("  … 还有 %d 处，先修上面这些" % (len(errs) - limit))


if __name__ == "__main__":
    import _compat as _c   # 控制台编码兜底（Windows 默认 cp936 编不出 ✓ ✗）
    _c.init()
    if "--dump" in sys.argv:
        i = sys.argv.index("--dump")
        out = sys.argv[i + 1]
        print("已导出 %s" % dump_schema(out))
        sys.exit(0)
    if "--check" in sys.argv:
        i = sys.argv.index("--check")
        p = sys.argv[i + 1]
        d = json.load(open(p, encoding="utf-8"))
        errs = validate(d)
        if errs:
            print_errors(errs)
            sys.exit(1)
        print("✓ %s 通过契约校验" % os.path.basename(p))
        sys.exit(0)
    print(__doc__)
