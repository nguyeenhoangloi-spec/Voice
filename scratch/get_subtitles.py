import yt_dlp
import json

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
    print("Subtitles keys:", info.get('subtitles', {}).keys())
    print("Automatic captions keys:", info.get('automatic_captions', {}).keys())
    
    # Save a small subset to inspect
    with open('scratch/subtitles_info.json', 'w', encoding='utf-8') as f:
        json.dump({
            'title': info.get('title'),
            'duration': info.get('duration'),
            'subtitles': {k: v[:2] for k, v in info.get('subtitles', {}).items()},
            'automatic_captions': {k: v[:2] for k, v in info.get('automatic_captions', {}).items() if k in ['en', 'vi']}
        }, f, indent=2, ensure_ascii=False)
