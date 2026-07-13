
from pydantic import BaseModel
from typing import Optional, Dict, Any

class LinkCheckRequest(BaseModel):
    url: str

class JobCreateRequest(BaseModel):
    source_url: Optional[str] = None
    source_type: str # 'link' or 'upload'
    title: str
    duration: float
    thumbnail: Optional[str] = None
    
    voice_gender: str
    voice_region: str
    voice_profile: Optional[str] = "auto"
    voice_emotion: Optional[str] = "neutral"
    keep_bg_music: bool
    bg_volume_db: Optional[int] = -18  # Volume of original audio: 0 (full) to -40 (nearly silent)
    generate_subtitles: bool
    burn_subtitles: Optional[bool] = False     # Opaque box blur old subs + burn-in new subs
    translation_mode: Optional[str] = "natural"
    video_context: Optional[str] = "neutral"  # neutral | fast | slow | teaching
    video_topic: Optional[str] = ""            # e.g. "Doraemon cartoon", "Harry Potter movie"
    whisper_model: Optional[str] = "base"      # base | small | medium
    asr_method: Optional[str] = "whisper"      # whisper | softsub | ocr
    clip_start: Optional[str] = None           # "HH:MM:SS" — start of clip (yt-dlp --download-sections)
    clip_end: Optional[str] = None             # "HH:MM:SS" — end of clip (yt-dlp --download-sections)
    exact_cut: Optional[bool] = True           # True = precise cut (force keyframes, slower CPU); False = fast cut (keyframe-aligned, near-zero CPU overhead)
    download_quality: Optional[str] = "720p"   # 1080p | 720p | 480p
    cookie_content: Optional[str] = None       # Content of cookies file (Netscape format)




class TimelineSegmentEdit(BaseModel):
    id: int
    start_time: float
    end_time: float
    text: str
    translation: str
    speaker: Optional[str] = "Speaker 1"
    emotional_tag: Optional[str] = "neutral"

class TimelineEditRequest(BaseModel):
    segments: list[TimelineSegmentEdit]

