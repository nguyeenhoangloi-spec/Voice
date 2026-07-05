import asyncio
import edge_tts
import os

async def test_tts():
    text = 'Vinh quang của tôi, <break time="500ms"/> không xảy ra trước đám đông.'
    voice = 'vi-VN-HoaiMyNeural'
    output_path = 'd:/Voice_AI/scratch/test_break.mp3'
    
    # Let's test with native rate parameter
    communicate = edge_tts.Communicate(text, voice, rate="+10%")
    await communicate.save(output_path)
    print(f"File created: {output_path}, size={os.path.getsize(output_path)} bytes")

if __name__ == "__main__":
    asyncio.run(test_tts())
