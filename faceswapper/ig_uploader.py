import os
import time
import requests

class IGUploader:
    def __init__(self):
        self.api_version = "v19.0"
        self.base_url = "https://graph.facebook.com"

    def upload_to_temp_host(self, file_path):
        """
        Uploads local video file to a temporary public host (Catbox or Tmpfiles)
        so Instagram API can download it.
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found at: {file_path}")

        print(f"[IGUploader] 📤 Uploading video to temporary public host...")

        # --- Try Catbox.moe ---
        try:
            url = "https://catbox.moe/user/api.php"
            data = {"reqtype": "fileupload"}
            with open(file_path, "rb") as f:
                files = {"fileToUpload": f}
                response = requests.post(url, data=data, files=files, timeout=120)
                
            if response.status_code == 200 and response.text.startswith("https://"):
                temp_url = response.text.strip()
                print(f"[IGUploader] ✅ Uploaded to Catbox! Public URL: {temp_url}")
                return temp_url
            else:
                print(f"[IGUploader] ⚠️ Catbox upload returned unexpected result: {response.text}")
        except Exception as e:
            print(f"[IGUploader] ⚠️ Catbox upload failed: {e}")

        # --- Fallback: Tmpfiles.org ---
        try:
            print(f"[IGUploader] 🔄 Trying fallback tmpfiles.org...")
            url = "https://tmpfiles.org/api/v1/upload"
            with open(file_path, "rb") as f:
                files = {"file": f}
                response = requests.post(url, files=files, timeout=120)

            if response.status_code == 200:
                res_data = response.json()
                raw_url = res_data.get("data", {}).get("url")
                if raw_url:
                    # Convert view URL to direct download URL (insert /dl/ after domain)
                    # From: https://tmpfiles.org/12345/filename.mp4
                    # To:   https://tmpfiles.org/dl/12345/filename.mp4
                    temp_url = raw_url.replace("tmpfiles.org/", "tmpfiles.org/dl/")
                    print(f"[IGUploader] ✅ Uploaded to Tmpfiles! Public URL: {temp_url}")
                    return temp_url
            print(f"[IGUploader] ⚠️ Tmpfiles upload returned status: {response.status_code}")
        except Exception as e:
            print(f"[IGUploader] ❌ Tmpfiles upload failed: {e}")

        raise RuntimeError("Failed to upload video to any temporary hosting service.")

    def upload_instagram_reel(self, ig_user_id, access_token, file_path, caption):
        """
        Uploads a video as a Reel to Instagram Business Account via Graph API.
        """
        # Step 1: Upload to temp host
        temp_url = self.upload_to_temp_host(file_path)

        # Step 2: Create media container
        container_url = f"{self.base_url}/{self.api_version}/{ig_user_id}/media"
        params = {
            "media_type": "REELS",
            "video_url": temp_url,
            "caption": caption,
            "access_token": access_token
        }

        print(f"[IGUploader] 🔗 Requesting Instagram media container creation for Reel...")
        response = requests.post(container_url, data=params, timeout=30)
        
        if response.status_code != 200:
            raise RuntimeError(f"Failed to create IG Reels container: {response.text}")
            
        creation_id = response.json().get("id")
        print(f"[IGUploader] 🔄 Container created! ID: {creation_id}. Waiting for processing...")

        # Step 3: Poll status
        status_url = f"{self.base_url}/{self.api_version}/{creation_id}"
        status_params = {
            "fields": "status_code,status",
            "access_token": access_token
        }

        max_polls = 18  # 18 * 10 seconds = 3 minutes
        for attempt in range(1, max_polls + 1):
            time.sleep(10)
            try:
                status_res = requests.get(status_url, params=status_params, timeout=20)
                if status_res.status_code == 200:
                    status_data = status_res.json()
                    status_code = status_data.get("status_code")
                    status_text = status_data.get("status")
                    
                    print(f"[IGUploader] 🕒 Poll {attempt}/{max_polls}: Status = {status_code} ({status_text})")
                    
                    if status_code == "FINISHED":
                        print(f"[IGUploader] ✅ Processing completed successfully!")
                        break
                    elif status_code == "ERROR":
                        raise RuntimeError(f"Instagram video processing failed: {status_text}")
                else:
                    print(f"[IGUploader] ⚠️ Failed to fetch status. Status: {status_res.status_code}")
            except Exception as poll_err:
                print(f"[IGUploader] ⚠️ Error during status poll: {poll_err}")
                
            if attempt == max_polls:
                raise TimeoutError("Instagram Reel processing timed out on Facebook's servers.")

        # Step 4: Publish Reel
        publish_url = f"{self.base_url}/{self.api_version}/{ig_user_id}/media_publish"
        publish_params = {
            "creation_id": creation_id,
            "access_token": access_token
        }

        print(f"[IGUploader] 🚀 Publishing Reel to Instagram feed...")
        pub_response = requests.post(publish_url, data=publish_params, timeout=30)
        
        if pub_response.status_code == 200:
            ig_media_id = pub_response.json().get("id")
            print(f"[IGUploader] ✅ Success! Reel published! Instagram Media ID: {ig_media_id}")
            return ig_media_id
        else:
            raise RuntimeError(f"Failed to publish IG Reel: {pub_response.text}")
