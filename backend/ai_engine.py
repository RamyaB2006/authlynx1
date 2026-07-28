import os
import io
import traceback
import subprocess
import cv2
import torch
import torch.nn as nn
import torchvision.transforms as T
import torchvision.models as tv_models
import torchaudio.transforms as AT
import soundfile as sf
import numpy as np
from PIL import Image
from facenet_pytorch import MTCNN


# ----------------------------------------------------------------------
# Voice spoof classifier - architecture copied verbatim from
# scripts/train_voice_model.py so the state_dict loads cleanly.
# Output classes: 0 = bonafide/genuine, 1 = replay, 2 = AI-generated.
# ----------------------------------------------------------------------
class VoiceSpoofCNN(nn.Module):
    def __init__(self):
        super(VoiceSpoofCNN, self).__init__()
        self.conv = nn.Sequential(
            nn.Conv2d(1, 16, kernel_size=3, padding=1),
            nn.BatchNorm2d(16),
            nn.ReLU(),
            nn.MaxPool2d(2, 2),
            nn.Conv2d(16, 32, kernel_size=3, padding=1),
            nn.BatchNorm2d(32),
            nn.ReLU(),
            nn.MaxPool2d(2, 2)
        )
        self.fc = nn.Sequential(
            nn.AdaptiveAvgPool2d((1, 1)),
            nn.Flatten(),
            nn.Linear(32, 64),
            nn.ReLU(),
            nn.Linear(64, 3)
        )

    def forward(self, x):
        return self.fc(self.conv(x))


class AIEngine:
    # Trained weight paths - relative to backend/ (where main.py runs from)
    DEEPFAKE_MODEL_PATH = os.path.join("trained_models", "deepfake_mobilenetv3.pth")
    VOICE_SPOOF_MODEL_PATH = os.path.join("trained_models", "voice_spoof_cnn.pth")

    def __init__(self):
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        print(f"[INFO] Initializing AIEngine inference on device: {self.device}")

        # --- Voiceprint feature extractor (face/voice MATCHING at login -
        # unrelated to spoof DETECTION below, left exactly as before) ---
        self.mfcc_transform = AT.MelSpectrogram(
            sample_rate=16000,
            n_mels=40,
            n_fft=400,
            hop_length=160
        ).to(self.device)

        haarcascade_path = cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'  # type: ignore
        self.face_cascade = cv2.CascadeClassifier(haarcascade_path)

        self._resamplers = {}

        # ------------------------------------------------------------
        # Real trained deepfake video/image classifier
        # (torchvision mobilenet_v3_small, classifier[3] -> Linear(*, 2))
        # ------------------------------------------------------------
        self.mtcnn = MTCNN(keep_all=False, select_largest=True, post_process=False, device=self.device)

        self.deepfake_transform = T.Compose([
            T.Resize((224, 224)),
            T.ToTensor(),
            T.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])
        ])

        self.deepfake_model = tv_models.mobilenet_v3_small(weights=None)
        in_features = int(getattr(self.deepfake_model.classifier[3], "in_features"))
        self.deepfake_model.classifier[3] = nn.Linear(in_features, 2)
        self._load_state_dict_safely(self.deepfake_model, self.DEEPFAKE_MODEL_PATH, "deepfake_mobilenetv3")
        self.deepfake_model.to(self.device).eval()

        # ------------------------------------------------------------
        # Real trained voice spoof classifier (ASVspoof2019 LA)
        # ------------------------------------------------------------
        self.voice_spoof_mfcc_transform = AT.MFCC(
            sample_rate=16000,
            n_mfcc=40,
            melkwargs={"n_mels": 40, "n_fft": 400, "hop_length": 160, "mel_scale": "htk"}
        ).to(self.device)
        self.voice_spoof_target_samples = 48000  # exactly 3s @ 16kHz, matches training

        self.voice_spoof_model = VoiceSpoofCNN()
        self._load_state_dict_safely(self.voice_spoof_model, self.VOICE_SPOOF_MODEL_PATH, "voice_spoof_cnn")
        self.voice_spoof_model.to(self.device).eval()

        # Starting-point thresholds - only used for the behavioral heuristic
        # and the decision cutoff on top of the two trained models' fake
        # probability (both output a 0-1 probability; 50 is the natural
        # midpoint since training used CrossEntropyLoss with balanced
        # intent, not a heuristic guess like the old thresholds were).
        self.video_fake_decision_cutoff = 50.0
        self.audio_fake_decision_cutoff = 50.0

        # --- Speed knobs for video analysis ---
        self.video_target_samples = 8       # frames actually run through MTCNN+model
        self.video_max_decode_frames = 60   # hard cap on frames even read
        self.video_analysis_max_width = 400  # downscale before MTCNN detect (speed only; crop uses full-res frame)

    # ------------------------------------------------------------------
    # Model loading helper
    # ------------------------------------------------------------------
    def _load_state_dict_safely(self, model: nn.Module, rel_path: str, label: str):
        if not os.path.exists(rel_path):
            print(f"[ERROR] {label} weights not found at '{rel_path}'. "
                  f"Model will run with RANDOM (untrained) weights - predictions will be meaningless "
                  f"until this file is present.")
            return
        try:
            state_dict = torch.load(rel_path, map_location=self.device, weights_only=True)
        except Exception:
            # Older torch.save() checkpoints (or ones containing non-tensor
            # metadata) may not be loadable with weights_only=True.
            state_dict = torch.load(rel_path, map_location=self.device, weights_only=False)
        model.load_state_dict(state_dict)
        print(f"[INFO] Loaded {label} weights from '{rel_path}'")

    # ------------------------------------------------------------------
    # Audio format handling
    # ------------------------------------------------------------------
    def _convert_to_wav_bytes(self, input_bytes: bytes, suffix_hint: str = ".webm") -> bytes:
        """
        Converts arbitrary audio bytes (webm/opus from MediaRecorder, mp4/aac,
        etc.) into 16kHz mono WAV bytes using ffmpeg.
        """
        cmd = ["ffmpeg", "-y", "-i", "pipe:0", "-ar", "16000", "-ac", "1", "-f", "wav", "pipe:1"]
        try:
            result = subprocess.run(cmd, input=input_bytes, capture_output=True, timeout=15)
            if result.returncode == 0 and result.stdout:
                return result.stdout
        except subprocess.TimeoutExpired:
            pass

        # Fallback: temp-file based conversion
        in_path = f"temp_in_{os.urandom(4).hex()}{suffix_hint}"
        out_path = f"temp_out_{os.urandom(4).hex()}.wav"
        try:
            with open(in_path, "wb") as f:
                f.write(input_bytes)

            result = subprocess.run(
                ["ffmpeg", "-y", "-i", in_path, "-ar", "16000", "-ac", "1", out_path],
                capture_output=True,
                timeout=20
            )
            if result.returncode != 0 or not os.path.exists(out_path):
                stderr = result.stderr.decode(errors="ignore") if result.stderr else "unknown ffmpeg error"
                raise RuntimeError(f"ffmpeg conversion failed: {stderr}")

            with open(out_path, "rb") as f:
                return f.read()
        finally:
            for p in (in_path, out_path):
                if os.path.exists(p):
                    os.remove(p)

    def _read_audio_bytes(self, audio_bytes: bytes, suffix_hint: str = ".webm"):
        """Reads audio bytes into (numpy_array, sample_rate)."""
        suffix = (suffix_hint or "").lower()
        natively_decodable = suffix in (".wav", ".flac", ".ogg")

        if natively_decodable:
            try:
                return sf.read(io.BytesIO(audio_bytes))
            except Exception:
                pass  # fall through to ffmpeg

        wav_bytes = self._convert_to_wav_bytes(audio_bytes, suffix_hint=suffix_hint)
        return sf.read(io.BytesIO(wav_bytes))

    # ------------------------------------------------------------------
    # Voice preprocessing - makes registration and login clips comparable
    # (used for the voiceprint/matching path only, not spoof detection)
    # ------------------------------------------------------------------
    def _trim_silence(self, audio_np: np.ndarray, sr: int, frame_ms: int = 20,
                       energy_percentile: float = 55.0) -> np.ndarray:
        if audio_np.ndim > 1:
            mono = audio_np.mean(axis=1)
        else:
            mono = audio_np

        frame_len = max(1, int(sr * frame_ms / 1000))
        n_frames = len(mono) // frame_len
        if n_frames < 3:
            return audio_np

        frames = mono[:n_frames * frame_len].reshape(n_frames, frame_len)
        energies = np.sqrt(np.mean(frames.astype(np.float64) ** 2, axis=1))

        if np.max(energies) <= 1e-9:
            return audio_np

        threshold = np.percentile(energies, energy_percentile)
        threshold = min(threshold, np.max(energies) * 0.5)
        voiced_frame_idx = np.where(energies >= threshold)[0]

        if len(voiced_frame_idx) == 0:
            return audio_np

        keep_mask = np.zeros(n_frames, dtype=bool)
        keep_mask[voiced_frame_idx] = True
        voiced = frames[keep_mask].reshape(-1)

        if audio_np.ndim > 1:
            trimmed = audio_np[:n_frames * frame_len].reshape(n_frames, frame_len, audio_np.shape[1])
            return trimmed[keep_mask].reshape(-1, audio_np.shape[1])
        return voiced

    def _normalize_amplitude(self, audio_np: np.ndarray, target_peak: float = 0.9) -> np.ndarray:
        peak = np.max(np.abs(audio_np))
        if peak <= 1e-9:
            return audio_np
        return (audio_np.astype(np.float64) * (target_peak / peak)).astype(np.float32)

    def detect_faces(self, cv2_img):
        """Fast single-image face COUNT - used for the 20s-window quick
        check as well as login (not for deepfake classification, which
        uses MTCNN separately below to match training preprocessing)."""
        try:
            if cv2_img is None:
                return 0
            h, w = cv2_img.shape[:2]
            if w > 480:
                scale = 480 / float(w)
                cv2_img = cv2.resize(cv2_img, (480, int(h * scale)))
            gray = cv2.cvtColor(cv2_img, cv2.COLOR_BGR2GRAY)
            faces = self.face_cascade.detectMultiScale(
                gray, scaleFactor=1.15, minNeighbors=5, minSize=(30, 30)
            )
            return len(faces)
        except Exception as e:
            print(f"[ERROR] Face detection failed: {e}")
            return 0

    def extract_face_embedding(self, cv2_img):
        try:
            rgb_img = cv2.cvtColor(cv2_img, cv2.COLOR_BGR2RGB)
            pil_img = Image.fromarray(rgb_img).resize((160, 160))

            transform = T.Compose([
                T.ToTensor(),
                T.Normalize(mean=[0.5, 0.5, 0.5], std=[0.5, 0.5, 0.5])
            ])

            tensor_img: torch.Tensor = transform(pil_img)  # type: ignore
            tensor_img = tensor_img.unsqueeze(0).to(self.device)

            flat_vector = tensor_img.view(-1).detach().cpu().numpy()
            embedding = [float(x) for x in flat_vector[:512]]
            return embedding
        except Exception as e:
            print(f"[ERROR] Face extraction failed: {e}")
            return None

    def extract_voice_features(self, audio_bytes, suffix_hint: str = ".webm"):
        try:
            audio_np, sr = self._read_audio_bytes(audio_bytes, suffix_hint=suffix_hint)

            trimmed = self._trim_silence(np.asarray(audio_np), sr)
            normalized = self._normalize_amplitude(trimmed)

            waveform = torch.tensor(normalized, dtype=torch.float32)
            if waveform.ndim == 1:
                waveform = waveform.unsqueeze(0)
            else:
                waveform = waveform.transpose(0, 1).mean(dim=0, keepdim=True)

            if sr != 16000:
                if sr not in self._resamplers:
                    self._resamplers[sr] = AT.Resample(orig_freq=sr, new_freq=16000).to(self.device)
                waveform = self._resamplers[sr](waveform.to(self.device))
            else:
                waveform = waveform.to(self.device)

            mel = self.mfcc_transform(waveform)
            log_mel = torch.log(mel + 1e-6)
            voice_print = log_mel.mean(dim=2).squeeze().cpu().tolist()

            if not isinstance(voice_print, list):
                voice_print = [voice_print]
            return voice_print
        except Exception as e:
            print(f"[ERROR] Voice extraction failed: {e}")
            return [0.0] * 40

    def compute_behavioral_score(self, typing_speed, hold_time, latency, rhythm, error_rate):
        # NOTE: kept as a heuristic on purpose - see project notes.
        # trained_models/behavioral_isolation_forest.pkl was fit on
        # synthetic np.random.normal() data (5 typing + 4 mouse features)
        # and the frontend only sends 5 randomly-generated typing metrics
        # with no real mouse tracking, so neither side of that model is
        # measuring anything real yet. Wiring it in would just swap one
        # placeholder for another while adding a shape mismatch (9 vs 5
        # features) that would crash at inference time. Revisit once
        # ContinuousAuth.jsx captures actual keystroke/mouse telemetry.
        speed_score = 100 - min(abs(typing_speed - 67.5) * 2, 100)
        hold_score = 100 - min(abs(hold_time - 85) * 2, 100)
        latency_score = 100 - min(abs(latency - 40) * 1.5, 100)
        rhythm_score = min(max(rhythm, 0.0), 1.0) * 100
        error_score = max(100 - error_rate * 40, 0)
        return float(np.clip(np.mean([speed_score, hold_score, latency_score, rhythm_score, error_score]), 0, 100))

    # ------------------------------------------------------------------
    # Deepfake video/image classification - real trained MobileNetV3
    # ------------------------------------------------------------------
    def _crop_face_pil(self, pil_img: Image.Image):
        """Runs MTCNN detection and returns the cropped face PIL image,
        matching FaceForensicsDataset._prepare_dataset()'s crop exactly
        (mtcnn.detect() for the box, then a plain PIL .crop() - no
        alignment/whitening, since the model trained on that raw crop)."""
        try:
            detection_result = self.mtcnn.detect(pil_img)
            boxes = detection_result[0]
        except Exception as e:
            print(f"[WARN] MTCNN detect failed: {e}")
            return None
        if boxes is None or len(boxes) == 0:
            return None
        b = boxes[0]
        box = (float(b[0]), float(b[1]), float(b[2]), float(b[3]))
        try:
            return pil_img.crop(box)
        except Exception as e:
            print(f"[WARN] Face crop failed: {e}")
            return None

    def _classify_face_crop(self, face_pil: Image.Image) -> float:
        """Runs one cropped face image through the trained model, returns
        fake probability in [0, 1] (softmax over the 2-class output,
        index 1 = fake per categories={'real':0,'fake':1} in training)."""
        tensor_img = self.deepfake_transform(face_pil.convert("RGB"))  # type: ignore
        tensor_img = tensor_img.unsqueeze(0).to(self.device)  # type: ignore
        with torch.no_grad():
            logits = self.deepfake_model(tensor_img)
            probs = torch.softmax(logits, dim=1)
        return float(probs[0, 1].item())

    def detect_deepfake(self, file_bytes, filename: str):
        try:
            path_lower = filename.lower()

            if path_lower.endswith(('.mp4', '.mov', '.avi', '.mkv', '.webm')) and not path_lower.endswith(
                    ('.wav', '.mp3', '.flac', '.m4a', '.ogg')):
                return self._analyze_video_bytes(file_bytes, path_lower)

            elif path_lower.endswith(('.wav', '.mp3', '.flac', '.m4a', '.ogg')):
                suffix = os.path.splitext(path_lower)[1] or ".wav"
                return self._analyze_audio_bytes(file_bytes, suffix_hint=suffix)

            elif path_lower.endswith(('.jpg', '.jpeg', '.png', '.webp')):
                return self._analyze_image_bytes(file_bytes)

            return {"is_fake": False, "real_percentage": 50.0, "fake_percentage": 50.0,
                    "debug_signals": {"note": "unrecognized_file_type"}}

        except Exception as e:
            print(f"[ERROR] Deepfake analysis failed for '{filename}': {e}")
            traceback.print_exc()
            return {
                "is_fake": False,
                "real_percentage": 50.0,
                "fake_percentage": 50.0,
                "debug_signals": {"note": f"analysis_error: {e}"},
            }

    def _analyze_image_bytes(self, file_bytes):
        nparr = np.frombuffer(file_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if img is None:
            return {"is_fake": False, "real_percentage": 50.0, "fake_percentage": 50.0,
                    "debug_signals": {"note": "image_decode_failed"}}

        rgb_img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        pil_img = Image.fromarray(rgb_img)

        face_crop = self._crop_face_pil(pil_img)
        if face_crop is None:
            return {"is_fake": False, "real_percentage": 50.0, "fake_percentage": 50.0,
                    "debug_signals": {"note": "no_face_detected"}}

        fake_prob = self._classify_face_crop(face_crop)
        fake_pct = round(fake_prob * 100, 1)
        return {
            "is_fake": fake_pct > self.video_fake_decision_cutoff,
            "real_percentage": round(100.0 - fake_pct, 1),
            "fake_percentage": fake_pct,
            "debug_signals": {"model": "deepfake_mobilenetv3", "frames_analyzed": 1},
        }

    def _analyze_video_bytes(self, file_bytes, path_lower):
        """Samples a handful of frames, runs each detected face crop through
        the trained MobileNetV3 classifier, and averages the fake
        probability across frames that had a detectable face."""
        ext = os.path.splitext(path_lower)[1] or ".mp4"
        temp_video = f"temp_sim_{os.urandom(4).hex()}{ext}"
        with open(temp_video, "wb") as f:
            f.write(file_bytes)

        try:
            cap = cv2.VideoCapture(temp_video)

            has_video = False
            if cap.isOpened():
                ret, first_frame = cap.read()
                if ret and first_frame is not None:
                    has_video = True
                    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)

            if not has_video:
                cap.release()
                return self._analyze_audio_bytes(file_bytes, suffix_hint=".webm")

            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
            if total_frames > 0:
                decode_limit = min(total_frames, self.video_max_decode_frames)
                skip = max(1, decode_limit // self.video_target_samples)
            else:
                decode_limit = self.video_max_decode_frames
                skip = 3

            fake_probs = []
            frame_idx = 0

            while cap.isOpened() and frame_idx < decode_limit and len(fake_probs) < self.video_target_samples:
                ret, frame = cap.read()
                if not ret:
                    break

                if frame_idx % skip == 0:
                    rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    pil_frame = Image.fromarray(rgb_frame)

                    face_crop = self._crop_face_pil(pil_frame)
                    if face_crop is not None:
                        try:
                            fake_probs.append(self._classify_face_crop(face_crop))
                        except Exception as e:
                            print(f"[WARN] Frame classification failed: {e}")

                frame_idx += 1

            cap.release()

            if len(fake_probs) == 0:
                return {"is_fake": False, "real_percentage": 50.0, "fake_percentage": 50.0,
                        "debug_signals": {"note": "no_face_detected", "frames_checked": frame_idx}}

            avg_fake_prob = float(np.mean(fake_probs))
            fake_pct = round(avg_fake_prob * 100, 1)
            real_pct = round(100.0 - fake_pct, 1)
            return {
                "is_fake": fake_pct > self.video_fake_decision_cutoff,
                "real_percentage": real_pct,
                "fake_percentage": fake_pct,
                "debug_signals": {
                    "model": "deepfake_mobilenetv3",
                    "frames_analyzed": len(fake_probs),
                    "per_frame_fake_prob": [round(p, 3) for p in fake_probs],
                },
            }
        finally:
            if os.path.exists(temp_video):
                os.remove(temp_video)

    # ------------------------------------------------------------------
    # Voice spoof classification - real trained VoiceSpoofCNN
    # ------------------------------------------------------------------
    def _analyze_audio_bytes(self, file_bytes, suffix_hint=".webm"):
        try:
            audio_np, sr = self._read_audio_bytes(file_bytes, suffix_hint=suffix_hint)
        except Exception as e:
            print(f"[ERROR] Audio decode failed: {e}")
            traceback.print_exc()
            return {"is_fake": False, "real_percentage": 50.0, "fake_percentage": 50.0,
                    "debug_signals": {"note": "audio_decode_failed"}}

        if len(audio_np) == 0:
            return {"is_fake": False, "real_percentage": 50.0, "fake_percentage": 50.0}

        try:
            waveform = torch.tensor(np.asarray(audio_np), dtype=torch.float32)
            if waveform.ndim == 1:
                waveform = waveform.unsqueeze(0)
            else:
                # stereo -> mono, matching training's torch.mean(dim=0, keepdim=True)
                waveform = waveform.transpose(0, 1).mean(dim=0, keepdim=True)

            if sr != 16000:
                if sr not in self._resamplers:
                    self._resamplers[sr] = AT.Resample(orig_freq=sr, new_freq=16000).to(self.device)
                waveform = self._resamplers[sr](waveform.to(self.device))
            else:
                waveform = waveform.to(self.device)

            # Pad/truncate to exactly 3s @ 16kHz (48000 samples) - matches
            # ASVspoofDataset.__getitem__ exactly.
            target_length = self.voice_spoof_target_samples
            if waveform.shape[1] < target_length:
                pad_amount = target_length - waveform.shape[1]
                waveform = torch.nn.functional.pad(waveform, (0, pad_amount))
            elif waveform.shape[1] > target_length:
                waveform = waveform[:, :target_length]

            mfcc = self.voice_spoof_mfcc_transform(waveform)
            mfcc = (mfcc - mfcc.mean()) / (mfcc.std() + 1e-8)
            mfcc = mfcc.unsqueeze(0)  # -> [batch=1, channel=1, n_mfcc, time]

            with torch.no_grad():
                logits = self.voice_spoof_model(mfcc)
                probs = torch.softmax(logits, dim=1)[0]

            # index 0 = bonafide/genuine; fake = anything else (replay or AI-generated)
            fake_prob = float(1.0 - probs[0].item())
            fake_pct = round(fake_prob * 100, 1)
            real_pct = round(100.0 - fake_pct, 1)

            predicted_class = int(torch.argmax(probs).item())
            class_names = {0: "bonafide", 1: "replay", 2: "ai_generated"}

            return {
                "is_fake": fake_pct > self.audio_fake_decision_cutoff,
                "real_percentage": real_pct,
                "fake_percentage": fake_pct,
                "debug_signals": {
                    "model": "voice_spoof_cnn",
                    "predicted_class": class_names.get(predicted_class, str(predicted_class)),
                    "class_probs": {class_names[i]: round(float(p), 3) for i, p in enumerate(probs.tolist())},
                },
            }
        except Exception as e:
            print(f"[ERROR] Voice spoof inference failed: {e}")
            traceback.print_exc()
            return {"is_fake": False, "real_percentage": 50.0, "fake_percentage": 50.0,
                    "debug_signals": {"note": f"voice_spoof_inference_error: {e}"}}