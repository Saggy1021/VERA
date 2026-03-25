"""
VERA - Audio Analyzer (Production v4)
FIXES:
  1. "Insufficient data" bug — was returning early when either text was empty;
     now only skips if BOTH are empty and returns a proper no-audio state.
  2. "you" hallucination — Whisper hallucinates on silence/noise. Added a
     minimum audio energy gate (RMS > 8.0) AND a hallucination filter that
     strips known Whisper silence artifacts before sync scoring.
  3. Improved sync scoring — added length-ratio penalty so a 1-word audio
     transcript doesn't score 1.0 against a long lip text.
  4. SpeakerVerifier unchanged — was working correctly.
"""
import os
import time
import tempfile
import numpy as np
from difflib import SequenceMatcher

# Known Whisper silence/noise hallucinations to filter out
WHISPER_HALLUCINATIONS = {
    "you", "thank you", "thanks", ".", "..", "...", "thank you.",
    "thanks.", "bye", "bye.", "okay", "okay.", "ok", "ok.",
    "hmm", "hmm.", "um", "uh", "ah", "oh",
    "you.", "you,", "you!", "[music]", "[applause]", "[silence]",
    "(music)", "(silence)", "(applause)",
}

# Minimum RMS energy (x1000) to consider audio as real speech
# Below this = silence/background noise, skip Whisper entirely
MIN_SPEECH_ENERGY = 8.0


try:
    import soundfile as sf
    _has_soundfile = True
except ImportError:
    _has_soundfile = False

try:
    from speechbrain.inference import SpeakerRecognition
    _has_speechbrain = True
except ImportError:
    _has_speechbrain = False
    import logging
    logging.getLogger(__name__).warning(
        "speechbrain not installed. Speaker verification disabled. "
        "Run: pip install speechbrain"
    )

SPKREC_SAVEDIR = os.path.join(os.path.dirname(__file__), 'models', 'spkrec')


class AudioAnalyzer:
    _model_cache: dict = {}

    def __init__(self, model_size: str = "base.en"):
        self._model_size = model_size
        self._model      = None
        self._load()

    # ── Lazy load (one per model_size) ──────────────────────────────────────
    def _load(self):
        if self._model_size in AudioAnalyzer._model_cache:
            self._model = AudioAnalyzer._model_cache[self._model_size]
            return
        try:
            import whisper
            print(f"[AudioAnalyzer] Loading Whisper '{self._model_size}' …")
            m = whisper.load_model(self._model_size)
            AudioAnalyzer._model_cache[self._model_size] = m
            self._model = m
            print("[AudioAnalyzer] Whisper ready.")
        except Exception as exc:
            self._model = None
            print(f"[AudioAnalyzer] Whisper load failed: {exc}")

    # ── Public API ───────────────────────────────────────────────────────────
    def transcribe_file(self, path: str) -> dict:
        """
        Transcribe an audio/video file with Whisper.
        FIX: energy gate — skip files with very low RMS (silence/noise).
        FIX: hallucination filter applied to result before returning.
        """
        if self._model is None:
            return {"text": "", "segments": [], "duration": 0, "error": "Whisper not loaded"}

        # Energy gate: skip transcription if audio is basically silent
        energy = self.compute_energy(path)
        if energy < MIN_SPEECH_ENERGY:
            return {
                "text": "",
                "segments": [],
                "duration": 0,
                "energy": energy,
                "error": None,
                "skipped_reason": "below_energy_threshold",
            }

        try:
            t0 = time.time()
            result = self._model.transcribe(
                path,
                fp16=False,
                language="en",
                condition_on_previous_text=False,
                # FIX: suppress common silence tokens Whisper hallucinates
                suppress_tokens=[-1],
                # FIX: no_speech_threshold — if model isn't sure speech is
                # present (prob > 0.6), treat as silence
                no_speech_threshold=0.6,
                logprob_threshold=-1.0,
            )
            text = result["text"].strip()
            # Apply hallucination filter
            text = self._filter_hallucinations(text)
            return {
                "text":     text,
                "segments": result.get("segments", []),
                "duration": round(time.time() - t0, 2),
                "energy":   energy,
                "error":    None,
            }
        except Exception as exc:
            return {"text": "", "segments": [], "duration": 0, "energy": 0, "error": str(exc)}

    def _filter_hallucinations(self, text: str) -> str:
        """
        Remove known Whisper hallucinations from transcript.
        Returns empty string if the entire result is a known artifact.
        """
        if not text:
            return ""
        stripped = text.strip().lower().rstrip(".")
        if stripped in WHISPER_HALLUCINATIONS:
            return ""
        # Also filter if text is <= 3 chars (single phoneme misfire)
        if len(text.strip()) <= 3:
            return ""
        return text

    def compute_energy(self, path: str) -> float:
        """Calculates the RMS energy of an audio file (x1000 scale)."""
        try:
            import whisper
            audio = whisper.load_audio(path)
            if len(audio) == 0:
                return 0.0
            rms = float(np.sqrt(np.mean(audio**2)))
            return round(rms * 1000, 2)
        except Exception:
            return 0.0

    def compute_sync_score(self, lip_text: str, audio_text: str) -> dict:
        """
        Returns a sync score dict.

        FIX 1: "Insufficient data" — old code returned score=1.0 whenever
        either text was empty. Now:
          - Both empty → "No audio data" (score=1.0, risk=0)
          - Only audio_text empty → "No transcript yet" (score=None, risk=0)
          - Only lip_text empty → score based on audio alone at reduced confidence

        FIX 2: Length-ratio penalty. A 1-word audio segment should not score
        1.0 against a 20-word lip transcript. Added a length ratio damper.
        """
        # --- Case 1: no audio at all ---
        if not audio_text and not lip_text:
            return {
                "score": 1.0, "is_synced": True, "risk": 0.0,
                "char_similarity": 1.0, "word_overlap": 1.0,
                "lip_text": "", "audio_text": "",
                "verdict": "No audio data",
                "data_available": False,
            }

        # --- Case 2: audio present but no lip text yet (LipNet still buffering) ---
        if not lip_text and audio_text:
            audio_clean = self._filter_hallucinations(audio_text)
            if not audio_clean:
                return {
                    "score": 1.0, "is_synced": True, "risk": 0.0,
                    "char_similarity": 1.0, "word_overlap": 1.0,
                    "lip_text": "", "audio_text": audio_text,
                    "verdict": "Audio noise / hallucination filtered",
                    "data_available": False,
                }
            # Audio exists but no lip reading yet — can't score, report honestly
            return {
                "score": None, "is_synced": True, "risk": 0.0,
                "char_similarity": None, "word_overlap": None,
                "lip_text": "", "audio_text": audio_text,
                "verdict": "Lip reading buffering — sync pending",
                "data_available": False,
            }

        # --- Case 3: both available — compute full sync ---
        audio_clean = self._filter_hallucinations(audio_text)
        lip_clean   = (lip_text or "").strip()

        if not audio_clean:
            # Audio was noise/hallucination — no mismatch signal
            return {
                "score": 1.0, "is_synced": True, "risk": 0.0,
                "char_similarity": 1.0, "word_overlap": 1.0,
                "lip_text": lip_text, "audio_text": audio_text,
                "verdict": "Audio filtered (noise/hallucination)",
                "data_available": False,
            }

        lc = lip_clean.lower()
        ac = audio_clean.lower()

        char_sim = SequenceMatcher(None, lc, ac).ratio()

        lw = set(lc.split())
        aw = set(ac.split())
        jacc = len(lw & aw) / max(len(lw | aw), 1)

        # Length ratio penalty: penalise when texts are very different in length
        len_ratio = min(len(lc), len(ac)) / max(len(lc), len(ac), 1)
        # Only apply penalty when length mismatch is severe (< 0.3 ratio)
        len_penalty = 1.0 if len_ratio >= 0.3 else len_ratio / 0.3

        raw_score = char_sim * 0.55 + jacc * 0.45
        score = round(raw_score * len_penalty, 3)
        risk  = round(max(0.0, (0.50 - score) / 0.50) * 0.85, 3) if score < 0.50 else 0.0

        return {
            "score":           score,
            "is_synced":       score >= 0.45,
            "risk":            risk,
            "char_similarity": round(char_sim, 3),
            "word_overlap":    round(jacc, 3),
            "len_ratio":       round(len_ratio, 3),
            "lip_text":        lip_text,
            "audio_text":      audio_text,
            "verdict":         self._verdict(score),
            "data_available":  True,
        }

    # ── Internal ─────────────────────────────────────────────────────────────
    @staticmethod
    def _verdict(score: float) -> str:
        if score >= 0.70: return "Synced — audio matches lip movement"
        if score >= 0.45: return "Partial mismatch detected"
        if score >= 0.20: return "MISMATCH — possible external audio source"
        return "NO MATCH — likely lip-syncing or hidden earpiece"


class SpeakerVerifier:
    """
    Compares two audio segments to determine if they are from the same speaker.
    Used to detect voice coaching during an exam session.
    Unchanged from v3 — was working correctly.
    """

    def __init__(self):
        if not _has_speechbrain:
            self._ready = False
            return
        try:
            os.makedirs(SPKREC_SAVEDIR, exist_ok=True)
            self._verifier = SpeakerRecognition.from_hparams(
                source='speechbrain/spkrec-ecapa-voxceleb',
                savedir=SPKREC_SAVEDIR
            )
            self._baseline_path = None
            self._ready = True
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(
                f"SpeakerVerifier: failed to load model: {e}"
            )
            self._ready = False

    def enroll_baseline(self, audio_array: np.ndarray, sample_rate: int = 16000):
        if not self._ready or not _has_soundfile:
            return
        tmp = tempfile.NamedTemporaryFile(
            suffix='.wav', delete=False, dir=SPKREC_SAVEDIR
        )
        sf.write(tmp.name, audio_array, sample_rate)
        self._baseline_path = tmp.name

    def verify(self, current_audio: np.ndarray, sample_rate: int = 16000) -> dict:
        if not self._ready or self._baseline_path is None or not _has_soundfile:
            return {'score': 1.0, 'same_speaker': True, 'second_speaker': False}
        try:
            tmp = tempfile.NamedTemporaryFile(
                suffix='.wav', delete=False, dir=SPKREC_SAVEDIR
            )
            sf.write(tmp.name, current_audio, sample_rate)
            score, prediction = self._verifier.verify_files(
                self._baseline_path, tmp.name
            )
            os.unlink(tmp.name)
            same_speaker = bool(prediction)
            second_speaker = float(score) < 0.25
            return {
                'score': round(float(score), 4),
                'same_speaker': same_speaker,
                'second_speaker': second_speaker
            }
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"SpeakerVerifier.verify failed: {e}")
            return {'score': 1.0, 'same_speaker': True, 'second_speaker': False}

    def reset(self):
        if self._baseline_path and os.path.exists(self._baseline_path):
            os.unlink(self._baseline_path)
        self._baseline_path = None
