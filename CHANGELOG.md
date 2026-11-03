# Changelog

Semantic versioning is not used here; versions track **structural** changes to the deliverable, and each entry states what was wrong rather than what was added. Full narrative history, with the reasoning and the real cases behind each change, lives at the end of [`SKILL.md`](./SKILL.md#七版本记录).

## v6.2 — every change now shows what it replaced

原型里的粉色块只能说明「这里改了」，答不了「原来是什么」——而评审第一个问的就是这句。
所以给改动加了 `changes` 台账（`id / title / where / before / after / why`），渲染成右侧的
**改前 → 改后** 对照卡：点原型里那块粉，卡片亮起来；点卡片，原型滚回去。

数据是新增的，不是从 HTML 反推的——原型只留改后的样子，改前那一版已经不在 DOM 里了。
`schema.py` 同时加了门禁：原型标了而台账没有的编号，直接报错。漏一条不会白屏，
只会少一张卡，读者以为这处没改过，这种静默缺失比报错难查得多。

顺带修掉一个真实隐患：`FieldController → FormFieldController` 这类替换，
目标串里含源串（`FormFieldController` 里有 `FieldController`），第二遍会套成
`FormFormFormFieldController`。现在类名规则带负向断言，并加了一条自愈正则把已套娃的压回去。

## v6.1 — four lanes, filled in

Defined "four lanes, one reader each" in v6.0 but never said how to fill them. This version adds the test-case lane (three-step cleanup from an xmind tree, every case pinned to a rule), the code lane (plain-language Q&A on top, front-end/back-end mapping below), and entity relations (5–7 top-level entities, each with "who creates it").

Also fixes anchor jumps landing at the top of the document, and adds URL deep links (`?m=cases`, `?m=code`, `?m=facts`, `?chg=C5`).

## v6.0 — one document, three audiences

Business owners, QA and developers were reading the same paragraph, so all three read it badly. Split into four lanes; technical detail **moves** (to the code lane or Appendix B) rather than being deleted, enforced by a gate.

## v5.3 — the section skeleton

Eight sections existed, but what goes **inside** each was unspecified, so the same document had eight sections with eight different shapes. Fixed slot lists per section, plus a gate that fails when section 1 declares "N changes" and section 4 only contains N-2 blocks.

## v5.0 — one signature instead of twelve

Module-level dual signatures meant 12 signatures for a 6-module project. Small teams do not work that way; the result was a permanent red X that stopped carrying information. Default is now a single document-level sign-off, bound to the draft number so it expires on edit.

## v4.4 — same-draft revisions

Added `Draft N (revision M)` for changes that only touch wording and evidence. One criterion: **did a business conclusion change?** If not, it is a revision — pushing a new draft makes readers think requirements changed and go diff-hunting for nothing.

## v4.2 — gates on gates

A single gate proves itself with its own data. Split into a process gate (human, signed) and a delivery gate (machine, reverse-checking the artifact). The second layer must approach from a different direction, otherwise it is duplicated labour.

## v4.0 — two delivery modes

Separated "record how it works today" from "design the next version". Mixing them produces a document where nobody can tell which sentence is current behaviour and which is a proposal.

Earlier iterations (v2.2–v3.x) are recorded in `SKILL.md`; most of them are CSS and capture bugs found by pointing the tool at real pages, each one now either a template fix or a gate.
