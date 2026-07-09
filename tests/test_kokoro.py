import os
import sys
from pathlib import Path

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent))

from app.services.kokoro_service import KokoroService

def test_kokoro_synthesis():
    print("Initializing KokoroService...")
    service = KokoroService(models_dir="storage/models")
    
    # Ensure temporary output directory exists
    os.makedirs("storage/temp", exist_ok=True)
    output_path = "storage/temp/test_kokoro_output.wav"
    
    # Clean previous test output
    if os.path.exists(output_path):
        os.remove(output_path)
        
    print("Generating speech (this may take a few seconds if downloading model files)...")
    success = service.generate_speech(
        text="Hello, this is a test of the Kokoro ONNX model running completely offline.",
        voice_id="af_bella",
        lang="en",
        output_path=output_path
    )
    
    assert success, "Speech generation failed!"
    assert os.path.exists(output_path), "Output file was not created!"
    assert os.path.getsize(output_path) > 0, "Output file is empty!"
    
    print(f"Test passed! Output saved successfully to: {output_path} ({os.path.getsize(output_path)} bytes)")

if __name__ == "__main__":
    test_kokoro_synthesis()
