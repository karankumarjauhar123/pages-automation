import os
import sys
import json
import datetime
import subprocess
import argparse
import shutil
import requests
import yt_dlp
import replicate

# Add root folder to python path to align with codebase structure
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Paths configuration
HISTORY_FILE = "faceswapper/history.json"
INFLUENCER_DIR = "influencer_faces"
OUTPUT_DIR = "swapped_reels"

# Ensure folders exist
os.makedirs(INFLUENCER_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

# ─────────────────────────────────────────────────────────────
#  TEMP UPLOADERS WITH RESILIENT FALLBACKS
# ─────────────────────────────────────────────────────────────

def upload_tmpfiles(file_path):
    """Uploads file to tmpfiles.org and returns direct download link."""
    url = "https://tmpfiles.org/api/v1/upload"
    with open(file_path, "rb") as f:
        r = requests.post(url, files={"file": f}, timeout=120)
    if r.status_code == 200:
        data = r.json()
        if data.get("status") == "success":
            view_url = data["data"]["url"]
            # Convert view URL to direct download URL
            if "tmpfiles.org/" in view_url:
                direct_url = view_url.replace("tmpfiles.org/", "tmpfiles.org/dl/")
                return direct_url
    return None

def upload_catbox(file_path):
    """Uploads file to catbox.moe and returns direct URL."""
    url = "https://catbox.moe/user/api.php"
    with open(file_path, "rb") as f:
        r = requests.post(
            url, 
            data={"reqtype": "fileupload"}, 
            files={"fileToUpload": f}, 
            timeout=120
        )
    if r.status_code == 200:
        res_text = r.text.strip()
        if res_text.startswith("https://"):
            return res_text
    return None

def upload_transfer_sh(file_path):
    """Uploads file to transfer.sh and returns direct URL."""
    filename = os.path.basename(file_path)
    url = f"https://transfer.sh/{filename}"
    with open(file_path, "rb") as f:
        r = requests.put(url, data=f, timeout=120)
    if r.status_code == 200:
        return r.text.strip()
    return None

def upload_file(file_path):
    """Tries multiple uploaders sequentially to upload file to temp storage."""
    print(f"[FaceSwapper] 📤 Uploading {os.path.basename(file_path)} to temporary hosting...")
    
    # Try tmpfiles.org
    try:
        url = upload_tmpfiles(file_path)
        if url:
            print(f"[FaceSwapper] ✅ Uploaded to tmpfiles.org: {url}")
            return url
    except Exception as e:
        print(f"[FaceSwapper] ⚠️ tmpfiles.org upload failed: {e}")
        
    # Try catbox.moe
    try:
        url = upload_catbox(file_path)
        if url:
            print(f"[FaceSwapper] ✅ Uploaded to catbox.moe: {url}")
            return url
    except Exception as e:
        print(f"[FaceSwapper] ⚠️ catbox.moe upload failed: {e}")
        
    # Try transfer.sh
    try:
        url = upload_transfer_sh(file_path)
        if url:
            print(f"[FaceSwapper] ✅ Uploaded to transfer.sh: {url}")
            return url
    except Exception as e:
        print(f"[FaceSwapper] ⚠️ transfer.sh upload failed: {e}")
        
    raise Exception("All temporary file hosting uploads failed.")

# ─────────────────────────────────────────────────────────────
#  DOWNLOAD AND AUDIO PROCESSING
# ─────────────────────────────────────────────────────────────

def download_video(url, output_path):
    """Downloads target video using yt-dlp."""
    print(f"[FaceSwapper] 📥 Downloading Reel: {url}...")
    if os.path.exists(output_path):
        try:
            os.remove(output_path)
        except Exception:
            pass

    ydl_opts = {
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
        'outtmpl': output_path,
        'quiet': True,
        'no_warnings': True,
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        if os.path.exists(output_path):
            print(f"[FaceSwapper] ✅ Downloaded successfully to {output_path}")
            return True
    except Exception as e:
        print(f"[FaceSwapper] ❌ yt-dlp failed to download {url}: {e}")
    return False

def merge_audio(original_video_path, swapped_video_path, output_path):
    """Merges the original video's audio track back into the face-swapped video."""
    print(f"[FaceSwapper] 🎵 Merging original audio with face-swapped video...")
    
    cmd = [
        "ffmpeg", "-y",
        "-i", swapped_video_path,
        "-i", original_video_path,
        "-c:v", "copy",
        "-c:a", "aac",
        "-map", "0:v:0",
        "-map", "1:a:0?",
        "-shortest",
        output_path
    ]
    
    try:
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if result.returncode == 0 and os.path.exists(output_path):
            print(f"[FaceSwapper] ✅ Audio merged successfully. Output saved to {output_path}")
            return True
        else:
            print(f"[FaceSwapper] ⚠️ FFmpeg merging failed, error: {result.stderr}")
            shutil.copy(swapped_video_path, output_path)
            return False
    except Exception as e:
        print(f"[FaceSwapper] ❌ Error running FFmpeg: {e}. Saving video without merging audio.")
        shutil.copy(swapped_video_path, output_path)
        return False

# ─────────────────────────────────────────────────────────────
#  HISTORY AND FILE UTILS
# ─────────────────────────────────────────────────────────────

def load_history():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"[FaceSwapper] Error loading history: {e}")
    return []

def save_history(history):
    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"[FaceSwapper] Error saving history: {e}")

def is_already_processed(history, url, influencer):
    for entry in history:
        if entry.get("url") == url and entry.get("influencer_image") == influencer:
            return True
    return False

def clean_filename(url, influencer):
    # Extract unique part of URL to make output name clean
    parts = [p for p in url.split("/") if p]
    unique_id = parts[-1] if parts else "video"
    # Filter special characters
    unique_id = "".join([c if c.isalnum() else "_" for c in unique_id])
    face_name = os.path.splitext(influencer)[0]
    face_name = "".join([c if c.isalnum() else "_" for c in face_name])
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"swapped_{unique_id}_with_{face_name}_{timestamp}.mp4"

def cleanup_files(*paths):
    for path in paths:
        if path and os.path.exists(path):
            try:
                os.remove(path)
                print(f"[FaceSwapper] 🧹 Cleaned up temporary file: {path}")
            except Exception as e:
                print(f"[FaceSwapper] ⚠️ Could not remove temporary file {path}: {e}")

# ─────────────────────────────────────────────────────────────
#  MAIN CONTROLLER
# ─────────────────────────────────────────────────────────────

def run_face_swap_pipeline(urls, influencer_filename, enhance=True, force=False):
    # 1. Validate inputs
    replicate_token = os.getenv("REPLICATE_API_TOKEN")
    if not replicate_token:
        print("[FaceSwapper] ❌ Error: REPLICATE_API_TOKEN environment variable not set.")
        sys.exit(1)

    influencer_path = os.path.join(INFLUENCER_DIR, influencer_filename)
    if not os.path.exists(influencer_path):
        print(f"[FaceSwapper] ❌ Error: Influencer face photo not found at '{influencer_path}'")
        print("[FaceSwapper] Please make sure you upload the photo to the 'influencer_faces/' directory.")
        sys.exit(1)

    history = load_history()
    processed_count = 0
    failed_count = 0

    print(f"[FaceSwapper] 🚀 Starting Face Swapper Pipeline for {len(urls)} URLs...")
    print(f"[FaceSwapper] Influencer face: {influencer_filename}")
    print(f"[FaceSwapper] GFPGAN enhancement: {enhance}")

    # 2. Upload source face image (needed once for the run)
    try:
        source_image_url = upload_file(influencer_path)
    except Exception as e:
        print(f"[FaceSwapper] ❌ Failed to upload influencer face image: {e}")
        sys.exit(1)

    for index, url in enumerate(urls, 1):
        url = url.strip()
        if not url:
            continue

        print(f"\n[FaceSwapper] ────────── Processing Reel {index}/{len(urls)} ──────────")
        print(f"[FaceSwapper] URL: {url}")

        if not force and is_already_processed(history, url, influencer_filename):
            print(f"[FaceSwapper] ⏩ Skipping: Already processed and recorded in history.")
            continue

        # Paths for temporary local files
        local_target_path = f"faceswapper_target_temp_{index}.mp4"
        local_swapped_temp_path = f"faceswapper_swapped_temp_{index}.mp4"
        output_filename = clean_filename(url, influencer_filename)
        output_path = os.path.join(OUTPUT_DIR, output_filename)

        try:
            # 3. Download the target video
            if not download_video(url, local_target_path):
                print(f"[FaceSwapper] ❌ Skipping: Download failed for {url}")
                failed_count += 1
                continue

            # 4. Upload the downloaded video to temporary cloud hosting
            target_video_url = upload_file(local_target_path)

            # 5. Invoke Replicate API to swap face
            print(f"[FaceSwapper] 🤖 Triggering face swap model on Replicate GPU...")
            
            # Using stable model version string for ddvinh1/video-faceswap-gpu
            model_version = "ddvinh1/video-faceswap-gpu:50a0a0018673852629578e627576326036b407e0dbd8cf8a0b5028296726dc5c"
            
            output = replicate.run(
                model_version,
                input={
                    "source_image": source_image_url,
                    "target_video": target_video_url,
                    "enhance": enhance
                }
            )

            # Get output video URL
            output_url = None
            if isinstance(output, list):
                if len(output) > 0:
                    output_url = str(output[0])
            elif output:
                output_url = str(output)

            if not output_url:
                raise Exception("Replicate returned empty output or unexpected format.")

            print(f"[FaceSwapper] ✅ Replicate GPU processing complete. Swapped video URL: {output_url}")

            # 6. Download swapped video
            print(f"[FaceSwapper] 📥 Downloading swapped video from Replicate storage...")
            r = requests.get(output_url, stream=True, timeout=120)
            if r.status_code == 200:
                with open(local_swapped_temp_path, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        f.write(chunk)
            else:
                raise Exception(f"Failed to download output from Replicate. HTTP {r.status_code}")

            # 7. Merge original audio back into the swapped video
            merge_audio(local_target_path, local_swapped_temp_path, output_path)

            # 8. Record in history
            history.append({
                "url": url,
                "influencer_image": influencer_filename,
                "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
                "output_file": output_path
            })
            save_history(history)

            processed_count += 1
            print(f"[FaceSwapper] 🎉 Successfully finished processing Reel: {output_filename}")

        except Exception as e:
            print(f"[FaceSwapper] ❌ Face Swapper failed for {url}: {e}")
            failed_count += 1
        finally:
            # Clean up temp files
            cleanup_files(local_target_path, local_swapped_temp_path)

    print(f"\n[FaceSwapper] 🏁 Pipeline completed. Processed: {processed_count}, Failed: {failed_count}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="World-class Face Swapper Suite")
    parser.add_argument("--urls", type=str, help="Comma-separated list of Reels URLs or path to a text file containing URLs")
    parser.add_argument("--influencer", type=str, required=True, help="Filename of the influencer face image inside influencer_faces/")
    parser.add_argument("--enhance", action="store_true", default=True, help="Enable GFPGAN face enhancement (default: True)")
    parser.add_argument("--no-enhance", action="store_false", dest="enhance", help="Disable GFPGAN face enhancement")
    parser.add_argument("--force", action="store_true", help="Force swap even if the Reel has been processed before")

    args = parser.parse_args()

    # Determine url list
    urls_input = args.urls
    urls_list = []
    
    if urls_input:
        if os.path.exists(urls_input):
            # Read from file
            with open(urls_input, "r", encoding="utf-8") as f:
                urls_list = [line.strip() for line in f if line.strip()]
        else:
            # Comma-separated list
            urls_list = [u.strip() for u in urls_input.split(",") if u.strip()]
    else:
        # Fallback to environment variable if run from GitHub Actions and not passed via cmdline
        env_urls = os.getenv("FACE_SWAP_URLS")
        if env_urls:
            # Can be newline or comma separated
            if "\n" in env_urls:
                urls_list = [u.strip() for u in env_urls.split("\n") if u.strip()]
            else:
                urls_list = [u.strip() for u in env_urls.split(",") if u.strip()]

    if not urls_list:
        print("[FaceSwapper] ❌ Error: No Reels URLs provided. Use --urls or set the FACE_SWAP_URLS environment variable.")
        sys.exit(1)

    run_face_swap_pipeline(
        urls=urls_list,
        influencer_filename=args.influencer,
        enhance=args.enhance,
        force=args.force
    )
