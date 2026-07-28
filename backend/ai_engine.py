import os
import io
import traceback
import subprocess
import cv2
import torch
import torchvision.transforms as T
import torchaudio.transforms as AT
import soundfile as sf
import numpy as np
from PIL import Image


class AIEngine:
    def __init__(self):
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        print(f"[INFO] Initializing AIEngine inference on device: {self.device}")

        self.mfcc_transform = AT.MelSpectrogram(
            sample_rate=16000,
            n_mels=40,
            n_fft=400,
            hop_length=160
        ).to(self.device)

        haarcascade_path = cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'  # type: ignore
        self.face_cascade = cv2.CascadeClassifier(haarcascade_path)

        # Cache resamplers per source sample rate instead of rebuilding the
        # FIR filter design on every single request (was a needless per-call
        # cost, even though in practice sr is usually already 16000 by the
        # time it gets here since ffmpeg already resamples during conversion).
        self._resamplers = {}

        # Starting-point thresholds only - see calibrate_threshold().
        self.video_sharpness_threshold = 60.0
        self.video_jitter_threshold = 18.0
        self.audio_variance_threshold = 0.005
        self.audio_flatness_threshold = 0.45
        self.video_fake_decision_cutoff = 50.0
        self.audio_fake_decision_cutoff = 50.0
        self.sensitivity = 2.5

        # --- Speed knobs for simulate-attack video analysis ---
        self.video_target_samples = 10     # frames actually run through face cascade
        self.video_max_decode_frames = 60  # hard cap on frames even read, bounds worst-case time
        self.video_analysis_max_width = 400  # downscale before detection

    # ------------------------------------------------------------------
    # Audio format handling
    # ------------------------------------------------------------------
    def _convert_to_wav_bytes(self, input_bytes: bytes, suffix_hint: str = ".webm") -> bytes:
        """
        Converts arbitrary audio bytes (webm/opus from MediaRecorder, mp4/aac,
        etc.) into 16kHz mono WAV bytes using ffmpeg.

        FIX (speed): previously wrote the input to disk, ran ffmpeg file->file,
        then read the output back from disk (2 writes + 2 reads + 2 deletes
        per call). Now pipes bytes directly through ffmpeg's stdin/stdout -
        no temp files at all in the common case. Falls back to the old
        temp-file approach only if the pipe conversion fails (some containers
        like certain .m4a/.mp4 files need a seekable input for a trailing
        moov atom, which a pipe can't provide).
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
        """
        Reads audio bytes into (numpy_array, sample_rate).

        FIX (speed): reads happen fully in-memory (io.BytesIO) instead of
        writing a "probe" temp file to disk first. Also skips the doomed
        soundfile attempt entirely for formats libsndfile can never decode
        (webm/opus/mp3/m4a) instead of trying-and-failing first - goes
        straight to ffmpeg for those.
        """
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

    def calibrate_threshold(self, real_values, fake_values):
        real_values = np.array(real_values, dtype=np.float64)
        fake_values = np.array(fake_values, dtype=np.float64)
        candidates = np.unique(np.concatenate([real_values, fake_values]))

        best_j = -1.0
        best_threshold = float(np.median(candidates))
        best_direction = "above_is_fake"

        for t in candidates:
            tpr_a = np.mean(fake_values > t) if len(fake_values) else 0.0
            fpr_a = np.mean(real_values > t) if len(real_values) else 0.0
            j_a = tpr_a - fpr_a

            tpr_b = np.mean(fake_values <= t) if len(fake_values) else 0.0
            fpr_b = np.mean(real_values <= t) if len(real_values) else 0.0
            j_b = tpr_b - fpr_b

            if j_a >= j_b and j_a > best_j:
                best_j, best_threshold, best_direction = j_a, float(t), "above_is_fake"
            elif j_b > j_a and j_b > best_j:
                best_j, best_threshold, best_direction = j_b, float(t), "below_is_fake"

        print(f"[CALIBRATION] threshold={best_threshold}, direction={best_direction}, J={best_j:.3f}")
        return best_threshold, best_direction

    def detect_faces(self, cv2_img):
        """Fast single-image face count - used for the 20s-window quick
        check as well as login. Downscales large frames first since Haar
        cascade cost scales with pixel count and webcam frames don't need
        full resolution for a simple count."""
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

    # ------------------------------------------------------------------
    # Scoring helpers
    # ------------------------------------------------------------------
    def _sigmoid_score(self, value, threshold, sensitivity, above_is_fake=True):
        safe_threshold = threshold if abs(threshold) > 1e-9 else 1e-9
        normalized_diff = (value - safe_threshold) / abs(safe_threshold)
        if not above_is_fake:
            normalized_diff = -normalized_diff
        return float(1.0 / (1.0 + np.exp(-sensitivity * normalized_diff)))

    def _face_temporal_jitter(self, face_variances):
        if len(face_variances) < 2:
            return 0.0
        deltas = np.diff(np.array(face_variances, dtype=np.float64))
        return float(np.std(deltas))

    def _spectral_flatness(self, audio_np, sr):
        if audio_np.ndim > 1:
            audio_np = audio_np.mean(axis=1)
        spectrum = np.abs(np.fft.rfft(audio_np.astype(np.float64)))
        spectrum = spectrum[spectrum > 1e-12]
        if len(spectrum) == 0:
            return 0.0
        geo_mean = np.exp(np.mean(np.log(spectrum)))
        arith_mean = np.mean(spectrum)
        if arith_mean <= 1e-12:
            return 0.0
        return float(geo_mean / arith_mean)

    def compute_behavioral_score(self, typing_speed, hold_time, latency, rhythm, error_rate):
        speed_score = 100 - min(abs(typing_speed - 67.5) * 2, 100)
        hold_score = 100 - min(abs(hold_time - 85) * 2, 100)
        latency_score = 100 - min(abs(latency - 40) * 1.5, 100)
        rhythm_score = min(max(rhythm, 0.0), 1.0) * 100
        error_score = max(100 - error_rate * 40, 0)
        return float(np.clip(np.mean([speed_score, hold_score, latency_score, rhythm_score, error_score]), 0, 100))

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

        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        laplacian = cv2.Laplacian(gray, cv2.CV_64F)
        lap_arr = np.asarray(laplacian, dtype=np.float32)
        img_var = float(np.var(lap_arr))

        fake_prob = self._sigmoid_score(img_var, 60.0, sensitivity=self.sensitivity, above_is_fake=False)
        fake_pct = round(fake_prob * 100, 1)
        return {
            "is_fake": fake_pct > self.video_fake_decision_cutoff,
            "real_percentage": round(100.0 - fake_pct, 1),
            "fake_percentage": fake_pct,
            "debug_signals": {"laplacian_var": img_var},
        }

    def _analyze_video_bytes(self, file_bytes, path_lower):
        """
        FIX (speed): previously decoded and ran the face cascade on up to 30
        FULL-RESOLUTION frames sequentially from the start of the file only -
        slow, and only covered the first couple seconds of longer clips.
        Now: downscales before detection, and evenly samples a small target
        number of frames across a bounded window instead of brute-forcing
        every frame - typically an order of magnitude faster while covering
        more of the clip.
        """
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

            face_variances = []
            frame_idx = 0

            while cap.isOpened() and frame_idx < decode_limit and len(face_variances) < self.video_target_samples:
                ret, frame = cap.read()
                if not ret:
                    break

                if frame_idx % skip == 0:
                    h, w = frame.shape[:2]
                    if w > self.video_analysis_max_width:
                        scale = self.video_analysis_max_width / float(w)
                        frame = cv2.resize(frame, (self.video_analysis_max_width, int(h * scale)))

                    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                    faces = self.face_cascade.detectMultiScale(gray, 1.15, 4, minSize=(30, 30))
                    for (x, y, w2, h2) in faces:
                        face_roi = gray[y:y + h2, x:x + w2]
                        laplacian = cv2.Laplacian(face_roi, cv2.CV_64F)
                        lap_arr = np.asarray(laplacian, dtype=np.float32)
                        face_variances.append(float(np.var(lap_arr)))
                        break

                frame_idx += 1

            cap.release()

            if len(face_variances) >= 2:
                avg_sharpness = float(np.mean(face_variances))
                jitter = self._face_temporal_jitter(face_variances)

                sharpness_fake_score = self._sigmoid_score(
                    avg_sharpness, self.video_sharpness_threshold,
                    sensitivity=self.sensitivity, above_is_fake=False
                )
                jitter_fake_score = self._sigmoid_score(
                    jitter, self.video_jitter_threshold,
                    sensitivity=self.sensitivity, above_is_fake=True
                )
                fake_prob = 0.4 * sharpness_fake_score + 0.6 * jitter_fake_score
                fake_pct = round(fake_prob * 100, 1)
                real_pct = round(100.0 - fake_pct, 1)
                return {
                    "is_fake": fake_pct > self.video_fake_decision_cutoff,
                    "real_percentage": real_pct,
                    "fake_percentage": fake_pct,
                    "debug_signals": {"avg_sharpness": avg_sharpness, "jitter": jitter,
                                       "frames_analyzed": len(face_variances)},
                }

            if len(face_variances) == 1:
                fake_prob = self._sigmoid_score(
                    face_variances[0], self.video_sharpness_threshold,
                    sensitivity=self.sensitivity * 0.5, above_is_fake=False
                )
                fake_pct = round(fake_prob * 100, 1)
                return {
                    "is_fake": fake_pct > self.video_fake_decision_cutoff,
                    "real_percentage": round(100.0 - fake_pct, 1),
                    "fake_percentage": fake_pct,
                    "debug_signals": {"note": "low_confidence_single_frame"},
                }

            return {"is_fake": False, "real_percentage": 50.0, "fake_percentage": 50.0,
                    "debug_signals": {"note": "no_face_detected", "frames_checked": frame_idx}}
        finally:
            if os.path.exists(temp_video):
                os.remove(temp_video)

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

        audio_var = float(np.var(audio_np))
        flatness = self._spectral_flatness(np.asarray(audio_np), sr)

        variance_fake_score = self._sigmoid_score(
            audio_var, self.audio_variance_threshold, sensitivity=self.sensitivity, above_is_fake=False
        )
        flatness_fake_score = self._sigmoid_score(
            flatness, self.audio_flatness_threshold, sensitivity=self.sensitivity, above_is_fake=True
        )

        fake_prob = 0.4 * variance_fake_score + 0.6 * flatness_fake_score
        fake_pct = round(fake_prob * 100, 1)
        real_pct = round(100.0 - fake_pct, 1)
        return {
            "is_fake": fake_pct > self.audio_fake_decision_cutoff,
            "real_percentage": real_pct,
            "fake_percentage": fake_pct,
            "debug_signals": {"audio_var": audio_var, "flatness": flatness},
        }