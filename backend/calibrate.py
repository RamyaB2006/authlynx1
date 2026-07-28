"""
Run this against a folder of labeled sample clips to get thresholds that
actually separate real from fake for YOUR dataset, instead of the
hand-guessed defaults in ai_engine.py.

Usage:
    python calibrate.py --real ./samples/real --fake ./samples/fake

Folder structure expected:
    samples/real/*.mp4  (or .mov/.avi/.mkv/.webm)
    samples/fake/*.mp4

Prints the calibrated sharpness threshold, jitter threshold, and the
direction each should score in. Paste the printed values into
ai_engine.py's __init__.
"""
import argparse
import glob
import os
from ai_engine import AIEngine


def extract_video_signals(engine: AIEngine, path: str):
    """Runs the same per-frame signal extraction _analyze_video_bytes uses,
    but returns the raw (avg_sharpness, jitter) numbers instead of a
    fake/real verdict, so we can feed them into calibrate_threshold()."""
    with open(path, "rb") as f:
        file_bytes = f.read()
    result = engine.detect_deepfake(file_bytes, os.path.basename(path))
    signals = result.get("debug_signals", {})
    return signals.get("avg_sharpness"), signals.get("jitter")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--real", required=True, help="Folder of known-real clips")
    parser.add_argument("--fake", required=True, help="Folder of known-fake clips")
    args = parser.parse_args()

    engine = AIEngine()
    exts = ("*.mp4", "*.mov", "*.avi", "*.mkv", "*.webm")

    real_files = [f for ext in exts for f in glob.glob(os.path.join(args.real, ext))]
    fake_files = [f for ext in exts for f in glob.glob(os.path.join(args.fake, ext))]

    if not real_files or not fake_files:
        print(f"Found {len(real_files)} real and {len(fake_files)} fake files. Need at least a few of each.")
        return

    real_sharpness, real_jitter = [], []
    fake_sharpness, fake_jitter = [], []

    for path in real_files:
        sharp, jit = extract_video_signals(engine, path)
        if sharp is not None:
            real_sharpness.append(sharp)
            real_jitter.append(jit)
        else:
            print(f"[WARN] Could not extract signals from {path} (no face detected across sampled frames?)")

    for path in fake_files:
        sharp, jit = extract_video_signals(engine, path)
        if sharp is not None:
            fake_sharpness.append(sharp)
            fake_jitter.append(jit)
        else:
            print(f"[WARN] Could not extract signals from {path} (no face detected across sampled frames?)")

    print(f"\nUsable samples: {len(real_sharpness)} real, {len(fake_sharpness)} fake\n")

    if len(real_sharpness) < 3 or len(fake_sharpness) < 3:
        print("Too few usable samples to calibrate reliably - add more clips per class.")
        return

    print("=== SHARPNESS ===")
    print(f"real:  min={min(real_sharpness):.1f}  max={max(real_sharpness):.1f}  avg={sum(real_sharpness)/len(real_sharpness):.1f}")
    print(f"fake:  min={min(fake_sharpness):.1f}  max={max(fake_sharpness):.1f}  avg={sum(fake_sharpness)/len(fake_sharpness):.1f}")
    sharp_threshold, sharp_direction = engine.calibrate_threshold(real_sharpness, fake_sharpness)
    print(f"-> video_sharpness_threshold = {sharp_threshold:.1f}   (direction: {sharp_direction})\n")

    print("=== JITTER ===")
    print(f"real:  min={min(real_jitter):.2f}  max={max(real_jitter):.2f}  avg={sum(real_jitter)/len(real_jitter):.2f}")
    print(f"fake:  min={min(fake_jitter):.2f}  max={max(fake_jitter):.2f}  avg={sum(fake_jitter)/len(fake_jitter):.2f}")
    jitter_threshold, jitter_direction = engine.calibrate_threshold(real_jitter, fake_jitter)
    print(f"-> video_jitter_threshold = {jitter_threshold:.2f}   (direction: {jitter_direction})\n")

    print("Paste the two threshold values above into AIEngine.__init__ in ai_engine.py.")
    print("If a direction printed as 'below_is_fake' instead of the code's assumed 'above_is_fake'")
    print("(sharpness) or vice versa (jitter), the above_is_fake flag in _sigmoid_score's call")
    print("for that signal needs to be flipped too - let me know if that happens.")


if __name__ == "__main__":
    main()