import os
import requests
import time
from dotenv import load_dotenv

load_dotenv()

class FBUploader:
    def __init__(self):
        """
        Initialize the Facebook Uploader.
        """
        self.api_version = "v19.0"
        self.base_url = "https://graph.facebook.com"

    def upload_video(self, page_id, access_token, file_path, title, caption, retries=3):
        """
        Uploads a video as a Facebook Reel using the Reels Publishing API.
        This gives much higher organic reach than standard video uploads.
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Video file not found at: {file_path}")
            
        file_size = os.path.getsize(file_path)
        print(f"Uploading video as Reel to Facebook Page {page_id} (Size: {file_size} bytes)...")
        
        # Step 1: Initialize the Reel Upload
        init_url = f"{self.base_url}/{self.api_version}/{page_id}/video_reels"
        init_params = {
            "upload_phase": "start",
            "access_token": access_token
        }
        
        for attempt in range(retries):
            try:
                # 1. Start Session
                init_resp = requests.post(init_url, params=init_params, timeout=30)
                if init_resp.status_code != 200:
                    print(f"Failed to initialize Reel upload (Attempt {attempt+1}/{retries}). Code {init_resp.status_code}: {init_resp.text}")
                    if attempt < retries - 1:
                        time.sleep(10)
                        continue
                    init_resp.raise_for_status()
                
                init_data = init_resp.json()
                video_id = init_data.get("video_id")
                upload_url = init_data.get("upload_url")
                
                if not video_id or not upload_url:
                    raise ValueError(f"Initialization response missing video_id or upload_url: {init_data}")
                
                # Step 2: Upload the video file (binary upload)
                print(f"Uploading binary data to upload_url for video_id {video_id}...")
                headers = {
                    "Authorization": f"OAuth {access_token}",
                    "offset": "0",
                    "file_size": str(file_size),
                    "Content-Type": "application/octet-stream"
                }
                
                with open(file_path, "rb") as f:
                    upload_resp = requests.post(upload_url, headers=headers, data=f, timeout=300)
                
                if upload_resp.status_code != 200:
                    print(f"Failed to upload video binary (Attempt {attempt+1}/{retries}). Code {upload_resp.status_code}: {upload_resp.text}")
                    if attempt < retries - 1:
                        time.sleep(10)
                        continue
                    upload_resp.raise_for_status()
                
                # Step 3: Publish the Reel
                print(f"Publishing Reel {video_id}...")
                publish_url = f"{self.base_url}/{self.api_version}/{page_id}/video_reels"
                publish_params = {
                    "upload_phase": "finish",
                    "video_id": video_id,
                    "video_state": "PUBLISHED",
                    "description": caption,
                    "access_token": access_token
                }
                
                publish_resp = requests.post(publish_url, params=publish_params, timeout=30)
                if publish_resp.status_code == 200:
                    print(f"Success! Reel published. Facebook Reel ID: {video_id}")
                    return video_id
                else:
                    print(f"Failed to publish Reel (Attempt {attempt+1}/{retries}). Code {publish_resp.status_code}: {publish_resp.text}")
                    if attempt < retries - 1:
                        time.sleep(10)
                        continue
                    publish_resp.raise_for_status()
                    
            except Exception as e:
                print(f"Error during Reel upload (Attempt {attempt+1}/{retries}): {e}")
                if attempt < retries - 1:
                    time.sleep(10)
                else:
                    raise e
        return None

    def upload_photo(self, page_id, access_token, file_path, caption, retries=3):
        """
        Uploads an image to the specified Facebook page feed.
        """
        url = f"{self.base_url}/{self.api_version}/{page_id}/photos"
        
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Image file not found at: {file_path}")
            
        print(f"Uploading photo post to Facebook Page {page_id}...")
        
        params = {
            "access_token": access_token,
            "caption": caption
        }
        
        for attempt in range(retries):
            try:
                with open(file_path, "rb") as photo_file:
                    files = {
                        "source": photo_file
                    }
                    
                    response = requests.post(url, data=params, files=files, timeout=120)
                    
                    if response.status_code == 200:
                        res_data = response.json()
                        print(f"Success! Photo uploaded. Facebook Photo ID: {res_data.get('id')}")
                        return res_data.get('id')
                    else:
                        print(f"Upload attempt {attempt + 1} failed. Code {response.status_code}: {response.text}")
                        if attempt < retries - 1:
                            time.sleep(10)
                            continue
                        response.raise_for_status()
            except Exception as e:
                print(f"Error during photo upload (Attempt {attempt + 1}/{retries}): {e}")
                if attempt < retries - 1:
                    time.sleep(10)
                else:
                    raise e
        return None
