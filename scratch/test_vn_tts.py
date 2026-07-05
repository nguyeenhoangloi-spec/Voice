import asyncio
import sys
sys.path.insert(0, 'd:/Voice_AI')
from app.services.dubbing_engine import generate_tts_audio

async def run_test():
    text = 'Xin chào, <break time="300ms"/> đây là một thử nghiệm ngắt nghỉ tự nhiên.'
    out_path = "d:/Voice_AI/scratch/test_vietnamese_tts.mp3"
    print("Generating TTS...")
    generate_tts_audio(text, out_path, rate="+10%")
    print(f"Success! Output file is at {out_path}")

if __name__ == "__main__":
    asyncio.run(run_test())
