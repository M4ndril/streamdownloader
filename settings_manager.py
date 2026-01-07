import json
import os

# Define defaults
DEFAULT_SETTINGS = {
    "check_interval": 15,
    "upload_targets": {
        "archive": {
            "access_key": "",
            "secret_key": ""
        },
        "youtube": {
            "enabled": False,
            "client_secrets": "",  # JSON content or path
            "token": ""            # JSON content of the token
        },
        "drive": {
            "enabled": False  # Future placeholder
        }
    }
}

DATA_DIR = "data"
SETTINGS_FILE = os.path.join(DATA_DIR, "settings.json")

def load_settings():
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR)
        
    if os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE, "r") as f:
            try:
                data = json.load(f)
                # Merge with defaults to ensure all keys exist
                # Simple merge: top level keys
                for k, v in DEFAULT_SETTINGS.items():
                    if k not in data:
                        data[k] = v
                return data
            except json.JSONDecodeError:
                return DEFAULT_SETTINGS
    return DEFAULT_SETTINGS

def save_settings(settings):
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR)
    with open(SETTINGS_FILE, "w") as f:
        json.dump(settings, f, indent=4)
