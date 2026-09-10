"""Curate the already recorded/verified demo; runtime intermediates are never bulk-copied.

python scripts/build_demo_release.py --out runs/releases/demo
Existing releases are not overwritten. The video must first pass runs/demo/qa_video.py.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from split_archive import digest, pack, restore


def build(root, output):
    final = root / 'runs/demo/final'
    qa = json.loads((final / 'video_qa.json').read_text(encoding='utf-8'))
    assert qa['decode_ok'] and qa['duration_s'] <= 120
    assert digest(final / 'Hy3-OJ-demo.mp4') == qa['sha256']
    stage = root / 'runs/demo/release_stage'
    if stage.exists():
        raise FileExistsError('Choose/move the previous runs/demo/release_stage before rebuilding')
    stage.mkdir(parents=True)

    def copy(source, dest):
        target = stage / dest
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)

    for name in ('Hy3-OJ-demo.mp4', 'Hy3-OJ-demo.zh-CN.srt', 'video_qa.json', 'qa_contact_sheet.png'):
        copy(final / name, name)
    # Editorial timing/provenance is portable; raw recording file references are local-only.
    chapters = json.loads((final / 'edit_manifest.json').read_text(encoding='utf-8'))
    for c in chapters['chapters']:
        for field in ('source', 'start', 'end'):
            c.pop(field, None)
    (stage / 'chapters.json').write_text(json.dumps(chapters, ensure_ascii=False, indent=2), encoding='utf-8')
    external = root / 'runs/demo/integer_decomposition'
    for name in ('sqrt_problem.jsonl', 'fourth_problem.jsonl', 'sqrt_statement.md', 'fourth_statement.md',
                 'manifest.json', 'benchmark.json', 'reference_sqrt.py', 'reference_fourth.py',
                 'reference_sqrt.cpp', 'reference_fourth.cpp'):
        copy(external / name, 'problems/integer_decomposition/' + name)
    copy(root / 'runs/demo/acceptance/merge_set_problem.jsonl', 'problems/merge_set_problem.jsonl')
    accepted = json.loads((root / 'runs/demo/acceptance/browser_acceptance.json').read_text(encoding='utf-8'))
    for row in accepted:
        source = Path(row['trace'])
        copy(source, 'evidence/traces/' + source.name)
        row['trace'] = 'traces/' + source.name
        row.pop('url', None)  # Host-local conversation URL does not survive export.
    (stage / 'evidence/browser_acceptance.json').write_text(json.dumps(accepted, ensure_ascii=False, indent=2), encoding='utf-8')
    copy(root / 'runs/demo/acceptance/extras.json', 'evidence/extras.json')
    provenance = {
        'internal_datasets': ['deepmind/code_contests', 'livecodebench/code_generation_lite'],
        'external': {'source': 'https://spaces.ac.cn/archives/9775', 'tests_by': 'Hy3-OJ project',
                     'seed': 9775, 'small_crosscheck': '101..20000', 'all_cases': 'independent parity oracle',
                     'video_profile': 'sqrt', 'sqrt_tests': 75, 'fourth_v2_tests': 90, 'time_limit_s': 1},
        'internal_demo': {'id': 'atcoder:abc302_f', 'title': 'Merge Set（集合合并）',
                          'source': 'https://atcoder.jp/contests/abc302/tasks/abc302_f?lang=en',
                          'dataset': 'livecodebench/code_generation_lite', 'difficulty_in_subset': 'hard',
                          'public_tests': 4, 'private_tests': 12, 'time_limit_s': 3, 'memory_mb': 1024},
        'video': qa,
    }
    (stage / 'provenance.json').write_text(json.dumps(provenance, ensure_ascii=False, indent=2), encoding='utf-8')
    (stage / 'README.md').write_text('''# Hy3-OJ Demo

[播放视频](Hy3-OJ-demo.mp4) · [中文字幕](Hy3-OJ-demo.zh-CN.srt) · [画面抽检](qa_contact_sheet.png)

1 分 58 秒，1080p，中文旁白和烧录字幕；真实应用录屏。缓存复跑、等待加速及历史回放均有标注。

## 外部题示例

“整数分解与最小和”来自[苏剑林博客](https://spaces.ac.cn/archives/9775)。
本项目明确为求精确最小值，并构造固定数据：seed=9775；小值、平方数和乘积边界、反例、上界及随机大数。
101～20000 由平方根和四次根算法交叉核验，全部固定点再经独立奇偶参数化算法检查。
视频正向展示基础版（N≤10¹²），4 公开 + 71 私有测试；大数据版 v2（N≤2⁶³−1）90 点。
两版均为每测试 1 秒 / 256 MB，特殊校验器接受任意最优三元组。
这些数据由项目制作，不是博客官方测试；完整题包跳过 AI 造测。

- [基础版完整题包](problems/integer_decomposition/sqrt_problem.jsonl)：视频 C++17 75/75，过程通过。
- [大数据版完整题包](problems/integer_decomposition/fourth_problem.jsonl)：用于复杂度压力测试，未作为在线 Agent 成功案例。
- [分类及种子清单](problems/integer_decomposition/manifest.json)、[参考解 Docker 校准](problems/integer_decomposition/benchmark.json)。

## 内部题示例

内部评测接入 CodeContests 和 LiveCodeBench；本片题目来自 LiveCodeBench，
原题为 [AtCoder ABC302 F — Merge Set](https://atcoder.jp/contests/abc302/tasks/abc302_f?lang=en)。
Merge Set 意为“集合合并”：合并有交集的集合，以最少次数使 1 和 M 同处一个集合。
hard 为所用子集标签；4 个公开 + 12 个私有测试来自本项目保存的 LiveCodeBench 数据。
视频 Python3 16/16，过程通过，限制为 3 秒 / 1024 MB。这是本地判题成绩。

- [内部完整题包](problems/merge_set_problem.jsonl)
- [题源与数据元信息](provenance.json)
- [真实浏览器验收](evidence/browser_acceptance.json)、[其余交互验收](evidence/extras.json)
- [视频质量检查与哈希](video_qa.json)、[逐段字幕及时间](chapters.json)

启动仓库的 `python scripts/run_demo.py`，通过输入框上传上述 JSONL 即可复跑。
完整题包包含测试和判题限制；只复制题面会丢掉测试。需要本机配置 Hy3 API 与 Docker。
参考实现只用于标答和测试校准，未作为 Agent 生成结果展示。
负向历史镜头保留 AI 造测、修复及过程错误状态；判题结果与过程状态独立。
''', encoding='utf-8')
    manifest = pack(stage, output, part_mib=8)
    restored = root / 'runs/demo/release_restore_check'
    verified = restore(output / 'manifest.json', restored)
    assert all(digest(restored / f['path']) == f['sha256'] for f in manifest['files'])
    summary = {'video': qa, 'parts': manifest['parts'], 'restoration': verified}
    (root / 'runs/demo/release_verification.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    (output / 'README.md').write_text('''# Demo 分片交付

视频、中文字幕、外部两档完整题包、内部 Merge Set 完整题包和验收证据都在分片中。
每片最多 8 MiB；下载本目录全部 `Hy3-OJ-demo.zip.00*` 与 [manifest.json](manifest.json)。

从仓库根目录执行（仅需 Python 3.11 标准库）：

```powershell
python scripts/split_archive.py restore runs/releases/demo/manifest.json runs/demo_restored
```

还原后打开 `runs/demo_restored/Hy3-OJ-demo.mp4`；题包在 `problems/`。
还原器按清单顺序拼接并检查分片、ZIP 及逐文件 SHA-256，缺片或损坏会失败。输出目录须为空或不存在。
单独的 `.001` 不是独立 ZIP，不能单片解压。

仅检查完整性、不解压：

```powershell
python scripts/split_archive.py restore runs/releases/demo/manifest.json runs/demo_verified --verify-only
```

题源、数据构造与截图见 [Demo 交付说明](../../../docs/demo_delivery.md)。
构建入口：[build_demo_release.py](../../../scripts/build_demo_release.py)；分片器也支持对任意显式选择的目录执行 `pack`。
''', encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=Path('runs/releases/demo'))
    args = parser.parse_args()
    build(Path(__file__).resolve().parents[1], args.out.resolve())
