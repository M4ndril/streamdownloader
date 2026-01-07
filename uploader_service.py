import os
import json
import sys
import threading

try:
    from internetarchive import upload, get_item
except ImportError:
    upload = None
    get_item = None

try:
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaIoBaseUpload
except ImportError:
    InstalledAppFlow = None
    Credentials = None
    build = None
    MediaIoBaseUpload = None

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]

class ProgressFileObject(object):
    def __init__(self, filename, callback=None):
        self._file = open(filename, 'rb')
        self._callback = callback
        self._total_size = os.path.getsize(filename)
        self._seen_so_far = 0
        self._lock = threading.Lock()

    def read(self, size=-1):
        data = self._file.read(size)
        with self._lock:
            self._seen_so_far += len(data)
            if self._callback:
                self._callback(self._seen_so_far, self._total_size)
        return data

    def seek(self, offset, whence=0):
        # Used by some uploaders to reset or check position
        return self._file.seek(offset, whence)
        
    def tell(self):
        return self._file.tell()

    def close(self):
        self._file.close()

    def __len__(self):
        return self._total_size

    @property
    def name(self):
        return self._file.name

    @property
    def mode(self):
        return self._file.mode


class UploaderService:
    def __init__(self, settings):
        self.settings = settings
        
    def upload_to_archive(self, file_path, metadata=None, progress_callback=None):
        if not upload:
            return False, "Library 'internetarchive' not installed."

        archive_settings = self.settings.get("upload_targets", {}).get("archive", {})
        access_key = archive_settings.get("access_key")
        secret_key = archive_settings.get("secret_key")

        if not access_key or not secret_key:
            return False, "Archive.org credentials not configured."

        if not os.path.exists(file_path):
            return False, "File not found."

        filename = os.path.basename(file_path)
        # Ensure unique identifier for Archive.org
        import time
        unique_suffix = int(time.time())
        # If filename is generic "video.mp4", prepend "stream_recording_" or similar if possible, 
        # but easier to just use "stream_rec_" + suffix
        # The user's files are now "video.mp4" inside unique folders.
        # We should try to use the TITLE if available or just a timestamped name.
        # Let's generate: "stream_rec_{timestamp}"
        identifier = f"stream_rec_{unique_suffix}"
        
        if not metadata:
            metadata = {'title': filename, 'mediatype': 'movies'}

        # Wrapper for progress
        f_obj = ProgressFileObject(file_path, callback=progress_callback)

        try:
            # We pass the file object instead of path
            r = upload(
                identifier, 
                files={filename: f_obj}, 
                metadata=metadata,
                access_key=access_key,
                secret_key=secret_key,
                verbose=True 
            )
            
            f_obj.close()
            
            if r[0].status_code == 200:
                return True, f"Uploaded to https://archive.org/details/{identifier}"
            else:
                return False, f"Upload failed: {r[0].status_code} - {r[0].text}"
                
        except Exception as e:
            f_obj.close()
            return False, str(e)

    def get_youtube_credentials(self):
        yt_settings = self.settings.get("upload_targets", {}).get("youtube", {})
        token_json = yt_settings.get("token")
        
        creds = None
        if token_json:
            try:
                if isinstance(token_json, str):
                    token_data = json.loads(token_json)
                else:
                    token_data = token_json
                creds = Credentials.from_authorized_user_info(token_data, SCOPES)
            except Exception as e:
                print(f"Error loading token: {e}")
                
        return creds

    def get_auth_url(self, client_secrets_content, redirect_uri):
        if not InstalledAppFlow:
            return None, "Google API libraries not installed."
            
        try:
            if isinstance(client_secrets_content, str):
                client_config = json.loads(client_secrets_content)
            else:
                client_config = client_secrets_content

            flow = InstalledAppFlow.from_client_config(
                client_config, 
                SCOPES,
                redirect_uri=redirect_uri
            )
            
            auth_url, _ = flow.authorization_url(prompt='consent')
            self._temp_flow = flow
            return auth_url, None
            
        except Exception as e:
            return None, f"Failed to generate auth URL: {str(e)}"
    
    def authenticate_youtube_with_code(self, auth_code):
        if not hasattr(self, '_temp_flow'):
            return None, "No authentication flow in progress."
            
        try:
            self._temp_flow.fetch_token(code=auth_code)
            creds = self._temp_flow.credentials
            delattr(self, '_temp_flow')
            return creds.to_json(), "Authentication successful."
            
        except Exception as e:
            return None, f"Authentication failed: {str(e)}"

    def upload_to_youtube(self, file_path, title, description, privacy_status="private", progress_callback=None):
        if not build:
            return False, "Google API libraries not installed."
            
        creds = self.get_youtube_credentials()
        
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())
                except Exception as e:
                     return False, f"Token expired and refresh failed: {e}"
            else:
                return False, "Valid YouTube credentials not found."

        try:
            youtube = build("youtube", "v3", credentials=creds)

            body = {
                "snippet": {
                    "title": title,
                    "description": description,
                    "tags": ["streamlink", "twitch_recorder"],
                    "categoryId": "20"
                },
                "status": {"privacyStatus": privacy_status}
            }
            
            # Use standard MediaFileUpload - safe and robust
            from googleapiclient.http import MediaFileUpload
            media = MediaFileUpload(file_path, chunksize=1024*1024, resumable=True)

            request = youtube.videos().insert(
                part="snippet,status",
                body=body,
                media_body=media
            )

            response = None
            while response is None:
                status, response = request.next_chunk()
                if status and progress_callback:
                    # Use native Google API progress status
                    progress_callback(status.resumable_progress, status.total_size)
            
            # Ensure 100% is reported at the end
            if progress_callback and os.path.exists(file_path):
                 total = os.path.getsize(file_path)
                 progress_callback(total, total)

            if "id" in response:
                return True, f"Uploaded to YouTube! Video ID: {response['id']}"
            else:
                return False, f"Upload failed: {response}"

        except Exception as e:
            return False, f"YouTube Upload Error: {str(e)}"

