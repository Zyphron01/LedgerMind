"""
submission/generate_audio.py
────────────────────────────────────────────────────────────────────────────────
Generates studio-grade neural voiceover for the LedgerMind showcase video.
Uses edge-tts with 'en-IN-PrabhatNeural' (warm, professional, natural Indian English).
"""

import asyncio
from pathlib import Path
import subprocess
import json
import edge_tts

AUDIO_DIR = Path(r"C:\Users\kiran\LedgerMind\submission\video\audio")
AUDIO_DIR.mkdir(parents=True, exist_ok=True)

FFMPEG_EXE = r"C:\Users\kiran\AppData\Roaming\Python\Python314\site-packages\imageio_ffmpeg\binaries\ffmpeg-win-x86_64-v7.1.exe"
VOICE = "en-IN-PrabhatNeural"

SCENES = [
    {
        "id": "scene1_problem",
        "title": "The Real Problem",
        "text": (
            "What happens when a company receives a supplier invoice that doesn't match what was ordered? "
            "In accounts payable, invoices, purchase orders, and receiving logs constantly arrive with discrepancies: "
            "price overcharges, quantity shortages, or tax variances. "
            "Traditional ERP systems easily flag the math mismatch. But detecting an exception is only half the battle. "
            "The hardest part is deciding what to do next: "
            "Has this supplier billed this way before? Did an authorized manager negotiate a waiver? "
            "And is that previous approval still valid under current company procurement policy?"
        ),
    },
    {
        "id": "scene2_innovation",
        "title": "Our Insight & Innovation",
        "text": (
            "That's why we built LedgerMind. "
            "An invoice exception isn't just a math error—it's an operational decision requiring context, precedent, and accountability. "
            "LedgerMind combines deterministic three-way matching with persistent institutional memory powered by Hindsight, "
            "version-governed policy evaluation, and fast Groq inference. "
            "Our central innovation: LedgerMind never blindly follows history. "
            "It cross-examines remembered precedents against the company's governing procurement rules. "
            "When past habit conflicts with policy, policy constraints govern, and the reviewer is alerted. "
            "This policy-versus-precedent intelligence is LedgerMind's core breakthrough."
        ),
    },
    {
        "id": "scene3a_intake",
        "title": "New Invoice Intake & 3-Way Match",
        "text": (
            "Here in the live application, the Overview tracks six discrepancy categories across twenty benchmark scenarios. "
            "Both our local Hindsight vector engine and SQLite operational database are online and healthy. "
            "Through New Invoice Intake, teams can create or import new invoices. "
            "Here we submit an invoice for Nova Tech Supplies: invoice INV-NOVA-2025-002. "
            "The purchase order specified one thousand rupees, but the vendor billed eleven hundred across ten units. "
            "With eighteen percent GST, LedgerMind instantly calculates a discrepancy of eleven hundred and eighty rupees, "
            "and syncs it immediately to SQLite and the active Invoice Queue."
        ),
    },
    {
        "id": "scene3b_workbench",
        "title": "Resolution Workbench & Human Review",
        "text": (
            "In the Resolution Workbench, LedgerMind evaluates the discrepancy. "
            "With memory enabled, the agent checks governing policy POL-AP-002 and identifies that price variances exceeding contract rates require line-item adjustment. "
            "LedgerMind generates an EDITED proposal, resetting unit rates to the contract price. "
            "Crucially, the human reviewer retains full authority. We submit our review as an authorized AP Specialist. "
            "The decision, adjusted amount, and audit rationale are permanently saved to both SQLite and persistent Hindsight memory."
        ),
    },
    {
        "id": "scene4_hindsight",
        "title": "Hindsight Memory & Live Provenance",
        "text": (
            "Look closely at our Hindsight vector memory integration. "
            "For invoice INV-PI-2025-101 from Prabhav Infosystems, Hindsight performs live semantic recall. "
            "Notice the storage badge: every card displays 'Hindsight Vector DB' with verified live provenance. "
            "Our multi-pass evidence deduplication consolidates sub-facts from a single Zenith review into one card, "
            "preserving slots for direct Prabhav precedents. "
            "Cross-vendor precedents are clearly flagged with orange badges, while the invoice's own historical review is excluded from confidence scoring. "
            "In our Memory Comparison view, Memory OFF yields zero context, while Memory ON boosts confidence to seventy-five percent, grounded in three consistent prior decisions."
        ),
    },
    {
        "id": "scene5_differentiator",
        "title": "Why LedgerMind is Different",
        "text": (
            "Most enterprise tools stop at finding where the numbers don't add up. "
            "LedgerMind's value is in helping a human reviewer understand what the organization learned before, "
            "whether that precedent is still valid, and why a specific resolution is justified right now. "
            "It unites historical recall, policy conflict detection, explainable evidence, and human accountability into a coherent decision workflow."
        ),
    },
    {
        "id": "scene6_conclusion",
        "title": "Technical Lessons & The Road Ahead",
        "text": (
            "Building LedgerMind taught us a key architectural lesson: never interleave blocking health probes into asynchronous vector queries, "
            "and keep supplier tag taxonomies strictly isolated from corporate legal stopwords. "
            "Today, LedgerMind is a working prototype with manual and CSV intake. In the future, we envision native ERP connectors, automated OCR, and enterprise role-based access. "
            "LedgerMind helps finance teams move from detecting invoice exceptions to making consistent, policy-backed decisions. "
            "Thank you."
        ),
    },
]


async def generate_all_audio():
    print(f"Generating narration using voice: {VOICE}...")
    audio_info = []

    for idx, scene in enumerate(SCENES, 1):
        out_file = AUDIO_DIR / f"{scene['id']}.mp3"
        print(f"[{idx}/{len(SCENES)}] Generating {scene['id']}...")
        
        communicate = edge_tts.Communicate(scene["text"], voice=VOICE, rate="+14%", pitch="+0Hz")
        await communicate.save(str(out_file))

        # Probe duration using ffmpeg
        cmd = [
            FFMPEG_EXE,
            "-i", str(out_file),
            "-f", "null",
            "-"
        ]
        res = subprocess.run(cmd, stderr=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        # Parse time from stderr e.g. time=00:00:32.45
        import re
        dur_matches = re.findall(r"time=(\d+):(\d+):(\d+\.\d+)", res.stderr)
        if dur_matches:
            h, m, s = dur_matches[-1]
            duration = float(h) * 3600 + float(m) * 60 + float(s)
        else:
            duration = 30.0

        audio_info.append({
            "id": scene["id"],
            "title": scene["title"],
            "path": str(out_file),
            "duration": round(duration, 2),
            "text": scene["text"],
        })
        print(f"  ✓ Saved {out_file.name} (Duration: {duration:.2f}s)")

    total_duration = sum(item["duration"] for item in audio_info)
    print(f"\nTotal Narration Duration: {total_duration:.2f} seconds ({total_duration/60:.2f} minutes)")

    manifest_file = AUDIO_DIR / "manifest.json"
    with open(manifest_file, "w", encoding="utf-8") as f:
        json.dump(audio_info, f, indent=2)
    print(f"Saved audio manifest to {manifest_file}")


if __name__ == "__main__":
    asyncio.run(generate_all_audio())
