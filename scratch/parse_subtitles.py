import json
import urllib.request

with open('d:/Voice_AI/scratch/subtitles_info.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

# Find 'en' automatic captions
en_captions = data.get('automatic_captions', {}).get('en', [])
print("Number of en formats:", len(en_captions))
if en_captions:
    # Try to find format with ext == 'json3'
    json3_formats = [f for f in en_captions if f.get('ext') == 'json3']
    if json3_formats:
        url = json3_formats[0]['url']
        print("Fetching JSON3 captions from URL...")
        response = urllib.request.urlopen(url)
        captions_data = json.loads(response.read().decode('utf-8'))
        
        # Print events
        events = captions_data.get('events', [])
        print(f"Total events: {len(events)}")
        for idx, event in enumerate(events[:20]):
            tStart = event.get('tStartMs', 0) / 1000.0
            dDuration = event.get('dDurationMs', 0) / 1000.0
            tEnd = tStart + dDuration
            segs = event.get('segs', [])
            text = "".join([s.get('utf8', '') for s in segs]).strip()
            if text:
                print(f"[{tStart:.2f} - {tEnd:.2f}] {text}")
    else:
        print("No json3 format found.")
else:
    print("No en captions found.")
