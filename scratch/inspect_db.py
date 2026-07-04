import sqlite3
import json
import sys

# Configure stdout to use utf-8
sys.stdout.reconfigure(encoding='utf-8')

conn = sqlite3.connect("d:/Voice_AI/storage/database.db")
cursor = conn.cursor()

# Get all jobs
cursor.execute("SELECT id, source_type, source_url, status, current_step, current_step_name, error_message, voice_config FROM dubbing_jobs")
jobs = cursor.fetchall()
print("=== DUBBING JOBS ===")
for job in jobs:
    print(f"ID: {job[0]}")
    print(f"  Source Type: {job[1]}")
    print(f"  Source URL: {job[2]}")
    print(f"  Status: {job[3]}")
    print(f"  Current Step: {job[4]} ({job[5]})")
    print(f"  Error: {job[6]}")
    print(f"  Voice Config: {job[7]}")
    
    # Get segments
    cursor.execute("SELECT segment_index, start_time, end_time, text, translation, audio_path FROM transcript_segments WHERE job_id = ?", (job[0],))
    segs = cursor.fetchall()
    print(f"  Segments Count: {len(segs)}")
    for s in segs[:10]:
        print(f"    Seg {s[0]} [{s[1]}-{s[2]}]: Text: '{s[3]}' | Translation: '{s[4]}' | Audio: '{s[5]}'")
    if len(segs) > 10:
        print("    ...")

conn.close()
