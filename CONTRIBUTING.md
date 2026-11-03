# Contributing

This project has one unusual rule, and it is the reason the rest of it holds together.

## 同一条错误被指出第二次，就把它做成门禁

A rule written only in prose gets forgotten — you have to remember it before every run, and when you forget, you repeat the mistake. So:

1. First time: write it down in `references/` (what it is, what went wrong, how to fix).
2. Second time: **turn it into a check.** Ask: *can a regex or a structure test decide this?*
   - data layer → a semantic check in `scripts/schema.py`
   - artifact layer → a group of checks in `scripts/check_delivery.py`
   - wording layer → a rule in `scripts/scan_wording.py`
3. If it cannot be decided mechanically → a manual checklist item, ticked at delivery.

The negative example is in the repo history: the draft-numbering rule was documented once, violated again the next round, and only stopped after becoming three code gates.

## Before you open a PR

- [ ] `python -m unittest discover -s tests` passes
- [ ] `python scripts/doctor.py` still prints green
- [ ] `python scripts/build_module_prd.py --data assets/example_module.json --out /tmp/x.html --strict` succeeds
- [ ] If you added a gate: **you also added a test that proves the gate fails on bad input.** Verifying only that things pass, never that things are caught, is the same as not having the gate.
- [ ] No company names, customer data, internal endpoints, or logos. The sample must stay fictional.
- [ ] Docs updated in the same PR (a rule without a landing spot is not a rule)

## What we will not merge

- Anything that fabricates data to make a check pass ("write 'N/A' to get past the gate")
- Renderer edits that break the single-file, zero-external-resource guarantee
- Features that skip the test-environment guard

## Reporting a bug

Include the `doctor.py` output and the exact command. If a gate missed something it should have caught, that is the highest-value bug you can report — include the input that slipped through.
