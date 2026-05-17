"""
build.py — Reads your Google Drive portfolio folder and generates data.json
for the website.

Google Drive folder structure expected:
  📁 VdV-Portfolio/
    📁 Zugspitze/
        info.json          ← place metadata + story text
        photo1.jpg
        photo2.jpg
        ...
    📁 Schwerin/
        info.json
        photo1.jpg
        ...

info.json format (create one per place folder):
{
  "name": "Zugspitze",
  "region": "Bavaria · 2,962m",
  "tagline": "Germany's highest peak",
  "subtitle": "& the edge of light",
  "coords": "47°25'16\"N  10°59'07\"E",
  "storyTitle": "As one world sets, the other arises.",
  "story": [
    "First paragraph of your story here.",
    "Second paragraph here."
  ],
  "camera": "Fujifilm X · Classic Chrome",
  "season": "Winter 2026",
  "theme": "Landscape",
  "instagramUrl": "https://www.instagram.com/p/YOURPOSTID/",
  "order": 1
}
"""

import os
import json
import sys
from datetime import datetime
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
import io
import base64

# ── Config ──────────────────────────────────────────────────────────────────
PORTFOLIO_FOLDER_NAME = "VdV-Portfolio"   # Name of your top-level Drive folder
OUTPUT_FILE = "data.json"
IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp'}
MAX_PHOTOS_PER_PLACE = 9
# ────────────────────────────────────────────────────────────────────────────

def get_drive_service():
    """Authenticate using service account credentials from environment."""
    creds_json = os.environ.get('GOOGLE_SERVICE_ACCOUNT_JSON')
    if not creds_json:
        print("ERROR: GOOGLE_SERVICE_ACCOUNT_JSON environment variable not set.")
        sys.exit(1)

    creds_data = json.loads(creds_json)
    creds = service_account.Credentials.from_service_account_info(
        creds_data,
        scopes=['https://www.googleapis.com/auth/drive.readonly']
    )
    return build('drive', 'v3', credentials=creds)

def find_folder(service, name, parent_id=None):
    """Find a folder by name, optionally within a parent."""
    query = f"name='{name}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
    if parent_id:
        query += f" and '{parent_id}' in parents"
    results = service.files().list(q=query, fields="files(id, name)").execute()
    files = results.get('files', [])
    return files[0] if files else None

def list_folder_contents(service, folder_id):
    """List all files and subfolders in a folder."""
    results = service.files().list(
        q=f"'{folder_id}' in parents and trashed=false",
        fields="files(id, name, mimeType, modifiedTime)",
        orderBy="name"
    ).execute()
    return results.get('files', [])

def download_file_as_base64_url(service, file_id, mime_type):
    """Download a file and return as a base64 data URL."""
    request = service.files().get_media(fileId=file_id)
    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    fh.seek(0)
    b64 = base64.b64encode(fh.read()).decode('utf-8')
    return f"data:{mime_type};base64,{b64}"

def get_public_url(file_id):
    """Return a direct public URL for a Drive file (must be shared publicly)."""
    return f"https://drive.google.com/thumbnail?id={file_id}&sz=w1200"

def read_json_file(service, file_id):
    """Download and parse a JSON file from Drive."""
    request = service.files().get_media(fileId=file_id)
    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    fh.seek(0)
    return json.loads(fh.read().decode('utf-8'))

def process_place_folder(service, folder_id, folder_name):
    """Process a single place folder and return place data dict."""
    print(f"  Processing: {folder_name}")
    contents = list_folder_contents(service, folder_id)

    info = {}
    photos = []
    hero_photo = None

    for item in contents:
        name = item['name']
        ext = os.path.splitext(name)[1].lower()

        if name == 'info.json':
            try:
                info = read_json_file(service, item['id'])
                print(f"    ✓ Loaded info.json")
            except Exception as e:
                print(f"    ✗ Could not read info.json: {e}")

        elif ext in IMAGE_EXTENSIONS:
            url = get_public_url(item['id'])
            # Use filename (without ext) as caption hint
            caption = os.path.splitext(name)[0].replace('-', ' ').replace('_', ' ')
            photo_entry = {
                "url": url,
                "caption": caption,
                "fileId": item['id'],
                "name": name
            }
            # First image or one named 'hero' becomes the hero
            if name.lower().startswith('hero') or not hero_photo:
                hero_photo = url
            photos.append(photo_entry)

    # Limit photos
    photos = photos[:MAX_PHOTOS_PER_PLACE]

    return {
        "name": info.get("name", folder_name),
        "region": info.get("region", ""),
        "tagline": info.get("tagline", ""),
        "subtitle": info.get("subtitle", ""),
        "coords": info.get("coords", ""),
        "storyTitle": info.get("storyTitle", folder_name),
        "story": info.get("story", []),
        "camera": info.get("camera", ""),
        "season": info.get("season", ""),
        "theme": info.get("theme", ""),
        "instagramUrl": info.get("instagramUrl", ""),
        "order": info.get("order", 99),
        "heroPhoto": info.get("heroPhoto", hero_photo),
        "photos": photos,
        "_photoCount": len(photos)
    }

def main():
    print("🔍 Connecting to Google Drive...")
    service = get_drive_service()

    print(f"🔍 Looking for folder: {PORTFOLIO_FOLDER_NAME}")
    root_folder = find_folder(service, PORTFOLIO_FOLDER_NAME)
    if not root_folder:
        print(f"ERROR: Could not find folder '{PORTFOLIO_FOLDER_NAME}' in Google Drive.")
        print("Make sure it's shared with your service account email.")
        sys.exit(1)

    print(f"✓ Found portfolio folder (ID: {root_folder['id']})")

    # List all subfolders (each = one place)
    contents = list_folder_contents(service, root_folder['id'])
    place_folders = [
        f for f in contents
        if f['mimeType'] == 'application/vnd.google-apps.folder'
    ]

    print(f"📁 Found {len(place_folders)} place folders")

    places = []
    for folder in place_folders:
        place = process_place_folder(service, folder['id'], folder['name'])
        places.append(place)

    # Sort by order field
    places.sort(key=lambda p: p.get('order', 99))

    data = {
        "lastUpdated": datetime.utcnow().strftime("%B %d, %Y"),
        "totalPlaces": len(places),
        "totalPhotos": sum(p['_photoCount'] for p in places),
        "places": places
    }

    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"\n✅ Generated {OUTPUT_FILE}")
    print(f"   {len(places)} places · {data['totalPhotos']} photos total")

if __name__ == '__main__':
    main()
