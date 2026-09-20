"""Uploads processed images to a Google Drive folder using OAuth user
credentials (i.e. your own Google account), instead of a service account.

Why: service accounts have no personal storage quota, so uploads to a
regular (non-Shared-Drive) folder fail with `storageQuotaExceeded`. Signing
in as a real user avoids that entirely.

Setup requirement:
  1. In Google Cloud Console, create an OAuth client ID of type
     "Desktop app" and download it as `client_secret.json` (or point
     GOOGLE_OAUTH_CLIENT_FILE at wherever you saved it).
  2. Add your own Google account as a "Test user" on the OAuth consent
     screen (required while the app is in "Testing" publishing status).
  3. The first time this runs, it opens a browser window for you to log in
     and approve access. A `token.json` file is then cached alongside it
     (path set by GOOGLE_OAUTH_TOKEN_FILE) so future runs skip the login
     step and silently refresh the token instead.
  4. DRIVE_FOLDER_ID should point to a folder your own account owns (or has
     Editor access to) -- files will be uploaded there under your account's
     normal storage quota.
"""
import io
import os

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

# drive.file: only lets the app see/manage files it creates itself (safer
# than the full "drive" scope, and sufficient for uploading images).
SCOPES = ["https://www.googleapis.com/auth/drive.file"]


class DriveUploader:
    def __init__(self, client_secret_file: str, folder_id: str, token_file: str = "./token.json"):
        if not folder_id or folder_id.strip().upper() in ("", "PUT_YOUR_DRIVE_FOLDER_ID_HERE"):
            raise RuntimeError(
                "storage.drive_folder_id in config.yaml is still the placeholder value -- it was "
                "never replaced with a real Google Drive folder ID. Open a folder in Drive, copy the "
                "long ID from its URL (drive.google.com/drive/folders/<THIS PART>), and paste it into "
                "config.yaml (or the Settings page in the dashboard) before running again."
            )
        self.folder_id = folder_id
        creds = self._get_credentials(client_secret_file, token_file)
        self.service = build("drive", "v3", credentials=creds)
        self._verify_folder()

    def _verify_folder(self):
        """Fails immediately and clearly if the folder ID doesn't exist or
        this account can't see it, instead of letting every single upload
        in the run fail one-by-one with a raw Google API error."""
        try:
            meta = self.service.files().get(fileId=self.folder_id, fields="id, name, mimeType, trashed").execute()
        except Exception as e:
            raise RuntimeError(
                f"Could not access Google Drive folder ID '{self.folder_id}': {e}. Double-check the ID "
                "(from the folder's URL) and that this Google account has at least Viewer/Editor access to it."
            )
        if meta.get("mimeType") != "application/vnd.google-apps.folder":
            raise RuntimeError(f"Drive ID '{self.folder_id}' exists but is not a folder ({meta.get('name')!r}).")
        if meta.get("trashed"):
            raise RuntimeError(f"Drive folder '{meta.get('name')}' ({self.folder_id}) is in the Trash.")

    @staticmethod
    def _get_credentials(client_secret_file: str, token_file: str) -> Credentials:
        creds = None

        if os.path.exists(token_file):
            creds = Credentials.from_authorized_user_file(token_file, SCOPES)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                if not os.path.exists(client_secret_file):
                    raise FileNotFoundError(
                        f"OAuth client secret file not found at {client_secret_file}. "
                        "Download it from Google Cloud Console (OAuth client ID -> "
                        "Desktop app) and point GOOGLE_OAUTH_CLIENT_FILE at it."
                    )
                flow = InstalledAppFlow.from_client_secrets_file(client_secret_file, SCOPES)
                # Opens a local browser window for one-time login/consent.
                creds = flow.run_local_server(port=0)

            # Cache (or refresh) the token so subsequent runs don't need a browser.
            with open(token_file, "w") as f:
                f.write(creds.to_json())

        return creds

    @classmethod
    def from_token_info(cls, token_info: dict, folder_id: str):
        """Alternate constructor for headless deployments (e.g. Streamlit
        Community Cloud) where there's no browser to complete an interactive
        login. `token_info` is the dict produced by generate_drive_token.py
        (typically loaded from st.secrets on a deployed app). Requires a
        valid refresh_token; raises if the credentials can't be refreshed
        without user interaction."""
        self = cls.__new__(cls)
        self.folder_id = folder_id
        creds = Credentials.from_authorized_user_info(dict(token_info), SCOPES)
        if not creds.valid:
            if creds.refresh_token:
                creds.refresh(Request())
            else:
                raise RuntimeError(
                    "Stored Drive token has no refresh_token and can't be "
                    "renewed without a browser login. Re-run "
                    "generate_drive_token.py locally and update the secret."
                )
        self.service = build("drive", "v3", credentials=creds)
        self._verify_folder()
        return self

    def upload_image(self, filename: str, image_bytes: bytes) -> str:
        file_metadata = {"name": filename, "parents": [self.folder_id]}
        media = MediaIoBaseUpload(io.BytesIO(image_bytes), mimetype="image/jpeg", resumable=False)
        file = self.service.files().create(
            body=file_metadata, media_body=media, fields="id, webViewLink"
        ).execute()
        return file.get("webViewLink", f"https://drive.google.com/file/d/{file.get('id')}/view")


class LocalStorageUploader:
    """Fallback storage used when no Google Drive is configured yet (e.g.
    first-time setup, or testing the dashboard without OAuth). Saves
    approved images under ./approved_images/ instead of uploading anywhere,
    so the rest of the pipeline (scoring, review, reporting) can be tried
    end-to-end before Drive is wired up."""
    def __init__(self, output_dir: str = "./approved_images"):
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)

    def upload_image(self, filename: str, image_bytes: bytes) -> str:
        path = os.path.join(self.output_dir, filename)
        with open(path, "wb") as f:
            f.write(image_bytes)
        return f"file://{os.path.abspath(path)}"
