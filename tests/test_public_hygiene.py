# -*- coding: utf-8 -*-
"""公开仓库的内容卫生：内部标识、凭据、本机路径，一个都不该出现。

为什么做成测试而不是检查脚本：CI 每次 push / PR 都会跑，人不用记得执行。
踩过一次——示例命令里写了真实系统的 host 和路由名，`git log -p` 全能翻到。

加词之前先问一句：这是不是只有我们内部才这么叫？
是，就加进来；只是通用英文词（admin、list、person），别加，会误伤。
"""

import base64
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 内部标识：公司名、系统名、内部仓库名、内部存储键。
# 内部标识：公司名、系统名、内部仓库名、内部存储键。
# 刻意存成 base64：明文列出来等于把要挡的词又公开一遍，等于没挡。
# 跑的时候解回明文拼正则，功能完全一样。
_DENY_B64 = [
    "Z2VvYWRtaW4=",   # 内部运营后台的 host 前缀
    "Z2VvLWJhY2tzdGFnZQ==",   # 内部后端仓库名
    "am95b3dv",   # 母公司英文名
    "eW91Y2h1aGFp",   # 海外业务主体名
    "6YeR5p+a",   # 公司中文名
    "5LuK5YWD",   # 集团中文名
    "YWlyd2FsbGV4",   # 跨境支付服务商
    "aWNccz9wYXlsaW5r",   # 内部产品线名
    "dGVzdDFnYXRld2F5",   # 内部网关域名
]
DENY = [base64.b64decode(x).decode("utf-8") for x in _DENY_B64]

SKIP_DIRS = {".git", "build", "__pycache__", "node_modules", ".mypy_cache"}
# 文件里的词都是 base64，所以扫自己不会红；留着这个口子反而会让它成为盲区
SKIP_FILES = set()

# 凭据：私钥块，或「键名 = 带引号的像凭据的值」
SECRETS = [
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
    r"""(?i)(?:api[_-]?key|access[_-]?token|secret[_-]?key|password)\s*[:=]\s*['"][A-Za-z0-9/+=_\-]{12,}['"]""",
]
# 本机绝对路径（个人目录名会顺带泄漏用户名）
ABS_PATH = re.compile(r"/(?:Users|home)/[A-Za-z0-9._-]+")

TEXT_EXT = {".md", ".py", ".json", ".html", ".yml", ".yaml", ".txt",
            ".css", ".js", ".sh", ".toml", ".cfg", ".ini", ""}


def _walk():
    for root, dirs, files in os.walk(ROOT):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        for f in sorted(files):
            if f in SKIP_FILES:
                continue
            p = os.path.join(root, f)
            if os.path.splitext(f)[1].lower() not in TEXT_EXT:
                continue
            yield p, os.path.relpath(p, ROOT)


def _read(p):
    try:
        with open(p, encoding="utf-8") as fh:
            return fh.read()
    except (UnicodeDecodeError, OSError):
        return None


class PublicHygieneTest(unittest.TestCase):

    def test_no_internal_identifiers(self):
        """内部叫法不许出现在公开仓库的任何文件里。"""
        pat = re.compile("|".join(DENY), re.I)
        bad = []
        for p, rel in _walk():
            s = _read(p)
            if s is None:
                continue
            for m in pat.finditer(s):
                line = s[:m.start()].count("\n") + 1
                bad.append("%s:%d  %s" % (rel, line, m.group(0)))
        self.assertFalse(bad, "内部标识泄漏：\n  " + "\n  ".join(bad[:20]))

    def test_no_credentials(self):
        """私钥、像凭据的赋值，一个都不许有。"""
        bad = []
        for p, rel in _walk():
            s = _read(p)
            if s is None:
                continue
            for pat in SECRETS:
                for m in re.finditer(pat, s):
                    line = s[:m.start()].count("\n") + 1
                    bad.append("%s:%d  %s" % (rel, line, m.group(0)[:60]))
        self.assertFalse(bad, "疑似凭据：\n  " + "\n  ".join(bad[:20]))

    def test_no_absolute_home_paths(self):
        """示例路径用 /path/to，别把某人本机目录带出去。"""
        bad = []
        for p, rel in _walk():
            s = _read(p)
            if s is None:
                continue
            for m in ABS_PATH.finditer(s):
                line = s[:m.start()].count("\n") + 1
                bad.append("%s:%d  %s" % (rel, line, m.group(0)))
        self.assertFalse(bad, "本机路径泄漏：\n  " + "\n  ".join(bad[:20]))

    def test_no_env_files_tracked(self):
        """.env 这类文件不该进来。"""
        bad = [rel for p, rel in _walk()
               if os.path.basename(rel) in (".env", ".env.local", "credentials.json")]
        self.assertFalse(bad, "不该跟踪的文件：%s" % bad)


if __name__ == "__main__":
    unittest.main(verbosity=2)
