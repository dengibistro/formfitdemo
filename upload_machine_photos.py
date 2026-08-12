"""One-off script: uploads machine_photos/*.png to a public Supabase Storage
bucket ('machine-photos', already created) instead of committing them to the
public GitHub repo. Run once from your own shell (needs SUPABASE_URL/
SUPABASE_KEY exported, same as uvicorn):

    python3 upload_machine_photos.py

Safe to re-run — uses upsert, so it just overwrites if you swap a photo
later. Doesn't touch git or the running server; just populates Storage.
"""

import os
from pathlib import Path

from supabase import create_client

url = os.environ["SUPABASE_URL"]
key = os.environ["SUPABASE_KEY"]
client = create_client(url, key)

photos_dir = Path(__file__).parent / "machine_photos"
bucket = client.storage.from_("machine-photos")

for photo in sorted(photos_dir.glob("*.png")):
    data = photo.read_bytes()
    bucket.upload(photo.name, data, {"content-type": "image/png", "upsert": "true"})
    public_url = bucket.get_public_url(photo.name)
    print(f"{photo.name} -> {public_url}")

print("\nDone.")
