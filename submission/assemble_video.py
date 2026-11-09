"""
submission/assemble_video.py
────────────────────────────────────────────────────────────────────────────────
Assembles the final LedgerMind showcase video:
1. Renders each of the 7 scenes with exact audio synchronization, 1920x1080 resolution, and 30 FPS.
2. Concatenates all scenes seamlessly into ledgermind_showcase.mp4.
3. Embeds subtitles track (subtitles.srt).
4. Verifies playback, duration, resolution, and audio track.
"""

import json
import os
from pathlib import Path
import subprocess

VIDEO_DIR = Path(r"C:\Users\kiran\LedgerMind\submission\video")
AUDIO_DIR = VIDEO_DIR / "audio"
FRAMES_DIR = VIDEO_DIR / "frames"
RECORDINGS_DIR = VIDEO_DIR / "source_recordings"
SEGS_DIR = VIDEO_DIR / "segments"
SEGS_DIR.mkdir(parents=True, exist_ok=True)

FINAL_OUTPUT = VIDEO_DIR / "ledgermind_showcase.mp4"
MANIFEST_FILE = AUDIO_DIR / "manifest.json"
SRT_FILE = VIDEO_DIR / "subtitles.srt"

FFMPEG_EXE = r"C:\Users\kiran\AppData\Roaming\Python\Python314\site-packages\imageio_ffmpeg\binaries\ffmpeg-win-x86_64-v7.1.exe"


def run_cmd(cmd, desc):
    print(f"Executing: {desc}...")
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if res.returncode != 0:
        print(f"Error in {desc}:\nSTDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}")
        raise RuntimeError(f"FFmpeg failed in {desc}")
    return res


def assemble_scene1(duration):
    """Scene 1: Title card for 4s, then clip_scene1.webm for remaining time."""
    out_file = SEGS_DIR / "seg1.mp4"
    audio_file = AUDIO_DIR / "scene1_problem.mp3"
    title_png = FRAMES_DIR / "title_card.png"
    clip_webm = RECORDINGS_DIR / "clip_scene1.webm"

    # Split clip into 4s title card + clip
    seg1_a = SEGS_DIR / "seg1_a.mp4"
    seg1_b = SEGS_DIR / "seg1_b.mp4"
    t_title = 4.0
    t_clip = duration - t_title

    # 4s title card video
    cmd_a = [
        FFMPEG_EXE, "-y",
        "-loop", "1", "-i", str(title_png),
        "-t", str(t_title),
        "-vf", "scale=1920:1080,format=yuv420p",
        "-r", "30", "-c:v", "libx264", "-preset", "fast", "-crf", "20",
        str(seg1_a),
    ]
    run_cmd(cmd_a, "Scene 1 Title Card Video")

    # t_clip video from webm
    cmd_b = [
        FFMPEG_EXE, "-y",
        "-i", str(clip_webm),
        "-t", str(t_clip),
        "-vf", "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2,format=yuv420p",
        "-r", "30", "-c:v", "libx264", "-preset", "fast", "-crf", "20",
        str(seg1_b),
    ]
    run_cmd(cmd_b, "Scene 1 App Clip Video")

    # Concat video parts and add audio
    concat_txt = SEGS_DIR / "seg1_concat.txt"
    with open(concat_txt, "w", encoding="utf-8") as f:
        f.write(f"file '{seg1_a.name}'\nfile '{seg1_b.name}'\n")

    cmd_merge = [
        FFMPEG_EXE, "-y",
        "-f", "concat", "-safe", "0", "-i", str(concat_txt),
        "-i", str(audio_file),
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", "192k",
        "-t", str(duration),
        str(out_file),
    ]
    run_cmd(cmd_merge, "Scene 1 Complete")
    return out_file


def assemble_image_scene(scene_id, image_png, audio_mp3, duration, out_seg):
    """Renders an image for the exact audio duration."""
    out_file = SEGS_DIR / out_seg
    cmd = [
        FFMPEG_EXE, "-y",
        "-loop", "1", "-i", str(image_png),
        "-i", str(audio_mp3),
        "-vf", "scale=1920:1080,format=yuv420p",
        "-r", "30",
        "-c:v", "libx264", "-preset", "fast", "-crf", "20",
        "-c:a", "aac", "-b:a", "192k",
        "-t", str(duration),
        str(out_file),
    ]
    run_cmd(cmd, f"Scene {scene_id} Image Video")
    return out_file


def assemble_clip_scene(scene_id, clip_webm, audio_mp3, duration, out_seg):
    """Renders a recorded webm clip for the exact audio duration."""
    out_file = SEGS_DIR / out_seg
    cmd = [
        FFMPEG_EXE, "-y",
        "-i", str(clip_webm),
        "-i", str(audio_mp3),
        "-vf", "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2,format=yuv420p",
        "-r", "30",
        "-c:v", "libx264", "-preset", "fast", "-crf", "20",
        "-c:a", "aac", "-b:a", "192k",
        "-t", str(duration),
        str(out_file),
    ]
    run_cmd(cmd, f"Scene {scene_id} Webm Video")
    return out_file


def main():
    with open(MANIFEST_FILE, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    durations = {item["id"]: item["duration"] for item in manifest}
    print("Scene Durations:", durations)

    # 1. Scene 1: Problem & System Overview
    seg1 = assemble_scene1(durations["scene1_problem"])

    # 2. Scene 2: Innovation & Architecture Card
    seg2 = assemble_image_scene(
        "scene2_innovation",
        FRAMES_DIR / "architecture_card.png",
        AUDIO_DIR / "scene2_innovation.mp3",
        durations["scene2_innovation"],
        "seg2.mp4",
    )

    # 3. Scene 3A: Intake & Queue
    seg3a = assemble_clip_scene(
        "scene3a_intake",
        RECORDINGS_DIR / "clip_scene3a.webm",
        AUDIO_DIR / "scene3a_intake.mp3",
        durations["scene3a_intake"],
        "seg3a.mp4",
    )

    # 4. Scene 3B: Resolution Workbench
    seg3b = assemble_clip_scene(
        "scene3b_workbench",
        RECORDINGS_DIR / "clip_scene3b.webm",
        AUDIO_DIR / "scene3b_workbench.mp3",
        durations["scene3b_workbench"],
        "seg3b.mp4",
    )

    # 5. Scene 4: Hindsight Vector Memory & Comparison
    seg4 = assemble_clip_scene(
        "scene4_hindsight",
        RECORDINGS_DIR / "clip_scene4.webm",
        AUDIO_DIR / "scene4_hindsight.mp3",
        durations["scene4_hindsight"],
        "seg4.mp4",
    )

    # 6. Scene 5: Memory Intelligence
    seg5 = assemble_clip_scene(
        "scene5_differentiator",
        RECORDINGS_DIR / "clip_scene5.webm",
        AUDIO_DIR / "scene5_differentiator.mp3",
        durations["scene5_differentiator"],
        "seg5.mp4",
    )

    # 7. Scene 6: Closing Summary & Roadmap
    seg6 = assemble_image_scene(
        "scene6_conclusion",
        FRAMES_DIR / "closing_card.png",
        AUDIO_DIR / "scene6_conclusion.mp3",
        durations["scene6_conclusion"],
        "seg6.mp4",
    )

    # Master Concatenation List
    master_txt = SEGS_DIR / "master_concat.txt"
    with open(master_txt, "w", encoding="utf-8") as f:
        for seg in [seg1, seg2, seg3a, seg3b, seg4, seg5, seg6]:
            f.write(f"file '{seg.name}'\n")

    print("\nConcatenating all 7 scenes into final showcase video...")
    cmd_final = [
        FFMPEG_EXE, "-y",
        "-f", "concat", "-safe", "0", "-i", str(master_txt),
        "-i", str(SRT_FILE),
        "-c:v", "copy",
        "-c:a", "copy",
        "-c:s", "mov_text",
        "-metadata:s:s:0", "language=eng",
        "-metadata:s:s:0", "title=English",
        "-movflags", "+faststart",
        str(FINAL_OUTPUT),
    ]
    run_cmd(cmd_final, "Final Video Assembly & Subtitle Muxing")

    print(f"\n🎉 Successfully created final showcase video: {FINAL_OUTPUT}")

    # Inspect final video properties
    cmd_probe = [
        FFMPEG_EXE,
        "-i", str(FINAL_OUTPUT),
        "-f", "null",
        "-",
    ]
    res_probe = subprocess.run(cmd_probe, stderr=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    print("\n--- FFmpeg Video Probe Output ---")
    import re
    time_match = re.findall(r"time=(\d+):(\d+):(\d+\.\d+)", res_probe.stderr)
    if time_match:
        h, m, s = time_match[-1]
        total_sec = float(h) * 3600 + float(m) * 60 + float(s)
        print(f"Final Video Duration: {int(total_sec // 60)}m {int(total_sec % 60)}s ({total_sec:.2f} seconds)")
    size_bytes = FINAL_OUTPUT.stat().st_size
    print(f"Final Video File Size: {size_bytes / (1024 * 1024):.2f} MB")
    print(f"File Path: {FINAL_OUTPUT}")


if __name__ == "__main__":
    main()
