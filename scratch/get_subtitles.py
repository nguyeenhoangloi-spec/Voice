import yt_dlp
import json
import sys

sys.stdout.reconfigure(encoding='utf-8')

url = "https://youtu.be/2UkYJTfaT8E"
ydl_opts = {
    'skip_download': True,
    'writeinfojson': True,
    'outtmpl': 'scratch/video_info',
}

with yt_dlp.YoutubeDL(ydl_opts) as ydl:
    info = ydl.extract_info(url, download=False)
    print("Title:", info.get('title'))
    print("Duration:", info.get('duration'))
    
    # Save a small subset to inspect
    with open('scratch/subtitles_info.json', 'w', encoding='utf-8') as f:
        json.dump({
            'title': info.get('title'),
            'duration': info.get('duration'),
            'subtitles': info.get('subtitles', {}),
            'automatic_captions': info.get('automatic_captions', {})
        }, f, indent=2, ensure_ascii=False)
