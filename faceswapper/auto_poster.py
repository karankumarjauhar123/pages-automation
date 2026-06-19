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

def is_recent_post(history, influencer_name, window_minutes=45):
    """Checks if a post was made for this influencer in the last window_minutes."""
    now = datetime.datetime.utcnow()
    for entry in history:
        if entry.get("influencer_image", "").lower().startswith(influencer_name.lower()):
            posted_at_str = entry.get("timestamp")
            if posted_at_str:
                try:
                    clean_ts = posted_at_str.replace("Z", "")
                    if "." in clean_ts:
                        clean_ts = clean_ts.split(".")[0]
                    posted_at = datetime.datetime.strptime(clean_ts, "%Y-%m-%dT%H:%M:%S")
                    if (now - posted_at).total_seconds() < (window_minutes * 60):
                        return True
                except Exception:
                    pass
    return False

def find_queue_video(queue, influencer_name):
    """
    Finds the first video in the queue suitable for the influencer.
    Supports either string URLs or object formats.
    """
    for index, item in enumerate(queue):
        if isinstance(item, str):
            return index, item
        elif isinstance(item, dict):
            target = item.get("influencer", "all").lower()
            if target == "all" or target == influencer_name.lower() or target.startswith(influencer_name.lower()):
                return index, item.get("url")
    return None, None

def run_auto_poster(dry_run=False, force=False):
    print(f"[AutoPoster] 🚀 Starting Auto Poster at {datetime.datetime.now().isoformat()}")
    
    # Load configs and state
    influencers = load_json_file(INFLUENCERS_FILE, [])
    queue = load_json_file(QUEUE_FILE, [])
    history = load_json_file(HISTORY_FILE, [])
    
    if not influencers:
        print("[AutoPoster] ❌ No influencers configured in influencers.json. Exiting.")
        return
        
    utc_hour = get_utc_hour()
    print(f"[AutoPoster] Current UTC Hour: {utc_hour}")
    
    # Filter active influencers scheduled for this hour
    active_influencers = []
    for inf in influencers:
        name = inf["name"]
        schedule = inf.get("schedule", [])
        
        if force:
            active_influencers.append(inf)
            continue
            
        # Check scheduling
        max_posts = inf.get("max_posts_per_day", 3)
        today_str = datetime.datetime.utcnow().strftime("%Y-%m-%d")
        
        # Count posts made today
        posts_today = 0
        for entry in history:
            img = entry.get("influencer_image", "")
            if img.lower().startswith(name.lower()) or inf.get("face_image", "").lower() == img.lower():
                ts = entry.get("timestamp", "")
                if ts.startswith(today_str):
                    posts_today += 1
                    
        target_posts = len([h for h in schedule if h <= utc_hour])
        target_posts = min(target_posts, max_posts)
        
        if posts_today >= target_posts:
            print(f"[AutoPoster] Influencer '{name}' has posted {posts_today} times today, target is {target_posts} posts by hour {utc_hour} UTC. Skipping.")
            continue
            
        # Rate limit check (min 45 mins between posts)
        if is_recent_post(history, name, window_minutes=45):
            print(f"[AutoPoster] Influencer '{name}' has posted too recently (within 45 mins). Skipping.")
            continue
            
        active_influencers.append(inf)

    if not active_influencers:
        print("[AutoPoster] No influencers scheduled for this hour.")
        return

    print(f"[AutoPoster] Active influencers to process: {[inf['name'] for inf in active_influencers]}")
    
    # Initialize uploaders
    fb_uploader = FBUploader()
    ig_uploader = IGUploader()
    
    changes_made = False
    
    for inf in active_influencers:
        name = inf["name"]
        face_img = inf["face_image"]
        print(f"\n[AutoPoster] ────────── Processing Influencer: {name} ──────────")
        
        # Find next video in queue
        q_idx, video_url = find_queue_video(queue, name)
        if video_url is None:
            print(f"[AutoPoster] ⚠️ No video in queue for {name}. Queue size is {len(queue)}.")
            continue
            
        print(f"[AutoPoster] Found video to post: {video_url}")
        
        # Prepare caption
        hashtags = inf.get("hashtags", "#dance #reels #viral #trending")
        caption = f"Dance performance! 💃🔥\n\n{hashtags}"
        title = f"Dance Reel - {name}"
        
        try:
            # 1. Run face swap locally
            # We wrap it in a list as run_face_swap_pipeline expects a list of URLs
            if dry_run:
                print(f"[AutoPoster] 🧪 [DRY RUN] Would swap face using influencer photo: {face_img}")
                print(f"[AutoPoster] 🧪 [DRY RUN] Caption: \n{caption}\n")
                # Remove from queue for dry run testing to verify queue behavior
                queue.pop(q_idx)
                changes_made = True
                continue
                
            print(f"[AutoPoster] 🤖 Running Face Swapper pipeline...")
            swapped_results = run_face_swap_pipeline(
                urls=[video_url],
                influencer_filename=face_img,
                enhance=True,
                force=True # Force swap since we already checked history and scheduler
            )
            
            if not swapped_results:
                raise RuntimeError("Face Swapper pipeline failed to produce swapped video output.")
                
            swapped_video_path = swapped_results[0]["output_file"]
            print(f"[AutoPoster] ✅ Face swap complete. Output: {swapped_video_path}")
            
            fb_video_id = None
            ig_media_id = None
            
            # 2. Upload to Facebook Page
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
                
            # 3. Upload to Instagram
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

            # If at least one upload succeeded (or we attempted uploads)
            if fb_video_id or ig_media_id:
                print(f"[AutoPoster] 🎉 Reel posted successfully! FB ID: {fb_video_id}, IG ID: {ig_media_id}")
                
                # Remove from queue
                queue.pop(q_idx)
                changes_made = True
                
                # Update history log entry with upload IDs
                history = load_json_file(HISTORY_FILE, [])
                for entry in reversed(history):
                    if entry.get("url") == video_url and entry.get("influencer_image") == face_img:
                        entry["fb_video_id"] = fb_video_id
                        entry["ig_media_id"] = ig_media_id
                        break
                save_json_file(HISTORY_FILE, history)
            else:
                raise RuntimeError("Failed to publish video on both Facebook and Instagram.")
                
        except Exception as e:
            print(f"[AutoPoster] ❌ Error processing post for {name}: {e}")
            
    if changes_made:
        save_json_file(QUEUE_FILE, queue)
        print("[AutoPoster] Queue updated and saved.")
        
    print("[AutoPoster] 🏁 Auto Poster cycle finished.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Auto Poster Face Swapped Reels Suite")
    parser.add_argument("--dry-run", action="store_true", help="Run the flow but skip actual swaps and uploads")
    parser.add_argument("--force", action="store_true", help="Force run ignoring schedule and limits")
    args = parser.parse_args()
    
    run_auto_poster(dry_run=args.dry_run, force=args.force)
