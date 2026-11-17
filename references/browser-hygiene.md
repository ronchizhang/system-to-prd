# 浏览器卫生：标签页只借不占

> 对应硬约束 19。脚本改动集中在 `scripts/tab_guard.py`，`vendor_cdp.py` 保持上游原样。

## 为什么要有这一条

采集一轮 = 开几十个页面，每页抓 5–10 帧（列表 / 详情 / 弹窗 / 页签）。如果一个页面开一个标签页且不关：

- 20 个页面之后浏览器常驻内存翻倍，`Runtime.evaluate` 开始变慢；
- 40 个页面之后 CDP 偶发超时，`snapshot_page` 抓回来的帧是「半张」——结构有、图没截全；
- 更糟的是没人知道是内存问题，会去怀疑页面慢、选择器不对、等待时间不够。

**根因不是页面重，是开出去的页没关。**

## 机制

`scripts/tab_guard.py` 提供 `Workspace`：

```python
from tab_guard import Workspace

with Workspace(port=9222) as w:      # 开一个专用标签页，不碰用户正在看的
    w.navigate("https://test1admin.example.com/personManage/list")
    w.evaluate("document.title")
    w.close_extra()                  # 点「查看」弹出来的新页，随手收掉
# 退出 with：关自己的页 + 关弹出来的页，异常退出也关（atexit）
```

| 能力 | 方法 | 说明 |
|:--|:--|:--|
| 开专用页 | `Workspace(port)` / `open()` | 先记基线（开工时浏览器里已有的页），再建新页 |
| 导航 | `navigate(url)` | 转发给 CDPClient |
| 执行 JS | `evaluate(js)` | 同上 |
| 收弹窗页 | `close_extra()` | 关掉「不在基线、也不是自己」的页 |
| 收工 | `close()` | 先收 extra，再关自己的页（`keep=True` 时保留自己） |
| 保留 | `keep=True` / `PRD_KEEP_TAB=1` | 调试时留着页看，默认不保留 |

边界是**基线**：开工那一刻已在浏览器里的页一律不碰。所以不会误关用户正在填的表单。

## 已经接上的脚本

| 脚本 | 改动 |
|:--|:--|
| `snapshot_page.py` | `connect()` 改用 `Workspace`；`close_tab()` 由 workspace 收口；`snap_one` 每点一次按钮/页签就 `close_extra()` 并打印「回收 N 个标签页」 |
| `shot_verify.py` | 不再劫持 `pages[0]`，改开专用页；新增 `--keep-tab` |
| `export_docs_md.py` | `Page.close` 挪进 `finally`，异常/超时也关，另用 HTTP `/json/close` 兜底 |

## 人工清理

```bash
python scripts/cdp_tabs.py list                       # 看数量，空白页 ≥3 会给提示
python scripts/cdp_tabs.py list --json
python scripts/cdp_tabs.py close --blank              # 关所有空白页（最常见）
python scripts/cdp_tabs.py close --url-contains admin
python scripts/cdp_tabs.py close --all-but <targetId>  # 只留一个
python scripts/cdp_tabs.py close --blank --dry         # 只看会关哪些
```

默认**不关非空白页**；要关带内容的页必须显式给条件，避免手滑。

## 自测记录（2026-11-17）

在 headless Chrome（端口 9333）上跑：

| 场景 | 结果 |
|:--|:--|
| 连开三页再关 | 标签数 1 → 1 → 1 → 1，无残留 |
| 页内 `window.open` 弹新页 | 3 → 4 → `close_extra` 后回到 3 |
| `keep=True` | 关掉 workspace 后该页仍在，可手动关 |
| 脚本中途抛异常（含已弹新页） | 退出后标签数回到基线 |
| `snapshot_page.py` 抓一帧 | 抓前 1 个、抓后 1 个 |
| `shot_verify.py --skip-shot` | 同上 |

## 不改 vendor_cdp.py 的原因

`vendor_cdp.py` 是 `browser-automation-cdp` skill 里 `cdp.py` 的内嵌副本，文件头写明「只动这一行说明，代码保持原样，便于日后对比更新」。标签页回收是本 skill 的纪律，放在 `tab_guard.py`，两边都能独立演进。

如果哪天上游自己也加了 `Workspace`，删掉本文件、把 `import tab_guard` 换成上游模块即可，脚本侧只有一个 import 的差别。
