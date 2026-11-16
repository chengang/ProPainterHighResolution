# ProPainterHighResolution - 长视频去水印分块处理脚本

基于 [ProPainter](https://github.com/sczhou/ProPainter) 的自动化脚本，一站式处理超长视频的水印移除。ProPainter 官方只能整段视频一次处理，长视频直接爆显存/内存，本脚本自动分块、逐块推理、归集输出、合成成品。

## 一、解决什么问题
ProPainter 效果好，但**整段视频必须一次性读入**。一个 241 秒 1080p 30fps 的视频解帧后有 7233 张 PNG（约 20 GB），普通 GPU 直接 OOM。手工分块又很麻烦：每块要手动建目录、输出帧编号各自从 1 开始拼不回去、`results/` 里新旧结果混杂易取错、最后还要手动合成音画。

本脚本把这一切自动化：准备好帧和 mask，一条命令跑完。

## 二、使用方法

### 2.1 环境要求

- Linux + Python ≥ 3.10
- [uv](https://docs.astral.sh/uv/)（运行 ProPainter 用 `uv run`）
- FFmpeg（全局安装）
- NVIDIA GPU（实测 Pro 6000 96G 可一次处理 1080p 300 帧）

### 2.2 部署 ProPainter

```bash
git clone https://github.com/sczhou/ProPainter.git
cd ProPainter
uv venv
uv pip install -r requirements.txt
```

按官方说明把权重下载到 `weights/` 目录（ProPainter.pth, i3d_rgb_imagenet.pt, raft-things.pth, recurrent_flow_completion.pth, cutie-base-mega.pth）。

### 2.3 解出画面帧和音频

把视频放到 ProPainter 目录下（假设叫 `input.mp4`）：
```bash
mkdir -p inputs/my_video/frames
ffmpeg -i input.mp4 -qscale:v 1 inputs/my_video/frames/%06d.jpg
ffmpeg -i input.mp4 -vn -c:a copy inputs/my_video/audio.m4a
```

### 2.4 制作水印 mask（关键前置工作）

mask 告诉 ProPainter 哪些区域需要移除补全，**一张 mask 适用于全部帧**（水印位置固定即可）。
**硬性标准：**
| 项目 | 要求 |
| --- | --- |
| 文件 | 单张 PNG，命名 `mask.png`，放 ProPainter 根目录 |
| 分辨率 | 与画面帧完全一致（1080p 就是 1920×1080） |
| 像素含义 | **白色(255) = 要去掉的水印区域；黑色(0) = 保留画面**，必须二值 |
| 覆盖范围 | 白色完整包住水印并多留 5~10 像素余量，别画太大 |

静态水印的遮罩可以直接用 ffmpeg 生成，以 1920×1080 视频、右下角 240×100 的水印为例：
```bash
ffmpeg -f lavfi -i color=black:s=1920x1080 \
  -vf "drawbox=x=1640:y=940:w=240:h=100:color=white@1.0:t=fill" \
  -frames:v 1 mask.png
```

自检——用 ffmpeg 把 mask 叠到帧上看效果：
```bash
ffmpeg -i inputs/my_video/frames/000100.png -i mask.png -filter_complex "[0][1]blend=all_mode=screen" preview.png
```

### 2.5 确认目录结构

```
ProPainter/
├── inference_propainter.py
├── mask.png              ← 你做的 mask
├── inputs/my_video/
│   ├── audio.m4a         ← 抽出的音频
│   └── frames/           ← 解出的全部帧
├── weights/
└── run_propainter_batch.py   ← 本仓库脚本
```

### 2.6 运行

```bash
uv run run_propainter_batch.py
```

脚本自动完成：分块（软链接，不占磁盘）→ 逐块调 ProPainter → 输出帧按全局编号归集到 `output_frames/` 并清理本次 results → ffmpeg 合成音画。
跑完得到 `output-delogo.mp4`（1080p 带音频成品），中间产物 `output_frames/` 和 `chunks/` 保留。

**常用配置（脚本顶部）：**
| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `BATCH` | 300 | 每块帧数，OOM 就调小，显存富余可调大 |
| `FPS` | 30 | 须与解帧 fps 一致 |
| `FINAL_VIDEO` | output-delogo.mp4 | 成品文件名 |

## 三、原理

- **分块 + 软链接**：把 7233 帧切成 25 个"300 帧小视频"逐个喂给 ProPainter，用 `os.symlink` 建输入目录，零磁盘开销。
- **归集与防误取**：每块跑完按目录修改时间定位最新输出，帧搬移到 `output_frames/` 并按全局连续编号重命名，随后删除该块在 `results/` 里的全部结果，下块绝不会取到旧数据。
- **音画合成**： `ffmpeg -map 0:v:0 -map 1:a:0 -c:a copy` 音频流复制零损耗，`-crf 17` 高画质，`-shortest` 保证音画等长。
- **已知局限**：块边界几帧缺少跨块时序参考，可能轻微跳变；不支持断点续跑；要求水印位置固定。

## 四、致谢

- [ProPainter](https://github.com/sczhou/ProPainter)（CVPR 2023）
- [RAFT](https://github.com/princeton-vl/RAFT)

