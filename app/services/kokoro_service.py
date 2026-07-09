import os
import urllib.request
import logging
from pathlib import Path
import soundfile as sf
from kokoro_onnx import Kokoro

logger = logging.getLogger(__name__)

# Official download links for model v1.0
MODEL_URL = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx"
VOICES_URL = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin"

# Mapping lang codes to kokoro-onnx format
# kokoro-onnx supports: en-us, en-gb, es, fr-fr, hi, it, pt-br, ja, zh
LANG_MAP = {
    "en": "en-us",
    "en-us": "en-us",
    "en-gb": "en-gb",
    "es": "es",
    "fr": "fr-fr",
    "fr-fr": "fr-fr",
    "hi": "hi",
    "it": "it",
    "pt": "pt-br",
    "pt-br": "pt-br",
    "ja": "ja",
    "zh": "zh"
}

# Supported voices (50 preset voices)
KOKORO_VOICES = {
    "en": [
        # American Female
        {"id": "af_heart", "name": "Heart (US Female)", "gender": "female"},
        {"id": "af_bella", "name": "Bella (US Female)", "gender": "female"},
        {"id": "af_sarah", "name": "Sarah (US Female)", "gender": "female"},
        {"id": "af_alloy", "name": "Alloy (US Female)", "gender": "female"},
        {"id": "af_aoede", "name": "Aoede (US Female)", "gender": "female"},
        {"id": "af_jessica", "name": "Jessica (US Female)", "gender": "female"},
        {"id": "af_kore", "name": "Kore (US Female)", "gender": "female"},
        {"id": "af_nicole", "name": "Nicole (US Female)", "gender": "female"},
        {"id": "af_nova", "name": "Nova (US Female)", "gender": "female"},
        {"id": "af_river", "name": "River (US Female)", "gender": "female"},
        {"id": "af_sky", "name": "Sky (US Female)", "gender": "female"},
        # American Male
        {"id": "am_adam", "name": "Adam (US Male)", "gender": "male"},
        {"id": "am_echo", "name": "Echo (US Male)", "gender": "male"},
        {"id": "am_eric", "name": "Eric (US Male)", "gender": "male"},
        {"id": "am_fenrir", "name": "Fenrir (US Male)", "gender": "male"},
        {"id": "am_liam", "name": "Liam (US Male)", "gender": "male"},
        {"id": "am_michael", "name": "Michael (US Male)", "gender": "male"},
        {"id": "am_onyx", "name": "Onyx (US Male)", "gender": "male"},
        {"id": "am_puck", "name": "Puck (US Male)", "gender": "male"},
        {"id": "am_santa", "name": "Santa (US Male)", "gender": "male"},
        # British Female
        {"id": "bf_alice", "name": "Alice (UK Female)", "gender": "female"},
        {"id": "bf_emma", "name": "Emma (UK Female)", "gender": "female"},
        {"id": "bf_isabella", "name": "Isabella (UK Female)", "gender": "female"},
        {"id": "bf_lily", "name": "Lily (UK Female)", "gender": "female"},
        # British Male
        {"id": "bm_daniel", "name": "Daniel (UK Male)", "gender": "male"},
        {"id": "bm_fable", "name": "Fable (UK Male)", "gender": "male"},
        {"id": "bm_george", "name": "George (UK Male)", "gender": "male"},
        {"id": "bm_lewis", "name": "Lewis (UK Male)", "gender": "male"}
    ],
    "es": [
        {"id": "ef_dora", "name": "Dora (ES Female)", "gender": "female"},
        {"id": "em_alex", "name": "Alex (ES Male)", "gender": "male"},
        {"id": "em_santa", "name": "Santa (ES Male)", "gender": "male"}
    ],
    "fr": [
        {"id": "ff_siwis", "name": "Siwis (FR Female)", "gender": "female"}
    ],
    "hi": [
        {"id": "hf_alpha", "name": "Alpha (HI Female)", "gender": "female"},
        {"id": "hf_beta", "name": "Beta (HI Female)", "gender": "female"},
        {"id": "hm_omega", "name": "Omega (HI Male)", "gender": "male"},
        {"id": "hm_psi", "name": "Psi (HI Male)", "gender": "male"}
    ],
    "it": [
        {"id": "if_sara", "name": "Sara (IT Female)", "gender": "female"},
        {"id": "im_nicola", "name": "Nicola (IT Male)", "gender": "male"}
    ],
    "pt": [
        {"id": "pf_dora", "name": "Dora (PT Female)", "gender": "female"},
        {"id": "pm_alex", "name": "Alex (PT Male)", "gender": "male"},
        {"id": "pm_santa", "name": "Santa (PT Male)", "gender": "male"}
    ],
    "ja": [
        {"id": "jf_alpha", "name": "Alpha (JA Female)", "gender": "female"},
        {"id": "jf_gongitsune", "name": "Gongitsune (JA Female)", "gender": "female"},
        {"id": "jf_nezumi", "name": "Nezumi (JA Female)", "gender": "female"},
        {"id": "jf_tebukuro", "name": "Tebukuro (JA Female)", "gender": "female"},
        {"id": "jm_kumo", "name": "Kumo (JA Male)", "gender": "male"}
    ],
    "zh": [
        {"id": "zf_xiaobei", "name": "Xiaobei (ZH Female)", "gender": "female"},
        {"id": "zf_xiaoni", "name": "Xiaoni (ZH Female)", "gender": "female"},
        {"id": "zf_xiaoxiao", "name": "Xiaoxiao (ZH Female)", "gender": "female"},
        {"id": "zf_xiaoyi", "name": "Xiaoyi (ZH Female)", "gender": "female"}
    ]
}


class KokoroService:
    _instance = None
    
    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(KokoroService, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, models_dir: str = "storage/models"):
        if self._initialized:
            return
            
        self.models_dir = Path(models_dir)
        self.model_path = self.models_dir / "kokoro-v1.0.onnx"
        self.voices_path = self.models_dir / "voices-v1.0.bin"
        self.kokoro = None
        self._initialized = True

    def _download_file(self, url: str, dest_path: Path):
        """Helper to download a file with logger progress."""
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        logger.info(f"Downloading {url} to {dest_path}...")
        
        # Download blockwise
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req) as response, open(dest_path, 'wb') as out_file:
                block_size = 1024 * 1024  # 1MB
                while True:
                    buffer = response.read(block_size)
                    if not buffer:
                        break
                    out_file.write(buffer)
            logger.info(f"Download complete: {dest_path}")
        except Exception as e:
            logger.error(f"Failed to download {url}: {e}")
            if dest_path.exists():
                dest_path.unlink()
            raise e

    def ensure_models_downloaded(self):
        """Ensure the ONNX model and voices file are downloaded."""
        if not self.model_path.exists():
            self._download_file(MODEL_URL, self.model_path)
            
        if not self.voices_path.exists():
            self._download_file(VOICES_URL, self.voices_path)

    def load_model(self):
        """Lazy load the ONNX model."""
        if self.kokoro is not None:
            return
            
        self.ensure_models_downloaded()
        
        logger.info("Initializing Kokoro ONNX engine...")
        self.kokoro = Kokoro(str(self.model_path), str(self.voices_path))
        logger.info("Kokoro ONNX engine loaded successfully.")

    def generate_speech(self, text: str, voice_id: str, lang: str, output_path: str, speed: float = 1.0) -> bool:
        """
        Synthesize speech to a file.
        
        Args:
            text: Text to synthesize.
            voice_id: The id of the preset voice (e.g. af_bella).
            lang: Language code (e.g. en, es, ja, zh).
            output_path: Target path to save wave file.
            speed: Speech rate multiplier.
            
        Returns:
            True if success, False otherwise.
        """
        try:
            self.load_model()
            
            # Map lang code
            kokoro_lang = LANG_MAP.get(lang.lower(), "en-us")
            
            # Generate audio samples
            samples, sample_rate = self.kokoro.create(
                text=text,
                voice=voice_id,
                speed=speed,
                lang=kokoro_lang
            )
            
            # Save audio
            sf.write(output_path, samples, sample_rate)
            return True
        except Exception as e:
            logger.error(f"Kokoro synthesis failed: {e}", exc_info=True)
            return False

    @classmethod
    def get_voices_for_lang(cls, lang: str) -> list:
        """Return preset voices list for a given language code."""
        # Clean lang code (e.g., 'en-US' -> 'en')
        clean_lang = lang.split('-')[0].lower()
        return KOKORO_VOICES.get(clean_lang, KOKORO_VOICES.get("en", []))
