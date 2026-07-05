import sys
sys.stdout.reconfigure(encoding='utf-8')
import os
sys.path.insert(0, 'd:/Voice_AI')
from app.services.dubbing_engine import generate_ssml_for_segment

# Test segment data  
test_segs = [
    {'start': 0.0, 'end': 5.0, 'translation': 'Vinh quang cua toi khong xay ra truoc dam dong.'},
    {'start': 5.0, 'end': 11.0, 'translation': 'No khong xay ra o san van dong hay tren san khau. Khong co huy chuong nao duoc trao.'},
    {'start': 21.0, 'end': 29.0, 'translation': 'Voi tat ca moi thu, toi phai tro thanh nguoi tot nhat co the, tot hon toi cua ngay hom qua, tot hon nhung gi moi nguoi nghi toi co the tro thanh, va tot hon nhung gi toi tu nghi minh co the dat duoc.'},
]

print("=== SSML Timing-Aware Test ===\n")
for s in test_segs:
    duration = s['end'] - s['start']
    words = s['translation'].split()
    ssml = generate_ssml_for_segment(s, voice='vi-VN-HoaiMyNeural', video_context='neutral')
    max_words = int(duration * 3.2)
    status = "OK" if len(words) <= max_words else f"COMPRESSED ({len(words)} -> {max_words})"
    print(f"[{s['start']:.1f}s - {s['end']:.1f}s] dur={duration}s | words={len(words)} | max={max_words} | {status}")
    print(f"  SSML preview: {ssml[:150]}...")
    print()
