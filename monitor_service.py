import time
import json
import os
import sys
import subprocess
import psutil
import streamlink
from datetime import datetime

# Configuração de Diretórios
DATA_DIR = "static"
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
                            print(f"Channel {channel} is ONLINE. Starting recording...")
                            timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
                            
                            rec_format = settings.get("recording_format", "mp4")
                            filename = os.path.join(DATA_DIR, f"rec_{channel}_{timestamp}.{rec_format}")

                            
                            cmd = [sys.executable, "-m", "streamlink", url, "best", "-o", filename]
                            
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
                            active_recs[channel] = {
                                "pid": proc.pid,
                                "filename": filename,
                                "start_time": timestamp
                            }
                            save_json(RECORDINGS_FILE, active_recs)
                            print(f"Started recording {channel} (PID {proc.pid})")
                            
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

