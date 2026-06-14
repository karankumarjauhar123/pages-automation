import os
import requests
import time

class Uploader:
    def __init__(self):
        self.api_version = "v19.0"
        self.base_url = "https://graph.facebook.com"

    def upload_reel(self, page_id, access_token, file_path, title, caption, retries=3):
        """
        Uploads a video to the specified Facebook page using the Graph API.
        Facebook automatically publishes vertical short videos as Reels.
        """
        url = f"{self.base_url}/{self.api_version}/{page_id}/videos"
        
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Video file not found at: {file_path}")
            
        print(f"[Uploader] Uploading video '{title}' to Facebook Page {page_id}...")
        
        params = {
            "access_token": access_token,
            "title": title,
            "description": caption  # For videos, description contains the feed caption text
        }
        
        for attempt in range(retries):
            try:
                with open(file_path, "rb") as video_file:
                    files = {
                        "source": video_file
                    }
                    
                    # 5-minute timeout for large video uploads
                    response = requests.post(url, data=params, files=files, timeout=300)
                    
                    if response.status_code == 200:
                        res_data = response.json()
                        fb_id = res_data.get('id')
                        print(f"[Uploader] ✅ Upload successful! Facebook Video ID: {fb_id}")
                        return fb_id
                    else:
                        print(f"[Uploader] ⚠️ Attempt {attempt + 1} failed. Status: {response.status_code}, Response: {response.text}")
                        if attempt < retries - 1:
                            time.sleep(15)
                            continue
                        response.raise_for_status()
            except Exception as e:
                print(f"[Uploader] ❌ Error during video upload (Attempt {attempt + 1}/{retries}): {e}")
                if attempt < retries - 1:
                    time.sleep(15)
                else:
                    raise e
        return None
