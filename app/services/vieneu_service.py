import os
import logging
from pathlib import Path
from vieneu import Vieneu

logger = logging.getLogger(__name__)

class VieneuService:
    _instance = None
    
    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(VieneuService, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self.tts = None
        self._initialized = True

    def load_model(self):
        """Lazy load the Vieneu TTS model."""
        if self.tts is not None:
            return
        logger.info("Initializing Vieneu TTS engine...")
        # Vieneu automatically downloads and caches models on demand via huggingface_hub
        self.tts = Vieneu()
        logger.info("Vieneu TTS engine loaded successfully.")

    def generate_speech(self, text: str, voice_id: str, output_path: str) -> bool:
        """
        Synthesize speech to a file.
        
        Args:
            text: Text to synthesize.
            voice_id: The ID of the preset voice (e.g. 'Trúc Ly', 'Phạm Tuyên').
            output_path: Target path to save wave or mp3 file.
            
        Returns:
            True if success, False otherwise.
        """
        try:
            self.load_model()
            
            # Select preset voice
            voice_data = self.tts.get_preset_voice(voice_id)
            
            # Infer (generates numpy array of audio samples)
            audio = self.tts.infer(text=text, voice=voice_data)
            
            # Save audio file
            self.tts.save(audio, output_path)
            return True
        except Exception as e:
            logger.error(f"Vieneu synthesis failed: {e}", exc_info=True)
            return False
