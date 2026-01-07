from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import JSONResponse
import uvicorn
import os
import glob
import json
import psutil
from datetime import datetime
import settings_manager
import monitor_service
import uploader_service
import subprocess
import sys

app = FastAPI()

# Mount Static Files (App Assets: CSS, JS)
if not os.path.exists("static"):
    os.makedirs("static")
app.mount("/static", StaticFiles(directory="static"), name="static")

# Mount Data Files (Recordings, Thumbnails)
if not os.path.exists("data"):
    os.makedirs("data")
app.mount("/files", StaticFiles(directory="data"), name="files")

# Templates
if not os.path.exists("templates"):
    os.makedirs("templates")
templates = Jinja2Templates(directory="templates")

# Paths
DATA_DIR = "data"
CHANNELS_FILE = os.path.join(DATA_DIR, "watchlist.json")
RECORDINGS_FILE = os.path.join(DATA_DIR, "active_recordings.json")
SERVICE_STATE_FILE = os.path.join(DATA_DIR, "service_state.json")

# --- Helpers ---
def load_json(filepath, default):
    if os.path.exists(filepath):
        with open(filepath, "r") as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return default
    return default

def save_json(filepath, data):
    with open(filepath, "w") as f:
        json.dump(data, f)

def has_ffmpeg():
    from shutil import which
    return which("ffmpeg") is not None

def generate_thumbnail(video_path):
    if not has_ffmpeg():
        return None
        
    filename = os.path.basename(video_path)
    thumb_name = f"{filename}.jpg"
    thumb_dir = os.path.join(DATA_DIR, "thumbnails")
    thumb_path = os.path.join(thumb_dir, thumb_name)
    
    if not os.path.exists(thumb_dir):
        os.makedirs(thumb_dir)
        
    if os.path.exists(thumb_path):
        return f"/files/thumbnails/{thumb_name}"
        
    # Generate
    try:
        subprocess.run([
            "ffmpeg", "-y", 
            "-i", video_path, 
            "-ss", "00:00:10", # 10s mark
            "-vframes", "1",
            "-vf", "scale=480:-1", # Resize width 480px, keep aspect
            "-q:v", "2",
            thumb_path
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
        
        if os.path.exists(thumb_path):
            return f"/files/thumbnails/{thumb_name}"
    except Exception as e:
        print(f"Error generating thumbnail for {filename}: {e}")
        
    return None

def get_recordings():
    # 1. Scan for Folders
    all_items = os.listdir(DATA_DIR)
    folders = [d for d in all_items if d.startswith("rec_") and os.path.isdir(os.path.join(DATA_DIR, d))]
    
    # 2. Scan for Legacy Files
    legacy_files = glob.glob(os.path.join(DATA_DIR, "rec_*.*"))
    legacy_files = [f for f in legacy_files if os.path.isfile(f) and f.lower().endswith(('.mp4', '.ts', '.mkv'))]
    
    result = []
    active_recs = load_json(RECORDINGS_FILE, {})
    
    # Process Folders
    for folder in folders:
        folder_path = os.path.join(DATA_DIR, folder)
        meta_path = os.path.join(folder_path, "meta.json")
        
        # Load Metadata
        meta = load_json(meta_path, {})
        
        # Find Video File
        video_file = None
        video_path = None
        
        # Check standard names or scan
        possible_video = [f for f in os.listdir(folder_path) if f.lower().endswith(('.mp4', '.ts', '.mkv'))]
        if possible_video:
            video_file = possible_video[0] # Take first valid video
            video_path = os.path.join(folder_path, video_file)
        
        if not video_path:
            continue # Skip empty folders
            
        # Stats
        try:
            size_mb = os.path.getsize(video_path) / (1024 * 1024)
            timestamp = os.path.getmtime(video_path)
            date_str = datetime.fromtimestamp(timestamp).strftime('%d/%m/%Y %H:%M')
        except OSError:
            size_mb = 0
            date_str = "Unknown"

        # Check Active
        is_active = False
        for info in active_recs.values():
            # Check by folder name match logic or pid logic
            if info.get('folder_name') == folder:
                is_active = True
                break
        
        # Thumbs
        thumb_url = None
        if not is_active:
            thumb_url = generate_thumbnail(video_path)

        result.append({
            "type": "folder",
            "id": folder, # Unique ID is folder name
            "filename": folder, # Display name fallback
            "title": meta.get("title", folder),
            "game": meta.get("game", ""),
            "author": meta.get("author", ""),
            "upload_links": meta.get("upload_links", {}),
            "path": video_path,
            "url": f"/files/{folder}/{video_file}",
            "thumbnail": thumb_url,
            "size_mb": round(size_mb, 1),
            "date": date_str,
            "is_active": is_active
        })

    # Process Legacy Files
    for f in legacy_files:
        filename_only = os.path.basename(f)
        try:
            size_mb = os.path.getsize(f) / (1024 * 1024)
            timestamp = os.path.getmtime(f)
            date_str = datetime.fromtimestamp(timestamp).strftime('%d/%m/%Y %H:%M')
        except OSError:
            size_mb = 0
            date_str = ""
            
        is_active = False
        for info in active_recs.values():
             if info.get('filename') and os.path.basename(info['filename']) == filename_only:
                is_active = True
                break
        
        thumb_url = generate_thumbnail(f) if not is_active else None
        
        result.append({
            "type": "legacy",
            "id": filename_only,
            "filename": filename_only,
            "title": filename_only,
            "game": "Legacy",
            "upload_links": {},
            "path": f,
            "url": f"/files/{filename_only}",
            "thumbnail": thumb_url,
            "size_mb": round(size_mb, 1),
            "date": date_str,
            "is_active": is_active
        })
        
    # Sort by date
    result.sort(key=lambda x: x['date'], reverse=True)
    return result

# --- Globals for Concurrency ---
# Key: filename, Value: {"target": "youtube"|"archive", "progress": 0.0, "status": "uploading"}
ACTIVE_UPLOADS = {}

# --- Routes ---

@app.get("/")
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

# API: Status & Uploads
# API: Status & Uploads
@app.get("/api/status")
async def get_status():
    try:
        service_state = load_json(SERVICE_STATE_FILE, {"enabled": False})
        active_recs = load_json(RECORDINGS_FILE, {})
        
        # Clean up zombie records visually
        clean_recs = []
        for ch, info in active_recs.items():
            clean_recs.append({
                "channel": ch,
                "pid": info.get('pid'),
                "filename": os.path.basename(info.get('filename', ''))
            })
            
        return {
            "service_enabled": service_state.get("enabled", False),
            "active_recordings": clean_recs,
            "active_uploads": ACTIVE_UPLOADS
        }
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.post("/api/service/toggle")
async def toggle_service():
    state = load_json(SERVICE_STATE_FILE, {"enabled": False})
    state["enabled"] = not state["enabled"]
    save_json(SERVICE_STATE_FILE, state)
    return state

@app.post("/api/recording/stop/{channel}")
async def stop_recording(channel: str):
    active_recs = load_json(RECORDINGS_FILE, {})
    if channel in active_recs:
        info = active_recs[channel]
        pid = info['pid']
        try:
            p = psutil.Process(pid)
            p.terminate()
            del active_recs[channel] # Optimistic UI update
            save_json(RECORDINGS_FILE, active_recs)
            return {"status": "stopped"}
        except Exception as e:
            return JSONResponse(status_code=500, content={"error": str(e)})
    return JSONResponse(status_code=404, content={"error": "Channel not recording"})

@app.delete("/api/recording/{filename}")
async def delete_recording(filename: str):
    # 'filename' here is actually the ID, which is the folder name for new items
    # or the filename for legacy items.
    
    safe_name = os.path.basename(filename)
    
    # LOCK CHECK
    # We need to check if ANY file inside this folder is uploading, or if the folder itself is locked
    # For now, simplistic check against ID
    if safe_name in ACTIVE_UPLOADS:
        return JSONResponse(status_code=409, content={"error": "File is currently being uploaded. Please wait."})
        
    path = os.path.join(DATA_DIR, safe_name)
    
    if os.path.exists(path):
        try:
            if os.path.isdir(path):
                import shutil
                shutil.rmtree(path)
            else:
                os.remove(path)
            return {"status": "deleted"}
        except Exception as e:
            return JSONResponse(status_code=500, content={"error": str(e)})
            
    return JSONResponse(status_code=404, content={"error": "File/Folder not found"})

# API: Channels
@app.get("/api/channels")
async def get_channels():
    # Helper to migrate old format if needed
    data = load_json(CHANNELS_FILE, [])
    if data and isinstance(data[0], str):
        data = [{"name": ch, "active": True} for ch in data]
        save_json(CHANNELS_FILE, data)
    return data

@app.post("/api/channels")
async def add_channel(payload: dict):
    try:
        channel = payload.get("channel")
        if not channel: return JSONResponse(status_code=400, content={"error": "Missing channel"})
        
        channel = channel.lower().strip()
        channels = load_json(CHANNELS_FILE, [])
        
        # Migrate if needed
        if channels and isinstance(channels[0], str):
            channels = [{"name": ch, "active": True} for ch in channels]

        if not any(c['name'] == channel for c in channels):
            channels.append({"name": channel, "active": True})
            save_json(CHANNELS_FILE, channels)
            return {"status": "added", "channels": channels}
        
        return JSONResponse(status_code=409, content={"error": "Channel exists"})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.delete("/api/channels/{channel_name}")
async def delete_channel(channel_name: str):
    channels = load_json(CHANNELS_FILE, [])
    # Migrate
    if channels and isinstance(channels[0], str):
        channels = [{"name": ch, "active": True} for ch in channels]
        
    new_list = [c for c in channels if c['name'] != channel_name]
    save_json(CHANNELS_FILE, new_list)
    return {"status": "deleted", "channels": new_list}

@app.post("/api/channels/toggle/{channel_name}")
async def toggle_channel(channel_name: str):
    channels = load_json(CHANNELS_FILE, [])
    if channels and isinstance(channels[0], str):
        channels = [{"name": ch, "active": True} for ch in channels]
        
    for c in channels:
        if c['name'] == channel_name:
            c['active'] = not c.get('active', True)
            break
            
    save_json(CHANNELS_FILE, channels)
    return {"status": "toggled", "channels": channels}

# API: Recordings List
@app.get("/api/recordings")
async def list_recordings():
    result = get_recordings()
    # Inject upload status
    for rec in result:
        fname = rec["filename"]
        if fname in ACTIVE_UPLOADS:
             rec["upload_status"] = ACTIVE_UPLOADS[fname]
    return result

# API: Settings
@app.get("/api/settings")
async def get_settings():
    return settings_manager.load_settings()

@app.post("/api/settings")
async def update_settings(payload: dict):
    settings = settings_manager.load_settings()
    # Merge updates
    if "check_interval" in payload: settings["check_interval"] = int(payload["check_interval"])
    if "recording_format" in payload: settings["recording_format"] = payload["recording_format"]
    
    if "upload_targets" in payload:
        # Deep merge for upload targets
        for target, data in payload["upload_targets"].items():
            if target not in settings["upload_targets"]:
                settings["upload_targets"][target] = {}
            settings["upload_targets"][target].update(data)
            
    settings_manager.save_settings(settings)
    return settings

# --- Threaded Upload Logic ---

# Note: In FastAPI, 'def' endpoints run in a threadpool, which is exactly what we want 
# to avoid blocking the main event loop.

@app.post("/api/upload/archive")
def upload_archive(payload: dict):
    try:
        filename = payload.get("filename") # ID (folder or file)
        title = payload.get("title")
        if not filename: return JSONResponse(status_code=400, content={"error": "Missing filename"})
        
        safe_name = os.path.basename(filename)
        
        if safe_name in ACTIVE_UPLOADS:
            return JSONResponse(status_code=409, content={"error": "Already uploading"})

        path = os.path.join(DATA_DIR, safe_name)
        
        # Resolve actual video path
        video_path = path
        meta_path = None
        
        if os.path.isdir(path):
             # Folder logic
             meta_path = os.path.join(path, "meta.json")
             # Find video
             possible = [f for f in os.listdir(path) if f.lower().endswith(('.mp4', '.ts', '.mkv'))]
             if not possible:
                  return JSONResponse(status_code=404, content={"error": "No video file found in folder"})
             video_path = os.path.join(path, possible[0])
        
        
        # LOCK
        ACTIVE_UPLOADS[safe_name] = {"target": "Archive.org", "progress": 0, "status": "starting"}
        
        def prog_cb(curr, total):
            try:
                if total > 0:
                    pct = (curr / total) * 100
                else:
                    pct = 0
                ACTIVE_UPLOADS[safe_name]["progress"] = round(pct, 1)
                ACTIVE_UPLOADS[safe_name]["status"] = "uploading"
                # Optional: Print to terminal
                sys.stdout.write(f"\r[Archive Upload] {safe_name}: {pct:.1f}%")
                sys.stdout.flush()
            except:
                pass # Ignore logging errors

        try:
            settings = settings_manager.load_settings()
            uploader = uploader_service.UploaderService(settings)
            
            success, msg = uploader.upload_to_archive(video_path, metadata={'title': title, 'mediatype': 'movies'}, progress_callback=prog_cb)
            
            if success:
                print("\nUpload Complete!")
                
                # Save Link if folder
                if meta_path:
                    meta = load_json(meta_path, {})
                    if "upload_links" not in meta: meta["upload_links"] = {}
                    # Extract URL from msg or assume
                    # Msg is usually "Uploaded to URL"
                    url_part = msg.split("Uploaded to ")[-1]
                    meta["upload_links"]["archive"] = url_part
                    save_json(meta_path, meta)
                
                return {"status": "success", "message": msg}
            else:
                print(f"\nUpload Failed: {msg}")
                return JSONResponse(status_code=500, content={"error": msg})
        finally:
            # UNLOCK
            if safe_name in ACTIVE_UPLOADS:
                del ACTIVE_UPLOADS[safe_name]
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse(status_code=500, content={"error": f"Server Error: {str(e)}"})

@app.post("/api/upload/youtube")
def upload_youtube(payload: dict):
    try:
        filename = payload.get("filename") # This is ID
        title = payload.get("title")
        description = payload.get("description", "")
        privacy = payload.get("privacy", "private")
        
        if not filename: return JSONResponse(status_code=400, content={"error": "Missing filename"})

        safe_name = os.path.basename(filename)
        
        if safe_name in ACTIVE_UPLOADS:
            return JSONResponse(status_code=409, content={"error": "Already uploading"})

        path = os.path.join(DATA_DIR, safe_name)
        
        # Resolve actual video path
        video_path = path
        meta_path = None
        
        if os.path.isdir(path):
             meta_path = os.path.join(path, "meta.json")
             possible = [f for f in os.listdir(path) if f.lower().endswith(('.mp4', '.ts', '.mkv'))]
             if not possible:
                  return JSONResponse(status_code=404, content={"error": "No video file found in folder"})
             video_path = os.path.join(path, possible[0])
        
        # LOCK
        ACTIVE_UPLOADS[safe_name] = {"target": "YouTube", "progress": 0, "status": "starting"}

        def prog_cb(curr, total):
            try:
                if total > 0:
                    pct = (curr / total) * 100
                else: 
                    pct = 0
                ACTIVE_UPLOADS[safe_name]["progress"] = round(pct, 1)
                ACTIVE_UPLOADS[safe_name]["status"] = "uploading"
                sys.stdout.write(f"\r[YouTube Upload] {safe_name}: {pct:.1f}%")
                sys.stdout.flush()
            except:
                pass
        
        try:
            settings = settings_manager.load_settings()
            uploader = uploader_service.UploaderService(settings)
            
            success, msg = uploader.upload_to_youtube(video_path, title=title, description=description, privacy_status=privacy, progress_callback=prog_cb)
            
            if success:
                print("\nUpload Complete!")
                
                # Save Link if folder
                if meta_path:
                    meta = load_json(meta_path, {})
                    if "upload_links" not in meta: meta["upload_links"] = {}
                    # Extract ID from msg "Uploaded to YouTube! Video ID: ..."
                    if "Video ID: " in msg:
                        vid_id = msg.split("Video ID: ")[-1]
                        meta["upload_links"]["youtube"] = f"https://youtu.be/{vid_id}"
                        save_json(meta_path, meta)

                return {"status": "success", "message": msg}
            else:
                print(f"\nUpload Failed: {msg}")
                return JSONResponse(status_code=500, content={"error": msg})
        finally:
            # UNLOCK
            if safe_name in ACTIVE_UPLOADS:
                del ACTIVE_UPLOADS[safe_name]
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse(status_code=500, content={"error": f"Server Error: {str(e)}"})


# For OAuth, we need a slight adjustment as we are not using Streamlit's session state
# Ideally we initiate flow and return URL, then handle callback
running_flows = {}

@app.post("/api/auth/youtube/init")
async def init_youtube_auth(payload: dict):
    client_secrets = payload.get("client_secrets")
    # HARDCODED FOR PRODUCTION as requested
    redirect_uri = "https://gravador.quimerastudio.com.br/auth/callback" 
    print(f"DEBUG_AUTH: Initiating flow with redirect_uri={redirect_uri}", flush=True)
    
    settings = settings_manager.load_settings()
    uploader = uploader_service.UploaderService(settings)
    
    auth_url, error = uploader.get_auth_url(client_secrets, redirect_uri)
    
    if auth_url:
        # We need to persist the flow object to exchange the code later
        # In a single-user local app, a global var is "okay", but risky if restarted
        # uploader_service logic needs to be revisited as it stores flow in self._temp_flow
        # but 'uploader' instance is lost here.
        
        # We need to hack this a bit for the stateless API or use a global singleton for the uploader service
        running_flows["pending"] = uploader # Store the instance
        
        return {"auth_url": auth_url}
    else:
        return JSONResponse(status_code=500, content={"error": error})

@app.get("/auth/callback")
async def auth_callback(code: str):
    uploader = running_flows.get("pending")
    if not uploader:
        return "Error: No auth flow initiated or server restarted."
    
    token_json, msg = uploader.authenticate_youtube_with_code(code)
    
    if token_json:
        settings = settings_manager.load_settings()
        if "upload_targets" not in settings: settings["upload_targets"] = {}
        if "youtube" not in settings["upload_targets"]: settings["upload_targets"]["youtube"] = {}
        
        settings["upload_targets"]["youtube"]["token"] = token_json
        
        # Also save the client secrets if we have them from the init step, 
        # usually they are in 'uploader.settings' but might not be PERMANENTLY saved yet if they came from payload
        # But we don't have easy access to the payload secrets here. 
        # Assuming user saves them in the UI separately or we trust the token.
        
        settings_manager.save_settings(settings)
        return "Authentication Successful! You can close this window."
    else:
        return f"Authentication Failed: {msg}"

if __name__ == "__main__":
    # Access log disabled to prevent polling spam in terminal.
    # Errors will still be visible due to our global exception handling.
    uvicorn.run(app, host="0.0.0.0", port=8501, access_log=False)
