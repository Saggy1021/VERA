"""
VERA — VAD Processor (Silero-VAD, MIT)
Voice Activity Detector to gate Whisper transcription.
Only calls Whisper if speech is actually present, preventing
hallucinations on silence/background noise and reducing CPU ~60%.
"""
import torch
import numpy as np
import logging

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16000
SPEECH_THRESHOLD = 0.5    # Silero confidence above this = speech present


class VADProcessor:
    """
    Voice Activity Detector using Silero-VAD (MIT).
    Use this to gate Whisper: only call Whisper if is_speech() returns True.
    Prevents Whisper hallucinations on silence/background noise.
    Model is ~2MB. Fully offline after first load.
    """

    def __init__(self):
        try:
            self._model, self._utils = torch.hub.load(
                repo_or_dir='snakers4/silero-vad',
                model='silero_vad',
                force_reload=False,
                onnx=False
            )
            (self.get_speech_timestamps,
             self.save_audio,
             self.read_audio,
             self.VADIterator,
             self.collect_chunks) = self._utils
            self._ready = True
            logger.info("VADProcessor: Silero-VAD loaded.")
        except Exception as e:
            logger.error(f"VADProcessor: Failed to load Silero-VAD: {e}")
            self._ready = False

    def is_speech(self, audio_chunk: np.ndarray) -> bool:
        """
        Returns True if the audio chunk contains speech.
        audio_chunk: 1D numpy array of float32 PCM at 16kHz.
        """
        if not self._ready:
            return True   # Fail open — don't block audio pipeline

        tensor = torch.from_numpy(audio_chunk).float()
        with torch.no_grad():
            confidence = self._model(tensor, SAMPLE_RATE).item()
        return confidence >= SPEECH_THRESHOLD

    def get_speech_segments(self, audio: np.ndarray) -> list:
        """
        Returns list of speech timestamps in a longer audio clip.
        Useful for clipping only the speech parts for transcription.
        """
        if not self._ready:
            return []
        tensor = torch.from_numpy(audio).float()
        return self.get_speech_timestamps(
            tensor, self._model,
            sampling_rate=SAMPLE_RATE,
            threshold=SPEECH_THRESHOLD
        )
