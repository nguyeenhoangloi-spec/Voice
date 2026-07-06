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
    voice_emotion: str
    keep_bg_music: bool
    bg_volume_db: Optional[int] = -18  # Volume of original audio: 0 (full) to -40 (nearly silent)
    generate_subtitles: bool
    translation_mode: Optional[str] = "vietnamese"
    video_context: Optional[str] = "neutral"  # neutral | fast | slow | teaching
    whisper_model: Optional[str] = "base"      # base | small | medium


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

