import sys
import os
import uuid
import json
from datetime import datetime

# Add root folder to PYTHONPATH
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import SessionLocal
from app.models.user import User
from app.models.job import DubbingJob, JobStep, TranscriptSegment, Export
from app.workers.dubbing_tasks import run_dubbing_pipeline, PIPELINE_STEPS

def main():
    db = SessionLocal()
    try:
        # 1. Find or create test user
        user = db.query(User).filter(User.email == "test_dubbing@example.com").first()
        if not user:
            user = User(
                email="test_dubbing@example.com",
                hashed_password="fake_hash_password",
                full_name="Test Dubbing",
                role="user",
                is_active=True
            )
            db.add(user)
            db.commit()
            db.refresh(user)
            print(f"Created new test user with ID: {user.id}")
        else:
            print(f"Using existing test user with ID: {user.id}")

        # 2. Create DubbingJob for test video
        job_id = str(uuid.uuid4())
        
        # Specific voice chosen: vi-VN-NamMinhNeural (Male, South)
        voice_config = {
            "voice_gender": "male",
            "voice_region": "south",
            "voice_profile": "vi-VN-NamMinhNeural",  # SPECIFIC VOICE (not 'auto')
            "voice_emotion": "neutral",
            "keep_bg_music": True,
            "bg_volume_db": -18,
            "generate_subtitles": True,
            "burn_subtitles": False,
            "translation_mode": "llm",
            "video_context": "neutral",
            "video_topic": "Test Dubbing Single Voice",
            "whisper_model": "tiny",
            "asr_method": "whisper"
        }

        job = DubbingJob(
            id=job_id,
            user_id=user.id,
            source_url="https://youtu.be/2UkYJTfaT8E?si=LtOCaovrTQbaWWi1",
            source_type="link",
            status="pending",
            progress_percent=0,
            current_step=1,
            current_step_name=PIPELINE_STEPS[0],
            duration=0.0,
            voice_config=voice_config
        )
        db.add(job)

        # Create JobStep
        for idx, name in enumerate(PIPELINE_STEPS):
            step = JobStep(
                job_id=job_id,
                step_number=idx + 1,
                name=name,
                status="pending" if idx > 0 else "processing",
                started_at=datetime.utcnow() if idx == 0 else None
            )
            db.add(step)

        db.commit()
        print(f"Created DubbingJob in DB. Job ID: {job_id}")

        # 3. Trigger run_dubbing_pipeline
        print("\n=== STARTING LIVE DUBBING PIPELINE ===")
        run_dubbing_pipeline(job_id)
        print("=== PIPELINE FINISHED ===\n")

        # 4. Check results in DB
        db.refresh(job)
        print(f"Final Job Status: {job.status}")
        if job.error_message:
            print(f"Error message: {job.error_message}")

        # Check assigned voices for each Segment
        segments = db.query(TranscriptSegment).filter(TranscriptSegment.job_id == job_id).all()
        print(f"\nNumber of generated segments: {len(segments)}")
        
        for s in segments:
            # We print speaker and translation
            # Encode print output to ascii or ignore characters that fail
            print(f"  Seg {s.segment_index} ({s.start_time:.1f}s - {s.end_time:.1f}s): "
                  f"Speaker={s.speaker} | Text={s.text[:30]}... | Translation={s.translation[:30]}... | Audio={s.audio_path}")
            
        # Check exports
        exports = db.query(Export).filter(Export.job_id == job_id).all()
        print(f"\nExported Files:")
        for exp in exports:
            print(f"  - [{exp.file_type}]: {exp.file_path} ({exp.file_size // 1024} KB)")

    except Exception as e:
        print(f"Error during live test: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    main()
