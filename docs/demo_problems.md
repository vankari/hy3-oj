# Demo 展示题清单（已验证通过，录制用）

> 由 `scripts/pick_demo_problems.py` 从已有评测结果中挑选：每个难度一题，
优先选一次通过（rounds=0）的题，保证录制时稳定复现。


## LiveCodeBench


来源子集：`data/subsets/subset_lcb_v1.jsonl`


| 难度 | 题号 | 修复轮数 | 判题点数 | 演示命令 |
|---|---|---|---|---|
| easy | `leetcode:3252` | 0 | 0 | `python scripts/demo_solve.py --subset data/subsets/subset_lcb_v1.jsonl --id "leetcode:3252"` |
| medium | `leetcode:3046` | 1 | 0 | `python scripts/demo_solve.py --subset data/subsets/subset_lcb_v1.jsonl --id "leetcode:3046"` |
| hard | `atcoder:abc312_f` | 1 | 0 | `python scripts/demo_solve.py --subset data/subsets/subset_lcb_v1.jsonl --id "atcoder:abc312_f"` |

## CodeContests


来源子集：`data/subsets/subset_mid100.jsonl`


| 难度 | 题号 | 修复轮数 | 判题点数 | 演示命令 |
|---|---|---|---|---|
| easy | `1471_A. Strange Partition` | 1 | 0 | `python scripts/demo_solve.py --subset data/subsets/subset_mid100.jsonl --id "1471_A. Strange Partition"` |
| medium | `343_B. Alternating Current` | 1 | 0 | `python scripts/demo_solve.py --subset data/subsets/subset_mid100.jsonl --id "343_B. Alternating Current"` |
| hard | `p02939 AtCoder Grand Contest 037 - Dividing a String` | 1 | 0 | `python scripts/demo_solve.py --subset data/subsets/subset_mid100.jsonl --id "p02939 AtCoder Grand Contest 037 - Dividing a String"` |
