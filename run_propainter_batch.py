#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ProPainter 批量去水印脚本（Linux 专用）
======================================
流程：
  1. 把 inputs/my_video/frames/ 里的所有帧按 BATCH 张一组分块，
     用软链接建成分块输入目录（不复制文件，不占磁盘）。
  2. 逐块调用 ProPainter 去水印。
  3. 把每块的输出帧按全局连续编号搬移到 output_frames/（无损 PNG），
     并删除 results/ 中本次的结果（帧 + 视频），避免下次误取。
  4. 最后用 ffmpeg 把帧序列和 audio.m4a 合成 1080p 带音频的成品视频
     （音频直接流复制，不重新编码）。

中间产物：chunks/ 下的软链接目录和 output_frames/ 保留不删；
          results/ 中每块的结果在帧被取走后即删除。
"""

import glob
import math
import os
import shutil
import subprocess
import sys

# ==================== 配置区（按需修改） ====================
FRAMES_DIR     = "inputs/my_video/frames"     # 原始帧目录
AUDIO_FILE     = "inputs/my_video/audio.m4a"  # 音频文件
MASK_FILE      = "mask.png"                   # 水印掩码（与 inputs/mmm/mask.png 相同）
CHUNK_DIR_ROOT = "chunks"                     # 分块输入目录的根
RESULT_ROOT    = "results"                    # ProPainter 默认输出根目录
MERGED_DIR     = "output_frames"              # 归集后的无损帧目录
FINAL_VIDEO    = "output-delogo.mp4"          # 最终成品视频

BATCH = 300   # 每块帧数（实验验证 300 张刚好能跑，若 OOM 可调小）
FPS   = 30    # 目标帧率

# 传给 ProPainter 的参数（与你成功的实验命令一致）
PAINTER_ARGS = [
    "--fp16",
    "--subvideo_length", "48",
    "--neighbor_length", "12",
    "--mask_dilation", "4",
    "--save_fps", str(FPS),
    "--save_frames",
]

# 合成最终视频的编码参数：H.264，crf 17 高画质，强制 1080p
FFMPEG_VCODEC = ["-c:v", "libx264", "-preset", "slow", "-crf", "17",
                 "-pix_fmt", "yuv420p", "-vf", "scale=1920:1080"]


def sh(cmd):
    """打印并执行外部命令，失败即终止。"""
    print("\n$ " + " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True)


def main():
    # ---------- 0. 收集所有原始帧 ----------
    frames = sorted(glob.glob(os.path.join(FRAMES_DIR, "*.png")))
    total = len(frames)
    if total == 0:
        sys.exit(f"错误：{FRAMES_DIR} 里没有找到任何 png 帧！")
    if not os.path.isfile(MASK_FILE):
        sys.exit(f"错误：找不到掩码文件 {MASK_FILE}！")
    if not os.path.isfile(AUDIO_FILE):
        sys.exit(f"错误：找不到音频文件 {AUDIO_FILE}！")

    num_chunks = math.ceil(total / BATCH)
    print(f"共 {total} 帧，按每块 {BATCH} 张分 {num_chunks} 块处理。")

    os.makedirs(MERGED_DIR, exist_ok=True)

    global_idx = 0  # 归集帧的全局编号

    # ---------- 1~3. 分块 -> 推理 -> 归集 -> 清理 ----------
    for ci in range(num_chunks):
        lo, hi = ci * BATCH, min((ci + 1) * BATCH, total)
        chunk_frames = frames[lo:hi]
        chunk_name = f"chunk_{ci + 1:03d}"
        chunk_frames_dir = os.path.join(CHUNK_DIR_ROOT, chunk_name, "frames")
        os.makedirs(chunk_frames_dir, exist_ok=True)

        print(f"\n===== [{ci + 1}/{num_chunks}] {chunk_name}: "
              f"第 {lo + 1}~{hi} 张（共 {len(chunk_frames)} 张） =====")

        # 1) 建软链接（Linux 专用）
        for src in chunk_frames:
            dst = os.path.join(chunk_frames_dir, os.path.basename(src))
            if not os.path.exists(dst):
                os.symlink(os.path.abspath(src), dst)

        # 2) 调用 ProPainter
        sh(["uv", "run", "inference_propainter.py",
            "--video", chunk_frames_dir,
            "--mask", MASK_FILE] + PAINTER_ARGS)

        # 3) 找到本次输出目录（results/ 下最近修改的子目录）
        result_dir = max(glob.glob(os.path.join(RESULT_ROOT, "*")),
                         key=os.path.getmtime)
        out_frames_dir = os.path.join(result_dir, "frames")
        out_frames = sorted(glob.glob(os.path.join(out_frames_dir, "*.png")))
        if len(out_frames) != len(chunk_frames):
            print(f"警告：本块输出帧数({len(out_frames)})与输入({len(chunk_frames)})不一致，请检查！")

        # 4) 搬移帧到 output_frames/（全局连续编号）
        for of in out_frames:
            global_idx += 1
            shutil.move(of, os.path.join(MERGED_DIR, f"{global_idx:06d}.png"))
        print(f"已归集 {len(out_frames)} 帧 -> {MERGED_DIR}/（累计 {global_idx} 帧）")

        # 5) 删除 results/ 中本次的结果目录（帧 + 视频），防下次误取
        shutil.rmtree(result_dir)
        print(f"已清理本次结果目录：{result_dir}")

    # ---------- 4. 校验并合成最终视频 ----------
    if global_idx != total:
        print(f"警告：归集帧总数({global_idx}) 与原始帧总数({total}) 不一致！")

    sh(["ffmpeg", "-y",
        "-framerate", str(FPS),
        "-i", os.path.join(MERGED_DIR, "%06d.png"),
        "-i", AUDIO_FILE]
       + FFMPEG_VCODEC +
       ["-map", "0:v:0", "-map", "1:a:0",
        "-c:a", "copy",
        "-shortest",
        FINAL_VIDEO])

    print(f"\n✅ 全部完成！成品视频：{FINAL_VIDEO}")
    print(f"   无损中间帧在：{MERGED_DIR}/，分块目录在：{CHUNK_DIR_ROOT}/，均未删除。")


if __name__ == "__main__":
    main()

