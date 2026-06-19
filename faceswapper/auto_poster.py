import os
import sys
import json
import datetime
import argparse
from dotenv import load_dotenv

# Ensure root directory is in the path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from faceswapper.run_faceswap import run_face_swap_pipeline
from faceswapper.ig_uploader import IGUploader
from src.fb_uploader import FBUploader

load_dotenv()

INFLUENCERS_FILE = "faceswapper/influencers.json"
QUEUE_FILE = "faceswapper/video_queue.json"
HISTORY_FILE = "faceswapper/history.json"

def load_json_file(file_path, default_val):
    if os.path.exists(file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"[AutoPoster] Error loading {file_path}: {e}")
            return default_val
    return default_val

def save_json_file(file_path, data):
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"[AutoPoster] Error saving {file_path}: {e}")

def get_utc_hour():
    return datetime.datetime.utcnow().hour

def run_auto_poster(dry_run=False, force=False):
    print(f"[AutoPoster] 🚀 Starting Auto Poster at {datetime.datetime.now().isoformat()}")
    
    # Load configs and state
    influencers = load_json_file(INFLUENCERS_FILE, [])
    queue = load_json_file(QUEUE_FILE, [])
    history = load_json_file(HISTORY_FILE, [])
    
    if not influencers:
        print("[AutoPoster] ❌ No influencers configured in influencers.json. Exiting.")
        return
        
    if not queue:
        print("[AutoPoster] ❌ Video queue is empty. Please add video URLs to faceswapper/video_queue.json. Exiting.")
        return

    # Check scheduling
    utc_hour = get_utc_hour()
    print(f"[AutoPoster] Current UTC Hour: {utc_hour}")
    
    # If not forced, check if this hour is in any influencer's schedule
    is_scheduled_hour = False
    for inf in influencers:
        if utc_hour in inf.get("schedule", []):
            is_scheduled_hour = True
            break
            
    if not is_scheduled_hour and not force:
        print(f"[AutoPoster] UTC Hour {utc_hour} is not in any influencer's posting schedule. Skipping.")
        return
        
    # Get the first video URL from the queue
    video_item = queue[0]
    video_url = ""
    if isinstance(video_item, str):
        video_url = video_item.strip()
    elif isinstance(video_item, dict):
        video_url = video_item.get("url", "").strip()
        
    if not video_url:
        print("[AutoPoster] ❌ Invalid video item in queue. Removing it and stopping.")
        queue.pop(0)
        save_json_file(QUEUE_FILE, queue)
        return
        
    print(f"[AutoPoster] 🎬 Selected video for this cycle: {video_url}")
    
    # Initialize uploaders
    fb_uploader = FBUploader()
    ig_uploader = IGUploader()
    
    # Process for all influencers
    for inf in influencers:
        name = inf["name"]
        face_img = inf["face_image"]
        print(f"\n[AutoPoster] ────────── Processing Influencer: {name} ──────────")
        
        # Prepare caption
        hashtags = inf.get("hashtags", "#dance #reels #viral #trending")
        caption = f"Dance performance! 💃🔥\n\n{hashtags}"
        title = f"Dance Reel - {name}"
        
        # Check if AI is enabled for this profile and API keys are set
        ai_enabled = inf.get("ai_caption_enabled", False)
        has_api_keys = os.getenv("OPENROUTER_API_KEY") or os.getenv("NVIDIA_API_KEY")
        
        if ai_enabled and has_api_keys:
            try:
                print(f"[AutoPoster] 🤖 Generating AI caption ({inf.get('ai_caption_vibe', 'energetic')} vibe, {inf.get('ai_caption_language', 'Hinglish')} language)...")
                from reposter.ai_helper import AIHelper
                ai = AIHelper()
                ai_caption = ai.generate_faceswap_caption(
                    influencer_name=name,
                    vibe=inf.get("ai_caption_vibe", "energetic"),
                    language=inf.get("ai_caption_language", "Hinglish"),
                    hashtags=hashtags
                )
                if ai_caption:
                    caption = ai_caption
                    print(f"[AutoPoster] AI Caption generated: {caption}")
            except Exception as ai_err:
                print(f"[AutoPoster] ⚠️ Failed to generate AI caption, falling back to default: {ai_err}")
        
        try:
            if dry_run:
                print(f"[AutoPoster] 🧪 [DRY RUN] Would swap face using influencer photo: {face_img}")
                print(f"[AutoPoster] 🧪 [DRY RUN] Caption: \n{caption}\n")
                continue
                
            print(f"[AutoPoster] 🤖 Running Face Swapper pipeline...")
            swapped_results = run_face_swap_pipeline(
                urls=[video_url],
                influencer_filename=face_img,
                enhance=True,
                force=True # Force swap since we are managing the queue ourselves
            )
            
            if not swapped_results:
                raise RuntimeError("Face Swapper pipeline failed to produce swapped video output.")
                
            swapped_video_path = swapped_results[0]["output_file"]
            print(f"[AutoPoster] ✅ Face swap complete. Output: {swapped_video_path}")
            
            fb_video_id = None
            ig_media_id = None
            
            # 1. Upload to Facebook Page
            fb_page_id = inf.get("facebook_page_id")
            fb_token_env = inf.get("fb_access_token_env")
            fb_token = os.getenv(fb_token_env) if fb_token_env else None
            
            if fb_page_id and fb_token:
                try:
                    print(f"[AutoPoster] 📘 Uploading to Facebook Page {fb_page_id}...")
                    fb_video_id = fb_uploader.upload_video(
                        page_id=fb_page_id,
                        access_token=fb_token,
                        file_path=swapped_video_path,
                        title=title,
                        caption=caption
                    )
                except Exception as fb_err:
                    print(f"[AutoPoster] ❌ Facebook upload failed: {fb_err}")
            else:
                print(f"[AutoPoster] ⚠️ Facebook config missing or token env var not set. Skipping Facebook upload.")
                
            # 2. Upload to Instagram
            ig_user_id = inf.get("instagram_business_id")
            ig_token_env = inf.get("ig_access_token_env")
            ig_token = os.getenv(ig_token_env) if ig_token_env else None
            
            if ig_user_id and ig_token and ig_user_id != "YOUR_INSTAGRAM_BUSINESS_ACCOUNT_ID":
                try:
                    print(f"[AutoPoster] 📸 Uploading to Instagram Account {ig_user_id}...")
                    ig_media_id = ig_uploader.upload_instagram_reel(
                        ig_user_id=ig_user_id,
                        access_token=ig_token,
                        file_path=swapped_video_path,
                        caption=caption
                    )
                except Exception as ig_err:
                    print(f"[AutoPoster] ❌ Instagram upload failed: {ig_err}")
            else:
                print(f"[AutoPoster] ⚠️ Instagram config missing, token env var not set, or using default placeholder. Skipping Instagram upload.")

            # If at least one upload succeeded
            if fb_video_id or ig_media_id:
                print(f"[AutoPoster] 🎉 Reel posted successfully for {name}! FB ID: {fb_video_id}, IG ID: {ig_media_id}")
                
                # Update history log entry with upload IDs
                history = load_json_file(HISTORY_FILE, [])
                for entry in reversed(history):
                    if entry.get("url") == video_url and entry.get("influencer_image") == face_img:
                        entry["fb_video_id"] = fb_video_id
                        entry["ig_media_id"] = ig_media_id
                        break
                save_json_file(HISTORY_FILE, history)
            else:
                print(f"[AutoPoster] ❌ Failed to publish video for {name} on both platforms.")
                
        except Exception as e:
            print(f"[AutoPoster] ❌ Error processing post for {name}: {e}")

    # Remove the video from the queue after processing for all influencers
    print(f"[AutoPoster] 🏁 Finished processing cycle for video: {video_url}")
    queue.pop(0)
    save_json_file(QUEUE_FILE, queue)
    print(f"[AutoPoster] Video removed from queue. Remaining queue size: {len(queue)}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Auto Poster Face Swapped Reels Suite")
    parser.add_argument("--dry-run", action="store_true", help="Run the flow but skip actual swaps and uploads")
    parser.add_argument("--force", action="store_true", help="Force run ignoring schedule and limits")
    args = parser.parse_args()
    
    run_auto_poster(dry_run=args.dry_run, force=args.force)
