# 音频整理清单

> 清理状态：已按用户要求删除后三类共 147 个音频，释放 726.1 MiB。当前剩余 41 个音频，120.5 MiB。下方内容和 CSV 是清理前快照；删除记录见 [清理日志](audio-cleanup-2026-10-22.json)。

扫描日期：2026-10-22（Europe/Amsterdam）。仅统计本仓库中的音频；没有删除或移动文件。

共 **188 个音频文件，846.5 MiB**。

## 按用途分类

| 分类 | 文件数 | 大小 |
|---|---:|---:|
| 旧版播放器与演示素材（旧服务可能使用） | 16 | 16.9 MiB |
| 已导出的 Grid MP3（保留/按版本选择） | 15 | 4.3 MiB |
| 历史实验（当前平台未引用，可归档） | 100 | 585.5 MiB |
| 当前任务/播放文件（保留） | 23 | 94.5 MiB |
| 当前生成过程素材（可评估清理，保留会便于排查和复现） | 31 | 123.7 MiB |
| 当前曲库（保留） | 3 | 21.7 MiB |

## 当前曲库：建议全部保留

| 名称 | 作品 | 时长 | 文件 |
|---|---|---:|---|
| Morandi · Still Life | Still Life / Giorgio Morandi | 27.00 s | `curator_platform/data/music/Morandi - Still Life-001.wav` |
| terrace at night | terrace at night / vincent van gogh | 30.00 s | `curator_platform/data/music/terrace at night-001.wav` |
| Mondrian · Boogie Revival | Victory Boogie Woogie / Piet Mondrian | 29.00 s | `curator_platform/data/music/Mondrian - Boogie Revival-001.wav` |

## 已保存的三个 Grid

三组都是 terrace at night → Victory Boogie Woogie。编号是导出版本，不代表自动评选的优劣。

| 导出文件夹 | 创建时间（荷兰） | 方法 | 五个 cell 时长（秒） |
|---|---|---|---|
| `audio/terrace at night - Victory Boogie Woogie` | 10-21 19:54 | Inpaint + audio-to-audio | 30.00 / 3.75 / 3.75 / 3.75 / 29.00 |
| `audio/terrace at night - Victory Boogie Woogie-002` | 10-21 19:59 | 纯 Inpaint | 30.00 / 3.75 / 3.75 / 3.75 / 29.00 |
| `audio/terrace at night - Victory Boogie Woogie-003` | 10-22 10:50 | 纯 Inpaint | 30.00 / 11.75 / 11.75 / 11.75 / 29.00 |

每个 MP3 导出文件夹包含 `cell_0.mp3` 到 `cell_4.mp3`。浏览器播放使用 `curator_platform/data/jobs/<grid-id>/cell_*.wav`，并不是读取这些 MP3。两份是不同用途、不同格式。

## 建议清理顺序

1. **优先归档 `assets/generated/` 的历史实验。** 100 个音频，约 585.5 MiB。包含旧 Mondrian/Morandi 生成、过渡候选、旧 grid、备份和三音层实验。它们不是当前 7870 平台的直接播放依赖，但可能包含值得保留的策展选段和旧工作流记录。建议先移到归档目录或外部磁盘，不直接丢弃。
2. **试听决定三个 grid 保留哪几个。** 三套相同作品配对，方法和版本不同；最新版本不一定最好。移除某个 grid 应同步处理数据库记录和对应导出文件夹，避免网页出现失效条目。
3. **评估当前任务过程素材。** `reference.wav`、`generated.wav`、`cell_*-raw.wav`、`middle-original.wav` 等用于生成/排查/复现；下方 CSV 已标明哪些不是数据库直接引用。它们可能仍有研究价值，不宜把“未直接引用”等同于“无用”。
4. **保留当前曲库、Grid 播放 WAV 和完整数据库。** 不要整体删掉 `curator_platform/data/jobs/`。
5. **根目录 `audio/cell_*.mp3`、`song_a.mp3`、`song_b.mp3`、`drone.mp3` 和 `assets/` 演示音频属于旧播放器。** 如果不再使用旧服务，可另外归档；不影响新的 7870 平台。

## 历史实验分组

| 分组 | 文件数 | 大小 |
|---|---:|---:|
| `3eb25205-36c9-43b1-b01d-95a77155ea3f-transition` | 4 | 44.5 MiB |
| `52731d3d-b228-4014-a208-73f2ab821f22-transition` | 4 | 28.3 MiB |
| `6dc10e9e-4f47-4e83-af97-06bfd97ff58a-transition` | 4 | 28.3 MiB |
| `9532cdf6-d42b-4c02-bd45-ac97af2d2ea5-transition` | 4 | 28.3 MiB |
| `b335190b-f498-4dbe-8657-6306fef569c5-transition` | 4 | 20.2 MiB |
| `curated-grid-20261021` | 13 | 29.0 MiB |
| `curated-grid-boogie-revival-20261021` | 18 | 53.8 MiB |
| `ee045c45-6482-4455-91f9-696c929acd0e-transition` | 4 | 44.5 MiB |
| `f5391dbb-3a7b-41e3-8d75-3b7b4bb5a7bf-transition` | 4 | 44.5 MiB |
| `f86b4c62-3261-4ba8-ba18-af74e6cf31e5-transition` | 4 | 28.3 MiB |
| `fef122da-674a-486f-840d-4781a408cc33-transition` | 4 | 24.3 MiB |
| `mondrian-three-layers` | 1 | 4.0 MiB |
| `mondrian-three-layers-denser` | 1 | 4.0 MiB |
| `顶层生成与 loop 文件` | 31 | 203.6 MiB |

## 完全相同的文件（SHA-256）

以下是字节完全相同的副本；只列举事实，不能据此直接删除被数据库引用的文件。

发现 **23 组**完全相同的文件。

1. `audio/cell_0.mp3`；`assets/generated/curated-grid-20261021/previous-grid/cell_0.mp3`；`assets/generated/curated-grid-boogie-revival-20261021/previous-grid/cell_0.mp3`
2. `audio/cell_1.mp3`；`assets/generated/curated-grid-20261021/previous-grid/cell_1.mp3`；`assets/generated/curated-grid-boogie-revival-20261021/previous-grid/cell_1.mp3`
3. `audio/cell_2.mp3`；`assets/generated/curated-grid-20261021/previous-grid/cell_2.mp3`；`assets/generated/curated-grid-boogie-revival-20261021/previous-grid/cell_2.mp3`
4. `audio/cell_3.mp3`；`assets/generated/curated-grid-20261021/previous-grid/cell_3.mp3`；`assets/generated/curated-grid-boogie-revival-20261021/previous-grid/cell_3.mp3`
5. `audio/cell_4.mp3`；`assets/generated/curated-grid-20261021/previous-grid/cell_4.mp3`；`assets/generated/curated-grid-boogie-revival-20261021/previous-grid/cell_4.mp3`
6. `audio/terrace at night - Victory Boogie Woogie/cell_0.mp3`；`audio/terrace at night - Victory Boogie Woogie-002/cell_0.mp3`；`audio/terrace at night - Victory Boogie Woogie-003/cell_0.mp3`
7. `audio/terrace at night - Victory Boogie Woogie/cell_4.mp3`；`audio/terrace at night - Victory Boogie Woogie-002/cell_4.mp3`；`audio/terrace at night - Victory Boogie Woogie-003/cell_4.mp3`
8. `assets/generated/3eb25205-36c9-43b1-b01d-95a77155ea3f-transition/transition.wav`；`assets/generated/3eb25205-36c9-43b1-b01d-95a77155ea3f.wav`
9. `assets/generated/52731d3d-b228-4014-a208-73f2ab821f22-transition/transition.wav`；`assets/generated/52731d3d-b228-4014-a208-73f2ab821f22.wav`
10. `assets/generated/6dc10e9e-4f47-4e83-af97-06bfd97ff58a-transition/transition.wav`；`assets/generated/6dc10e9e-4f47-4e83-af97-06bfd97ff58a.wav`
11. `assets/generated/754b73fa-411e-46c2-806d-26a3dcbd94ad-loop-220500.wav`；`assets/generated/curated-grid-20261021/cell_4.wav`；`assets/generated/curated-grid-boogie-revival-20261021/cell_4.wav`；`assets/generated/curated-grid-boogie-revival-20261021/previous-grid/cell_4.wav`；`curator_platform/data/music/Morandi - Still Life-001.wav`
12. `assets/generated/9532cdf6-d42b-4c02-bd45-ac97af2d2ea5-transition/transition.wav`；`assets/generated/9532cdf6-d42b-4c02-bd45-ac97af2d2ea5.wav`
13. `assets/generated/Mondrian-Boogie-Revival-loop-44100.wav`；`assets/generated/curated-grid-boogie-revival-20261021/cell_0.wav`；`curator_platform/data/jobs/65e7a66d-7b35-4a99-9776-3a2fde5e7335/cell_4.wav`；`curator_platform/data/jobs/79a977d6-968b-4fc1-868a-a36d725c550d/cell_4.wav`；`curator_platform/data/jobs/e0eec255-f401-43f5-8a63-eb497f51624d/cell_4.wav`；`curator_platform/data/music/Mondrian - Boogie Revival-001.wav`
14. `assets/generated/b335190b-f498-4dbe-8657-6306fef569c5-transition/transition.wav`；`assets/generated/b335190b-f498-4dbe-8657-6306fef569c5.wav`
15. `assets/generated/cb89007a-07e8-4474-97c0-c052795e4105-loop-44100.wav`；`assets/generated/curated-grid-20261021/cell_0.wav`；`assets/generated/curated-grid-boogie-revival-20261021/previous-grid/cell_0.wav`
16. `assets/generated/curated-grid-20261021/cell_1.wav`；`assets/generated/curated-grid-boogie-revival-20261021/previous-grid/cell_1.wav`
17. `assets/generated/curated-grid-20261021/cell_2.wav`；`assets/generated/curated-grid-boogie-revival-20261021/previous-grid/cell_2.wav`
18. `assets/generated/curated-grid-20261021/cell_3.wav`；`assets/generated/curated-grid-boogie-revival-20261021/previous-grid/cell_3.wav`
19. `assets/generated/ee045c45-6482-4455-91f9-696c929acd0e-transition/transition.wav`；`assets/generated/ee045c45-6482-4455-91f9-696c929acd0e.wav`
20. `assets/generated/f5391dbb-3a7b-41e3-8d75-3b7b4bb5a7bf-transition/transition.wav`；`assets/generated/f5391dbb-3a7b-41e3-8d75-3b7b4bb5a7bf.wav`
21. `assets/generated/f86b4c62-3261-4ba8-ba18-af74e6cf31e5-transition/transition.wav`；`assets/generated/f86b4c62-3261-4ba8-ba18-af74e6cf31e5.wav`
22. `assets/generated/fef122da-674a-486f-840d-4781a408cc33-transition/transition.wav`；`assets/generated/fef122da-674a-486f-840d-4781a408cc33.wav`
23. `curator_platform/data/jobs/65e7a66d-7b35-4a99-9776-3a2fde5e7335/cell_0.wav`；`curator_platform/data/jobs/79a977d6-968b-4fc1-868a-a36d725c550d/cell_0.wav`；`curator_platform/data/jobs/c88d2363-8da3-418c-ac9d-63d011c6f18f/loop.wav`；`curator_platform/data/jobs/e0eec255-f401-43f5-8a63-eb497f51624d/cell_0.wav`；`curator_platform/data/music/terrace at night-001.wav`

完整逐文件清单见 [CSV](audio-inventory-2026-10-22.csv)，包含时长、大小、引用关系和 SHA-256。
