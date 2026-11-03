# Validation and interpretation

The original runtime was tested on reComputer Industrial / Orin NX16GB,
JetPack package6.2.1, L4T36.4.3, Python3.10.12 and CUDA12.6 on2026-11-02/03.
Historical runs are not rewritten by packaging changes. Private host addresses,
profiles, raw run records and screenshots are intentionally not in the public repo.

| Actual target-device check | Observed result | Limit |
| --- | --- | --- |
| Five real city-suggestion tasks | 5/5, two browser actions each | Laya city loop only; test supplied text, no Qwen parsing |
| Ten frozen held-out flight tasks on an earlier version | 9/10; successful-task median123.3s | One failed record-write race retained; limited Trip.com tasks, not general web success |
| Wait optimization, three routes / separate empty profiles / unchanged warm models | Baseline1/3, final3/3; optimized median41.6s | Small sample; initial optimized2/3 retained before readiness fix |
| Matched successful Guangzhou→Beijing task | 119.4s→41.6s (65.2% lower) | Wait/state handling change, not model replacement; failures aren't successful speed comparisons |
| Whiteboard create / modify / manual-move recovery, same identities | 13.08 / 8.89 / 4.22s, all verified | Supplied warm-model tasks, not held-out generalization |
| Whiteboard rename / local delete / standalone text | Verified actual UI edits and scene reads | Limited labels, colors, fixed grid and viewport |
| Cancel during held gesture / export reopen / window close recovery | Real input released; IDs/bindings verified after reopen | Not a guarantee for arbitrary external editors |
| Target runtime test suite before public packaging | 94 passed in35.59s | Includes fixture tests; fixture success is not real-site acceptance |

A user-supplied flight recording separately shows32.8s/5 browser actions, with
0.5s cumulative Laya and3.5s Qwen parsing. It reused existing page conditions and
cannot stand for an empty-profile run. A separately recorded whiteboard addition
shows10.1s/3 Laya calls. Recording duration is not task elapsed time.

System memory is CPU/GPU shared and sampled whole-system, including unrelated
processes. The recorded whiteboard addition reports12.29GiB and2577MiB swap;
this is not per-model GPU memory. A prior Qwen exit had no confirmed kernel cause.

No script-vs-model equivalence benchmark, general browser success rate, universal
hardware ranking, industrial reliability test or unattended transaction claim is
made. Public deployment checks and CI results are described separately from these
original task measurements. See release notes for the packaging verification.
