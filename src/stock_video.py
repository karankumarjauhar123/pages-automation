import os
import requests

class StockVideoGenerator:
    def __init__(self, api_key=None):
        """
        Initialize Pexels Stock Video Generator.
        """
        self.api_key = api_key or os.getenv("PEXELS_API_KEY")
        if not self.api_key:
            print("Pexels: No API key provided. Stock video functionality will be disabled (falling back to AI images).")

    def search_and_download_video(self, query, output_path):
        """
        Searches Pexels for a portrait video clip based on the query,
        downloads the best MP4 file, and saves it to output_path.
        Returns True if successful, None if it fails.
        """
        if not self.api_key:
            return None

        headers = {
            "Authorization": self.api_key
        }
        url = "https://api.pexels.com/v1/videos/search"
        params = {
            "query": query,
            "orientation": "portrait",
            "per_page": 5
        }

        print(f"Pexels: Searching for stock video with query: '{query}'...")
        try:
            r = requests.get(url, headers=headers, params=params, timeout=15)
            if r.status_code != 200:
                print(f"Pexels: API returned status code {r.status_code}. Response: {r.text[:200]}")
                return None
            
            data = r.json()
            videos = data.get("videos", [])
            if not videos:
                print(f"Pexels: No videos found for query: '{query}'.")
                return None

            # Choose the first video (best match)
            video = videos[0]
            video_files = video.get("video_files", [])
            
            # Find the best MP4 download link
            download_url = None
            
            # 1. Look for HD quality MP4
            for vf in video_files:
                if vf.get("file_type") == "video/mp4" and vf.get("quality") == "hd":
                    download_url = vf.get("link")
                    break
                    
            # 2. Look for SD quality MP4 if no HD
            if not download_url:
                for vf in video_files:
                    if vf.get("file_type") == "video/mp4" and vf.get("quality") == "sd":
                        download_url = vf.get("link")
                        break
                        
            # 3. Fallback to any MP4
            if not download_url:
                for vf in video_files:
                    if vf.get("file_type") == "video/mp4":
                        download_url = vf.get("link")
                        break

            if not download_url:
                print(f"Pexels: No valid MP4 download links found in video files.")
                return None

            print(f"Pexels: Downloading video (duration: {video.get('duration')}s) from: {download_url[:60]}...")
            
            # Stream the download
            res = requests.get(download_url, stream=True, timeout=30)
            if res.status_code != 200:
                print(f"Pexels: Failed to download video. Status: {res.status_code}")
                return None

            with open(output_path, "wb") as f:
                for chunk in res.iter_content(chunk_size=1024 * 1024):  # 1MB chunks
                    if chunk:
                        f.write(chunk)
                        
            print(f"Pexels: Stock video downloaded successfully: {output_path}")
            return True

        except Exception as e:
            print(f"Pexels: Error during search/download: {e}")
            return None
