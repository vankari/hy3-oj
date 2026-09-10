# Demo 分片交付

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
