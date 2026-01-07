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
    search_pattern = os.path.join(DATA_DIR, "rec_*.*")
    all_files = glob.glob(search_pattern)
    files = [f for f in all_files if f.lower().endswith(('.mp4', '.ts', '.mkv'))]
    files.sort(key=os.path.getmtime, reverse=True)
    
    result = []
    active_recs = load_json(RECORDINGS_FILE, {})
    
    for f in files:
        filename_only = os.path.basename(f)
        try:
            size_mb = os.path.getsize(f) / (1024 * 1024)
        except OSError:
            size_mb = 0
            
        timestamp = os.path.getmtime(f)
        date_str = datetime.fromtimestamp(timestamp).strftime('%d/%m/%Y %H:%M')
        
        is_active = False
        for info in active_recs.values():
            if os.path.abspath(info['filename']) == os.path.abspath(f):
                is_active = True
                break
        
        # Thumbs
        thumb_url = None
        if not is_active: # Don't thumb active recordings (file locked/changing)
            thumb_url = generate_thumbnail(f)
                
        result.append({
            "filename": filename_only,
            "path": f, # Absolute path for internal use
            "url": f"/files/{filename_only}",
            "thumbnail": thumb_url,
            "size_mb": round(size_mb, 1),
            "date": date_str,
            "is_active": is_active
        })
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
    # Security check: only allow deleting files in static dir
    safe_name = os.path.basename(filename)
    
    # LOCK CHECK
    if safe_name in ACTIVE_UPLOADS:
        return JSONResponse(status_code=409, content={"error": "File is currently being uploaded. Please wait."})
        
    path = os.path.join(DATA_DIR, safe_name)
    if os.path.exists(path):
        try:
            os.remove(path)
            return {"status": "deleted"}
        except Exception as e:
            return JSONResponse(status_code=500, content={"error": str(e)})
    return JSONResponse(status_code=404, content={"error": "File not found"})

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
        filename = payload.get("filename")
        title = payload.get("title")
        if not filename: return JSONResponse(status_code=400, content={"error": "Missing filename"})
        
        safe_name = os.path.basename(filename)
        
        if safe_name in ACTIVE_UPLOADS:
            return JSONResponse(status_code=409, content={"error": "Already uploading"})

        path = os.path.join(DATA_DIR, safe_name)
        
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
            
            success, msg = uploader.upload_to_archive(path, metadata={'title': title, 'mediatype': 'movies'}, progress_callback=prog_cb)
            
            if success:
                print("\nUpload Complete!")
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
        filename = payload.get("filename")
        title = payload.get("title")
        description = payload.get("description", "")
        privacy = payload.get("privacy", "private")
        
        if not filename: return JSONResponse(status_code=400, content={"error": "Missing filename"})

        safe_name = os.path.basename(filename)
        
        if safe_name in ACTIVE_UPLOADS:
            return JSONResponse(status_code=409, content={"error": "Already uploading"})

        path = os.path.join(DATA_DIR, safe_name)
        
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
            
            success, msg = uploader.upload_to_youtube(path, title=title, description=description, privacy_status=privacy, progress_callback=prog_cb)
            
            if success:
                print("\nUpload Complete!")
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
    redirect_uri = "http://localhost:8501/auth/callback" # Changed for local dev
    
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
