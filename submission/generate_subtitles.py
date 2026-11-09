"""
submission/generate_subtitles.py
────────────────────────────────────────────────────────────────────────────────
Generates synchronized .srt subtitles based on the exact audio manifests and scene timings.
"""

import json
from pathlib import Path
import re

AUDIO_DIR = Path(r"C:\Users\kiran\LedgerMind\submission\video\audio")
MANIFEST_FILE = AUDIO_DIR / "manifest.json"
SRT_FILE = Path(r"C:\Users\kiran\LedgerMind\submission\video\subtitles.srt")

def format_time(seconds: float) -> str:
    hrs = int(seconds // 3600)
    mins = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int(round((seconds - int(seconds)) * 1000))
    return f"{hrs:02d}:{mins:02d}:{secs:02d},{millis:03d}"

def generate_srt():
    with open(MANIFEST_FILE, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    srt_entries = []
    current_time = 0.0
    entry_idx = 1

    for scene in manifest:
        text = scene["text"]
        duration = scene["duration"]
        # Split into sentences or clauses
        sentences = [s.strip() for s in re.split(r"(?<=[.?!])\s+", text) if s.strip()]
        
        # Allocate time proportionally to word count
        word_counts = [len(s.split()) for s in sentences]
        total_words = sum(word_counts)

        scene_start = current_time
        for sent, wc in zip(sentences, word_counts):
            sent_dur = (wc / total_words) * duration
            start_t = scene_start
            end_t = scene_start + sent_dur
            
            # Subtitle entry
            srt_entries.append(
                f"{entry_idx}\n"
                f"{format_time(start_t)} --> {format_time(end_t)}\n"
                f"{sent}\n"
            )
            entry_idx += 1
            scene_start = end_t

        current_time += duration

    srt_content = "\n".join(srt_entries)
    with open(SRT_FILE, "w", encoding="utf-8") as f:
        f.write(srt_content)
    print(f"Generated {entry_idx - 1} subtitle cues into {SRT_FILE}")

if __name__ == "__main__":
    generate_srt()
