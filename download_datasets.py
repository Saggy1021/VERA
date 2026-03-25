"""
VERA — Dataset Downloader
Downloads the best freely available datasets for testing VERA features.
All datasets are free, no account needed (except Kaggle for FER2013).

Run this once:
    python download_datasets.py

Datasets downloaded:
  1. CREMA-D  — 7,442 audio-visual emotion clips (GitHub, direct)
  2. RAVDESS  — 2,452 video clips, 24 actors, 8 emotions (Zenodo, direct)
  3. CK+      — 593 expression sequences (Kaggle)
  4. Real-Life Trial Deception Dataset (University of Michigan)
  5. CMU-MOSI samples (opinion/sentiment)
"""

import os
import sys
import zipfile
import tarfile
import urllib.request
import shutil

BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
DATA_DIR    = os.path.join(BASE_DIR, "data", "vera_datasets")

os.makedirs(DATA_DIR, exist_ok=True)


# ──────────────────────────────────────────────────────────────────────
# Download helpers
# ──────────────────────────────────────────────────────────────────────

def progress_hook(count, block_size, total_size):
    pct = min(int(count * block_size * 100 / max(total_size, 1)), 100)
    bar = "█" * (pct // 5) + "░" * (20 - pct // 5)
    print(f"\r  [{bar}] {pct}%", end="", flush=True)


def download_file(url: str, dest_path: str, label: str = ""):
    if os.path.exists(dest_path):
        print(f"  ✅ Already downloaded: {os.path.basename(dest_path)}")
        return True
    print(f"  ⬇  Downloading {label or os.path.basename(dest_path)} ...")
    try:
        urllib.request.urlretrieve(url, dest_path, reporthook=progress_hook)
        print()
        return True
    except Exception as e:
        print(f"\n  ❌ Failed: {e}")
        return False


def extract_zip(zip_path: str, dest_dir: str):
    print(f"  📦 Extracting {os.path.basename(zip_path)} ...")
    with zipfile.ZipFile(zip_path, "r") as z:
        z.extractall(dest_dir)
    print("  ✅ Done.")


def extract_tar(tar_path: str, dest_dir: str):
    print(f"  📦 Extracting {os.path.basename(tar_path)} ...")
    with tarfile.open(tar_path) as t:
        t.extractall(dest_dir)
    print("  ✅ Done.")


# ──────────────────────────────────────────────────────────────────────
# 1. CREMA-D  (Crowd-sourced Emotional Multimodal Actors Dataset)
#    7,442 clips, 91 actors, 6 emotions: happy/sad/angry/fear/disgust/neutral
#    Use: emotion detection testing + audio-visual sync testing
# ──────────────────────────────────────────────────────────────────────
def download_cremad():
    print("\n[1/4] CREMA-D — Audio-Visual Emotion Dataset")
    dest = os.path.join(DATA_DIR, "CREMA-D")
    if os.path.exists(dest):
        print("  ✅ CREMA-D already present.")
        return

    try:
        import subprocess
        print("  Cloning CREMA-D from GitHub (~2 GB) — this may take a few minutes ...")
        subprocess.run([
            "git", "clone", "--depth", "1",
            "https://github.com/CheyneyComputerScience/CREMA-D.git",
            dest
        ], check=True)
        print("  ✅ CREMA-D cloned.")
    except Exception as e:
        print(f"  ⚠️  Git clone failed ({e}). Try manually:")
        print("     git clone https://github.com/CheyneyComputerScience/CREMA-D.git data/vera_datasets/CREMA-D")


# ──────────────────────────────────────────────────────────────────────
# 2. RAVDESS (Ryerson Audio-Visual Database of Emotional Speech and Song)
#    24 actors, 8 emotions, audio + video
#    Use: emotion testing, audio-visual sync, blink rate stress testing
#    Hosted on Zenodo — direct download
# ──────────────────────────────────────────────────────────────────────
def download_ravdess():
    print("\n[2/4] RAVDESS — Emotional Speech Video Dataset")
    dest_dir = os.path.join(DATA_DIR, "RAVDESS")
    os.makedirs(dest_dir, exist_ok=True)

    # Download video zip (Actor_01 as sample — full dataset is 24 actors)
    # Full dataset: https://zenodo.org/record/1188976 (~24 GB)
    # Sample (Actor 01 speech video — ~250 MB):
    url = "https://zenodo.org/record/1188976/files/Video_Speech_Actor_01.zip"
    zip_path = os.path.join(dest_dir, "RAVDESS_Actor01.zip")

    if download_file(url, zip_path, "RAVDESS Actor 01 videos"):
        extract_zip(zip_path, dest_dir)
        print("  ℹ️  Downloaded Actor 01 as sample.")
        print("     Full dataset (all 24 actors): https://zenodo.org/record/1188976")
    else:
        print("  ℹ️  Manual download: https://zenodo.org/record/1188976")


# ──────────────────────────────────────────────────────────────────────
# 3. Real Life Trial Deception Dataset (University of Michigan)
#    121 clips, truth/lie labeled, real court trial footage
#    Use: deception scoring validation
# ──────────────────────────────────────────────────────────────────────
def download_real_life_trial():
    print("\n[3/4] Real-Life Trial Dataset — Deception Detection")
    dest_dir = os.path.join(DATA_DIR, "RealLifeTrial")
    os.makedirs(dest_dir, exist_ok=True)

    url = "https://web.eecs.umich.edu/~mihalcea/downloads/RealLifeDeceptionDetection.2016.zip"
    zip_path = os.path.join(dest_dir, "RealLifeDeception.zip")

    if download_file(url, zip_path, "Real Life Trial Deception Dataset"):
        extract_zip(zip_path, dest_dir)
    else:
        print("  ℹ️  Manual download: https://web.eecs.umich.edu/~mihalcea/downloads/")
        print("     File: RealLifeDeceptionDetection.2016.zip")


# ──────────────────────────────────────────────────────────────────────
# 4. FER2013 via Kaggle (Facial Expression Recognition)
#    35,887 grayscale 48×48 images, 7 emotions
#    Use: emotion model testing / fine-tuning
# ──────────────────────────────────────────────────────────────────────
def download_fer2013():
    print("\n[4/4] FER2013 — Facial Expression Dataset (Kaggle)")
    dest_dir = os.path.join(DATA_DIR, "FER2013")

    if os.path.exists(dest_dir):
        print("  ✅ FER2013 already present.")
        return

    try:
        import kaggle
        os.makedirs(dest_dir, exist_ok=True)
        print("  Downloading via Kaggle API...")
        kaggle.api.authenticate()
        kaggle.api.dataset_download_files(
            "msambare/fer2013",
            path=dest_dir,
            unzip=True
        )
        print("  ✅ FER2013 downloaded.")
    except ImportError:
        print("  ⚠️  kaggle package not installed. Run: pip install kaggle")
        print("     Then set up ~/.kaggle/kaggle.json with your API key.")
        print("     Manual: https://www.kaggle.com/datasets/msambare/fer2013")
    except Exception as e:
        print(f"  ⚠️  Kaggle download error: {e}")
        print("     Manual: https://www.kaggle.com/datasets/msambare/fer2013")


# ──────────────────────────────────────────────────────────────────────
# Quick test helper — verify videos open correctly
# ──────────────────────────────────────────────────────────────────────
def test_downloaded_data():
    print("\n──── Testing downloaded data ────")
    import cv2

    tested = 0
    for root, dirs, files in os.walk(DATA_DIR):
        for f in files:
            if f.lower().endswith((".mp4", ".avi", ".flv", ".mov", ".mpg", ".mpeg")):
                vpath = os.path.join(root, f)
                cap = cv2.VideoCapture(vpath)
                ok = cap.isOpened()
                frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
                cap.release()
                status = "✅" if ok else "❌"
                print(f"  {status} {os.path.relpath(vpath, DATA_DIR)} ({frames} frames)")
                tested += 1
                if tested >= 10:
                    print("  ... (showing first 10 videos)")
                    return

    if tested == 0:
        print("  No video files found yet.")


# ──────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 60)
    print("  VERA — Dataset Downloader")
    print(f"  Saving to: {DATA_DIR}")
    print("=" * 60)

    args = sys.argv[1:]

    if not args or "crema" in args:
        download_cremad()

    if not args or "ravdess" in args:
        download_ravdess()

    if not args or "trial" in args:
        download_real_life_trial()

    if not args or "fer" in args:
        download_fer2013()

    if "--test" in sys.argv:
        test_downloaded_data()

    print("\n" + "=" * 60)
    print("  Download complete!")
    print(f"  Data location: {DATA_DIR}")
    print("=" * 60)
    print("""
  Usage in VERA:
    from vera.vera_pipeline import VERAPipeline
    pipeline = VERAPipeline(context="interview")
    result = pipeline.analyze_video_file("data/vera_datasets/RAVDESS/video.mp4")
    print(result["summary"])
    """)
