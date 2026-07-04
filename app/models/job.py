from datetime import datetime
from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, JSON
from sqlalchemy.orm import relationship
from app.database import Base

class DubbingJob(Base):
    __tablename__ = "dubbing_jobs"

    id = Column(String, primary_key=True, index=True) # UUID string or similar unique ID
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    
    source_url = Column(String, nullable=True) # URL of YouTube or media file
    source_type = Column(String, nullable=False) # 'link' or 'upload'
    
    # Trạng thái: pending | processing | completed | failed | cancelled
    status = Column(String, default="pending", nullable=False)
    progress_percent = Column(Integer, default=0, nullable=False)
    current_step = Column(Integer, default=1, nullable=False) # 1 to 20
    current_step_name = Column(String, nullable=True)
    
    source_language = Column(String, nullable=True)
    target_language = Column(String, default="vi", nullable=False)
    duration = Column(Float, nullable=True) # in seconds
    
    voice_config = Column(JSON, nullable=True) # JSON config containing speed, pitch, emotion, voice profile
    error_message = Column(String, nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)

    # Relationships
    user = relationship("User", back_populates="jobs")
    project = relationship("Project", back_populates="jobs")
    steps = relationship("JobStep", back_populates="job", cascade="all, delete-orphan")
    segments = relationship("TranscriptSegment", back_populates="job", cascade="all, delete-orphan")
    exports = relationship("Export", back_populates="job", cascade="all, delete-orphan")

class JobStep(Base):
    __tablename__ = "job_steps"

    id = Column(Integer, primary_key=True, index=True)
    job_id = Column(String, ForeignKey("dubbing_jobs.id", ondelete="CASCADE"), nullable=False)
    step_number = Column(Integer, nullable=False) # 1 to 20
    name = Column(String, nullable=False)
    
    # Trạng thái: pending | waiting | processing | completed | warning | failed | skipped | cancelled
    status = Column(String, default="pending", nullable=False)
    
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    log_message = Column(String, nullable=True)

    job = relationship("DubbingJob", back_populates="steps")

class TranscriptSegment(Base):
    __tablename__ = "transcript_segments"

    id = Column(Integer, primary_key=True, index=True)
    job_id = Column(String, ForeignKey("dubbing_jobs.id", ondelete="CASCADE"), nullable=False)
    segment_index = Column(Integer, nullable=False)
    
    start_time = Column(Float, nullable=False) # in seconds
    end_time = Column(Float, nullable=False) # in seconds
    speaker = Column(String, default="Speaker 1")
    
    text = Column(String, nullable=False) # original text
    translation = Column(String, nullable=True) # Vietnamese translation
    emotional_tag = Column(String, default="Neutral") # Neutral, Happy, Angry, Whisper, etc.
    voice_profile_id = Column(String, nullable=True) # Selected voice (nam, nữ, miền Bắc/Trung/Nam)
    
    # Trạng thái: pending | recognized | translated | tts_generated | completed
    status = Column(String, default="pending", nullable=False)
    audio_path = Column(String, nullable=True) # local path to individual translated audio file
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    job = relationship("DubbingJob", back_populates="segments")

class Export(Base):
    __tablename__ = "exports"

    id = Column(Integer, primary_key=True, index=True)
    job_id = Column(String, ForeignKey("dubbing_jobs.id", ondelete="CASCADE"), nullable=False)
    file_type = Column(String, nullable=False) # video | audio_mp3 | audio_wav | subtitle_srt | subtitle_vtt
    file_path = Column(String, nullable=False)
    file_size = Column(Integer, nullable=True) # in bytes
    created_at = Column(DateTime, default=datetime.utcnow)

    job = relationship("DubbingJob", back_populates="exports")
