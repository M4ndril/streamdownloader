import os
import json
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
    from googleapiclient.http import MediaFileUpload
except ImportError:
    InstalledAppFlow = None
    Credentials = None
    build = None

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]

class UploaderService:
    def __init__(self, settings):
        self.settings = settings
        
    def upload_to_archive(self, file_path, metadata=None):
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
        # Create a unique identifier based on filename (sanitize it)
        identifier = filename.replace(".", "_").replace(" ", "_").lower()
        
        # Basic metadata
        if not metadata:
            metadata = {
                'title': filename,
                'mediatype': 'movies'
            }

        try:
            # Configure session
            r = upload(
                identifier, 
                files={filename: file_path}, 
                metadata=metadata,
                access_key=access_key,
                secret_key=secret_key,
                verbose=True
            )
            
            if r[0].status_code == 200:
                return True, f"Uploaded to https://archive.org/details/{identifier}"
            else:
                return False, f"Upload failed: {r[0].status_code} - {r[0].text}"
                
        except Exception as e:
            return False, str(e)

    def get_youtube_credentials(self):
        yt_settings = self.settings.get("upload_targets", {}).get("youtube", {})
        token_json = yt_settings.get("token")
        
        creds = None
        if token_json:
            try:
                # token_json is a string, check if it's actually a dict or json string
                if isinstance(token_json, str):
                    token_data = json.loads(token_json)
                else:
                    token_data = token_json
                creds = Credentials.from_authorized_user_info(token_data, SCOPES)
            except Exception as e:
                print(f"Error loading token: {e}")
                
        return creds

    def get_auth_url(self, client_secrets_content):
        """Generate authorization URL for manual OAuth flow"""
        if not InstalledAppFlow:
            return None, "Google API libraries not installed."
            
        try:
            # Load client secrets from the provided string/dict
            if isinstance(client_secrets_content, str):
                client_config = json.loads(client_secrets_content)
            else:
                client_config = client_secrets_content

            flow = InstalledAppFlow.from_client_config(
                client_config, 
                SCOPES,
                redirect_uri='urn:ietf:wg:oauth:2.0:oob'  # Manual flow
            )
            
            auth_url, _ = flow.authorization_url(prompt='consent')
            
            # Store flow temporarily (in a real app, use session state)
            self._temp_flow = flow
            
            return auth_url, None
            
        except Exception as e:
            return None, f"Failed to generate auth URL: {str(e)}"
    
    def authenticate_youtube_with_code(self, auth_code):
        """Complete OAuth flow with authorization code from user"""
        if not hasattr(self, '_temp_flow'):
            return None, "No authentication flow in progress. Please generate auth URL first."
            
        try:
            self._temp_flow.fetch_token(code=auth_code)
            creds = self._temp_flow.credentials
            
            # Clean up temp flow
            delattr(self, '_temp_flow')
            
            return creds.to_json(), "Authentication successful."
            
        except Exception as e:
            return None, f"Authentication failed: {str(e)}"

    def upload_to_youtube(self, file_path, title, description, privacy_status="private"):
        if not build:
            return False, "Google API libraries not installed."
            
        creds = self.get_youtube_credentials()
        
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())
                    # ideally we should save the refreshed token back to settings here
                    # effectively we return the new token so the caller can save it?
                    # For now just use it in memory
                except Exception as e:
                     return False, f"Token expired and refresh failed: {e}"
            else:
                return False, "Valid YouTube credentials not found. Please authenticate in Settings."

        try:
            youtube = build("youtube", "v3", credentials=creds)

            body = {
                "snippet": {
                    "title": title,
                    "description": description,
                    "tags": ["streamlink", "twitch_recorder"],
                    "categoryId": "20" # Gaming
                },
                "status": {
                    "privacyStatus": privacy_status
                }
            }

            media = MediaFileUpload(file_path, chunksize=-1, resumable=True)

            request = youtube.videos().insert(
                part="snippet,status",
                body=body,
                media_body=media
            )

            response = None
            while response is None:
                status, response = request.next_chunk()
                if status:
                    # Could enable progress callback here
                    pass

            if "id" in response:
                return True, f"Uploaded to YouTube! Video ID: {response['id']}"
            else:
                return False, f"Upload failed: {response}"

        except Exception as e:
            return False, f"YouTube Upload Error: {str(e)}"

