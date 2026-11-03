"""冒烟测试：示例数据能构建、门禁会红、模板无外链。

跑法：python -m unittest discover -s tests -v
"""
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


class ExampleBuilds(unittest.TestCase):
    def test_example_builds_strict(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "prd.html")
            r = run(os.path.join(SCRIPTS, "build_module_prd.py"),
                    "--data", EXAMPLE, "--out", out, "--strict")
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
        for f in self.data["prototype"]["frames"]:
            for m in re.findall(r'data-chg="([^"]+)"', f["html"]):
                self.assertRegex(f["html"], r'data-chg="%s"[^>]*data-draft' % re.escape(m),
                                 "改动 %s 缺 data-draft" % m)

    def test_sample_stays_fictional(self):
        """示例必须是虚构业务域：不给读者留下可在现实中定位的线索。"""
        raw = read(EXAMPLE)
        self.assertEqual(self.data["meta"]["system"], "管理后台")
        for marker in ("主办方", "报名者", "票种"):
            self.assertIn(marker, raw, "示例缺虚构域标记：%s" % marker)


class GatesActuallyBite(unittest.TestCase):
    """门禁只验证「能过」不验证「能抓」，等于没做。这里造坏数据，确认它会红。"""

    def test_breaks_when_rule_cites_missing_fact(self):
        import copy
        data = copy.deepcopy(load(EXAMPLE))
        data["rules"][0].setdefault("facts", []).append("F-999")
        with tempfile.TemporaryDirectory() as tmp:
            bad = os.path.join(tmp, "bad.json")
            with open(bad, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
            r = run(os.path.join(SCRIPTS, "build_module_prd.py"),
                    "--data", bad, "--out", os.path.join(tmp, "x.html"), "--strict")
            self.assertNotEqual(r.returncode, 0, "规则引用了不存在的事实，构建居然通过了")
            self.assertIn("F-999", r.stdout + r.stderr)


class IterationDraft(unittest.TestCase):
    """迭代版示例：必须能构建，且改动标注必须带稿次。"""

    def test_iteration_builds_and_marks_changes(self):
        path = os.path.join(ROOT, "assets", "example_iteration.json")
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "d2.html")
            r = run(os.path.join(SCRIPTS, "build_module_prd.py"),
                    "--data", path, "--out", out, "--strict")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            html = read(out)
            self.assertIn("第 2 稿", html, "迭代版没有稿次")
            self.assertGreaterEqual(html.count("data-chg="), 2, "改动标注少于 2 处")
            self.assertIn("chg-col", html, "列级改动没有被渲染")


if __name__ == "__main__":
    unittest.main()
