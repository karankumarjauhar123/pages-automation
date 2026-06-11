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
        Uploads a video to the specified Facebook page using the Graph API.
        Works for Reels/Shorts and standard video posts.
        """
        url = f"{self.base_url}/{self.api_version}/{page_id}/videos"
        
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Video file not found at: {file_path}")
            
        print(f"Uploading video '{title}' to Facebook Page {page_id}...")
        
        params = {
            "access_token": access_token,
            "title": title,
            "description": caption  # For videos, description is the post text
        }
        
        for attempt in range(retries):
            try:
                with open(file_path, "rb") as video_file:
                    files = {
                        "source": video_file
                    }
                    
                    response = requests.post(url, data=params, files=files, timeout=300) # 5 min timeout for video upload
                    
                    if response.status_code == 200:
                        res_data = response.json()
                        print(f"Success! Video uploaded. Facebook Video ID: {res_data.get('id')}")
                        return res_data.get('id')
                    else:
                        print(f"Upload attempt {attempt + 1} failed. Code {response.status_code}: {response.text}")
                        if attempt < retries - 1:
                            time.sleep(10)
                            continue
                        response.raise_for_status()
            except Exception as e:
                print(f"Error during video upload (Attempt {attempt + 1}/{retries}): {e}")
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
