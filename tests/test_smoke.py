"""冒烟测试：示例能构建、契约成立、门禁真的会红。

跑法：python -m unittest discover -s tests -v

这组测试只锁两类东西：
  1. 示例本身合不合法（八段骨架、规则引用真实事实、改动标注带稿次、来源不空口核过）
  2. 门禁会不会真的响——造一份坏数据，断言构建必须失败

第二类比第一类重要。只验证「能过」不验证「能抓」，等于没做门禁。
"""
import copy
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "scripts")
EXAMPLE = os.path.join(ROOT, "assets", "example_module.json")


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def load(path):
    return json.loads(read(path))


def run(*args, cwd=ROOT):
    return subprocess.run(
        [sys.executable] + list(args),
        cwd=cwd, capture_output=True, text=True,
    )


def build(data_path, out):
    return run(os.path.join(SCRIPTS, "build_module_prd.py"),
               "--data", data_path, "--out", out, "--strict")


class ExampleBuilds(unittest.TestCase):
    def test_example_builds_strict(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "prd.html")
            r = build(EXAMPLE, out)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertTrue(os.path.getsize(out) > 100_000, "产物过小，渲染可能失败")
            html = read(out)
            # 单文件、离线可开：不允许任何外链
            self.assertNotRegex(html, r'<script[^>]+src=', "产物里有外链脚本")
            self.assertNotRegex(html, r'<link[^>]+href="http', "产物里有外链样式")
            # 四栏都在
            for lane in ("原型+文档", "测试用例", "代码逻辑", "核查"):
                self.assertIn(lane, html, "缺少栏目：%s" % lane)


class ContractHolds(unittest.TestCase):
    def setUp(self):
        self.data = load(EXAMPLE)

    def test_eight_sections_fixed(self):
        self.assertEqual([s["n"] for s in self.data["sections"]], list(range(1, 9)))

    def test_rules_cite_real_facts(self):
        ids = {f["id"] for f in self.data["facts"]}
        for r in self.data["rules"]:
            for ref in r.get("facts") or []:
                self.assertIn(ref, ids, "规则 %s 引用了不存在的事实 %s" % (r["id"], ref))

    def test_every_change_mark_has_draft(self):
        """改动标注必须带稿次。

        编号是跨稿累积的：一份走了十几稿的需求，C1…C23 里可能只有 3 处是这一稿改的。
        不带 data-draft，「本次改动 20 处」就会被读成「这一稿改了 20 处」。
        """
        for f in self.data["prototype"]["frames"]:
            for m in re.findall(r'data-chg="([^"]+)"', f["html"]):
                self.assertRegex(f["html"], r'data-chg="%s"[^>]*data-draft' % re.escape(m),
                                 "改动 %s 缺 data-draft" % m)

    def test_draft_matches_version(self):
        """meta.draft 必须等于 version 里的「第 N 稿」，两个数字打架就打回。"""
        m = re.search(r"第\s*(\d+)\s*稿", self.data["meta"]["version"])
        self.assertIsNotNone(m, "meta.version 里没有「第 N 稿」")
        self.assertEqual(int(m.group(1)), self.data["meta"]["draft"],
                         "meta.draft 与 version 里的稿次不一致")

    def test_sources_never_claim_without_evidence(self):
        """标「已核」却没写核到什么，等于空口核过。"""
        for s in self.data["sources"]:
            if s.get("status") == "已核":
                self.assertTrue((s.get("detail") or "").strip(),
                                "来源「%s」标了已核但 detail 是空的" % s.get("name"))

    def test_frames_declare_known_kind(self):
        """帧类型只能是 ui / flow / diagram / explain，写错会静默影响渲染与检查范围。"""
        for f in self.data["prototype"]["frames"]:
            self.assertIn(f.get("kind", "ui"), ("ui", "flow", "diagram", "explain"),
                          "帧「%s」的 kind 不认识" % f.get("name"))

    def test_sample_has_no_real_looking_identifiers(self):
        """示例里不该出现真实形态的标识：长数字机构 ID、具体域名、真实单据号。

        这里故意**不列禁用词**。早先那版是照着词表逐个 assertNotIn 的，
        结果等于把「哪些词是敏感的」明明白白写进了公开仓库——为了防泄露，
        自己造了一处泄露。脱敏是发布流程的职责，有词表和门禁管；
        公开仓库里的测试只该检查形态，不该复述清单。
        """
        raw = read(EXAMPLE)
        self.assertNotRegex(raw, r"\b\d{15,}\b", "示例里有像真实机构 ID 的长数字串")
        self.assertNotRegex(raw, r"\bCK\d{8,}\b", "示例里有像真实单据号的编号")
        self.assertIn(self.data["meta"]["system"], ("管理后台", "机构端", "学员端"))


class GatesActuallyBite(unittest.TestCase):
    """门禁只验证「能过」不验证「能抓」，等于没做。这里造坏数据，确认它会红。"""

    def _build_bad(self, mutate):
        data = copy.deepcopy(load(EXAMPLE))
        mutate(data)
        with tempfile.TemporaryDirectory() as tmp:
            bad = os.path.join(tmp, "bad.json")
            with open(bad, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
            return build(bad, os.path.join(tmp, "x.html"))

    def test_breaks_when_rule_cites_missing_fact(self):
        def mutate(d):
            d["rules"][0].setdefault("facts", []).append("F-999")
        r = self._build_bad(mutate)
        self.assertNotEqual(r.returncode, 0, "规则引用了不存在的事实，构建居然通过了")
        self.assertIn("F-999", r.stdout + r.stderr)

    def test_breaks_when_draft_missing(self):
        """现状稿本来就没有改动标注，所以这里主动造一个「标了改动但不带稿次」的帧。

        直接删 data-draft 是测不出东西的：示例里没有 data-chg，删了等于没删，
        构建照过，看着像门禁失效，其实是造的数据不成立。
        """
        def mutate(d):
            f = d["prototype"]["frames"][0]
            f["html"] = ('<span class="chg-flag" data-chg="C1">改①</span>'
                         + f["html"])
        r = self._build_bad(mutate)
        self.assertNotEqual(r.returncode, 0,
                            "标了改动却没写稿次，构建居然通过了")
        self.assertIn("data-draft", r.stdout + r.stderr)

    def test_breaks_when_section_dropped(self):
        def mutate(d):
            d["sections"].pop()
        r = self._build_bad(mutate)
        self.assertNotEqual(r.returncode, 0, "少了整整一段，构建居然通过了")


if __name__ == "__main__":
    unittest.main()
