import time
import json
import os
import sys
import subprocess
import psutil
import streamlink
from datetime import datetime

# Configuração de Diretórios
DATA_DIR = "data"
if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)

CHANNELS_FILE = os.path.join(DATA_DIR, "watchlist.json")
RECORDINGS_FILE = os.path.join(DATA_DIR, "active_recordings.json")
SERVICE_STATE_FILE = os.path.join(DATA_DIR, "service_state.json")

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

def is_process_running(pid):
    try:
        p = psutil.Process(pid)
        return p.is_running() and p.status() != psutil.STATUS_ZOMBIE
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return False

import settings_manager

def main():
    print("Starting Monitor Service...")
    
    while True:
        try:
            # 0. Load Settings
            settings = settings_manager.load_settings()
            check_interval = settings.get("check_interval", 15)

            # 1. Check Service State
            state = load_json(SERVICE_STATE_FILE, {"enabled": False})
            
            if state.get("enabled"):
                channels = load_json(CHANNELS_FILE, [])
                active_recs = load_json(RECORDINGS_FILE, {})
                
                # 2. Clean up dead recordings
                dirty = False
                for ch_name, info in list(active_recs.items()):
                    if not is_process_running(info['pid']):
                        print(f"Process for {ch_name} (PID {info['pid']}) ended.")
                        
                        del active_recs[ch_name]
                        dirty = True


                
                if dirty:
                    save_json(RECORDINGS_FILE, active_recs)

                # 3. Check for new recordings
                active_targets = [c['name'] for c in channels if c.get('active', True)]
                
                for channel in active_targets:
                    # Skip if already recording
                    if channel in active_recs:
                        continue
                    
                    url = f"https://www.twitch.tv/{channel}"
                    try:
                        # Check stream availability
                        streams = streamlink.streams(url)
                        if streams:
                            print(f"Channel {channel} is ONLINE. Fetching metadata...")
                            
                            # 1. Fetch Metadata (streamlink --jsonURL)
                            meta_info = {}
                            try:
                                json_cmd = [sys.executable, "-m", "streamlink", "--json", url]
                                res = subprocess.run(json_cmd, capture_output=True, text=True, timeout=15)
                                if res.returncode == 0:
                                    import json as std_json
                                    data = std_json.loads(res.stdout)
                                    # Streamlink JSON output has a 'streams' key usually, or just general info
                                    # We usually want the 'title' and 'game' (category) from the first stream logic or 'metadata'
                                    # Actual output depends on plugin, but usually: 
                                    # { "streams": { "best": { ... } }, "metadata": { "title": "...", "id": "...", "author": "..." } }
                                    # OR for Twitch it might be directly in plugin payload. 
                                    # Let's try to extract safely.
                                    if "metadata" in data and data["metadata"]:
                                         meta_info["title"] = data["metadata"].get("title", "No Title")
                                         meta_info["game"] = data["metadata"].get("game", "Unknown Game")
                                         meta_info["author"] = data["metadata"].get("author", channel)
                                    else:
                                        # Fallback
                                        meta_info["title"] = "Unknown Title"
                                        meta_info["game"] = "Unknown Game"
                            except Exception as e:
                                print(f"Metadata fetch failed: {e}")
                                meta_info = {"title": "Error fetching title", "game": "Unknown"}

                            print(f"Starting recording for {channel}...")
                            timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
                            
                            # 2. Create Directory
                            rec_folder_name = f"rec_{channel}_{timestamp}"
                            rec_folder_path = os.path.join(DATA_DIR, rec_folder_name)
                            os.makedirs(rec_folder_path, exist_ok=True)
                            
                            rec_format = settings.get("recording_format", "mp4")
                            # We keep simple filename inside the folder
                            filename_rel = f"video.{rec_format}" 
                            filename_abs = os.path.join(rec_folder_path, filename_rel)

                            # 3. Save Metadata
                            meta_file = os.path.join(rec_folder_path, "meta.json")
                            meta_info["channel"] = channel
                            meta_info["start_time"] = timestamp
                            meta_info["format"] = rec_format
                            save_json(meta_file, meta_info)

                            # 4. Start Recording
                            cmd = [sys.executable, "-m", "streamlink", url, "best", "-o", filename_abs]
                            
                            kwargs = {}
                            if sys.platform == "win32":
                                kwargs['creationflags'] = 0x08000000
                            
                            # Spawn process
                            proc = subprocess.Popen(
                                cmd, 
                                stdout=subprocess.DEVNULL, 
                                stderr=subprocess.DEVNULL,
                                **kwargs
                            )
                            
                            # Update tracking
                            # Record the FOLDER name as the ID/Key mostly, but for compat we track the path/pid
                            active_recs[channel] = {
                                "pid": proc.pid,
                                "folder_name": rec_folder_name,
                                "filename": filename_abs, # Keep full path for legacy compat/checking
                                "start_time": timestamp
                            }
                            save_json(RECORDINGS_FILE, active_recs)
                            print(f"Started recording {channel} (PID {proc.pid}) in {rec_folder_name}")
                            
                    except streamlink.PluginError:
                        pass # Channel offline or invalid
                    except Exception as e:
                        print(f"Error checking {channel}: {e}")
            
            else:
                # Service disabled, just wait
                pass

        except Exception as e:
            print(f"Monitor Loop Error: {e}")
        
        # Wait before next cycle
        time.sleep(check_interval)

import signal

def cleanup(signum, frame):
    print("\n🛑 Stopping Monitor Service...")
    # Kill all active recording processes
    active_recs = load_json(RECORDINGS_FILE, {})
    for ch_name, info in active_recs.items():
        pid = info.get('pid')
        if pid:
            try:
                print(f"Killing recording for {ch_name} (PID {pid})...")
                p = psutil.Process(pid)
                p.terminate()
            except:
                pass
    sys.exit(0)

if __name__ == "__main__":
    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)
    main()

