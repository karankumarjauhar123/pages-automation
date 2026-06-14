import os
import sys
import json
import datetime
import argparse
from dotenv import load_dotenv

# Ensure the root directory is in the path so we can import helper modules if needed
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from reposter.downloader import Downloader
from reposter.editor import Editor
from reposter.ai_helper import AIHelper
from reposter.uploader import Uploader

load_dotenv()

HISTORY_FILE = "reposter/history.json"
PENDING_FILE = "reposter/pending_reposts.json"
CONFIG_FILE = "reposter/repost_pages.json"

def load_json_file(file_path, default_val):
    if os.path.exists(file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"[Main] Error loading {file_path}: {e}")
            return default_val
    return default_val

def save_json_file(file_path, data):
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"[Main] Error saving {file_path}: {e}")

def get_utc_hour():
    return datetime.datetime.utcnow().hour

def is_recent_post(history, page_name, window_minutes=45):
    """Checks if a post was made for this page in the last window_minutes."""
    now = datetime.datetime.utcnow()
    for entry in history:
        if entry.get("page_name", "").lower() == page_name.lower():
            posted_at_str = entry.get("posted_at")
            if posted_at_str:
                try:
                    posted_at = datetime.datetime.strptime(posted_at_str, "%Y-%m-%dT%H:%M:%SZ")
                    if (now - posted_at).total_seconds() < (window_minutes * 60):
                        return True
                except Exception:
                    pass
    return False

def clean_temp_files(*paths):
    for path in paths:
        if path and os.path.exists(path):
            try:
                os.remove(path)
                print(f"[Main] Cleaned up temporary file: {path}")
            except Exception as e:
                print(f"[Main] Warning: Could not remove {path}: {e}")

def process_pending_uploads(downloader, editor, uploader, history):
    """Tries to upload any failed posts from the retry queue by downloading and re-editing."""
    pending = load_json_file(PENDING_FILE, [])
    if not pending:
        return history

    still_pending = []
    print(f"[Main] 🔄 Found {len(pending)} pending failed uploads in the queue. Processing...")

    for item in pending:
        page_name = item["page_name"]
        page_id = item["page_id"]
        token_env = item["access_token_env"]
        token = os.getenv(token_env)
        original_url = item["original_url"]
        title = item["title"]
        caption = item["caption"]
        hook = item["hook"]
        cta = item["cta"]
        style = item["edit_style"]
        
        if not token:
            print(f"[Main] ❌ Skipping retry for {page_name}: Env var {token_env} not set.")
            still_pending.append(item)
            continue
            
        print(f"[Main] 🔄 Retrying post for {page_name}: '{title}'...")
        
        # Paths for retry run
        safe_name = "".join([c if c.isalnum() else "_" for c in page_name])
        dl_path = f"reposter/download_{safe_name}_retry.mp4"
        overlay_path = f"reposter/overlay_{safe_name}_retry.png"
        out_path = f"reposter/repost_{safe_name}_retry.mp4"

        try:
            # 1. Download original video again
            downloaded_file = downloader.download_video(original_url, output_path=dl_path)
            if not downloaded_file:
                raise RuntimeError("Download failed during retry")

            # 2. Draw overlay
            editor.create_overlay_image(
                hook_text=hook,
                cta_text=cta,
                watermark=style["watermark"],
                watermark_opacity=style["watermark_opacity"],
                bg_color_rgb=style["banner_bg_color"],
                text_color_rgb=style["banner_text_color"],
                font_name=style["banner_font"],
                output_path=overlay_path
            )

            # 3. Transform video
            final_video = editor.transform_video(
                input_video=downloaded_file,
                overlay_image=overlay_path,
                edit_style=style,
                output_video=out_path
            )

            # 4. Upload
            fb_id = uploader.upload_reel(
                page_id=page_id,
                access_token=token,
                file_path=final_video,
                title=title,
                caption=caption
            )
            
            if fb_id:
                print(f"[Main] ✅ Pending retry successful for {page_name}!")
                # Add to history
                history.append({
                    "video_id": item.get("original_video_id"),
                    "url": original_url,
                    "title": title,
                    "posted_at": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "page_name": page_name,
                    "fb_video_id": fb_id,
                    "caption": caption
                })
                # Clean up all files
                clean_temp_files(downloaded_file, overlay_path, final_video)
            else:
                raise RuntimeError("Upload returned empty response")
        except Exception as e:
            print(f"[Main] ⚠️ Retry failed for {page_name}: {e}")
            # Clean up intermediate files
            clean_temp_files(dl_path, overlay_path, out_path)
            
            retries_left = item.get("retries_left", 3) - 1
            if retries_left > 0:
                item["retries_left"] = retries_left
                item["error"] = str(e)
                still_pending.append(item)
            else:
                print(f"[Main] ❌ Retry limit reached for pending post on {page_name}. Discarding.")

    save_json_file(PENDING_FILE, still_pending)
    return history

def run_page_flow(page_config, downloader, editor, ai_helper, uploader, history, dry_run=False):
    page_name = page_config["page_name"]
    page_id = page_config["page_id"]
    token_env = page_config["access_token_env"]
    language = page_config["language"]
    topic = page_config.get("topic", "")
    sources = page_config["sources"]
    style = page_config["edit_style"]

    print(f"\n==========================================")
    print(f"🎬 Processing Page: {page_name.upper()}")
    print(f"==========================================")

    # 1. Scraping and Virality Scoring
    best_video = downloader.find_best_viral_video(sources)
    if not best_video:
        print(f"[Main] ❌ No suitable viral video found for {page_name}.")
        return history

    # Setup specific file paths to prevent overlap
    safe_name = "".join([c if c.isalnum() else "_" for c in page_name])
    dl_path = f"reposter/download_{safe_name}.mp4"
    overlay_path = f"reposter/overlay_{safe_name}.png"
    out_path = f"reposter/repost_{safe_name}.mp4"

    # 2. Download original video
    downloaded_file = downloader.download_video(best_video["url"], output_path=dl_path)
    if not downloaded_file:
        print(f"[Main] ❌ Download failed. Skipping page {page_name}.")
        return history

    # 3. Generate AI assets (caption, hook, CTA)
    print(f"[Main] Generating AI caption and banners...")
    ai_meta = ai_helper.generate_repost_metadata(
        original_title=best_video["title"],
        page_name=page_name,
        language=language,
        topic=topic,
        original_description=best_video["description"]
    )
    print(f"[Main] Hook text: '{ai_meta['banner_hook']}'")
    print(f"[Main] CTA text:  '{ai_meta['banner_cta']}'")

    # 4. Draw Overlay Image
    print(f"[Main] Drawing overlay image...")
    editor.create_overlay_image(
        hook_text=ai_meta["banner_hook"],
        cta_text=ai_meta["banner_cta"],
        watermark=style["watermark"],
        watermark_opacity=style["watermark_opacity"],
        bg_color_rgb=style["banner_bg_color"],
        text_color_rgb=style["banner_text_color"],
        font_name=style["banner_font"],
        output_path=overlay_path
    )

    # 5. Transform Video (Anti-detection changes)
    print(f"[Main] Applying video transformation filters...")
    try:
        final_video = editor.transform_video(
            input_video=downloaded_file,
            overlay_image=overlay_path,
            edit_style=style,
            output_video=out_path
        )
    except Exception as e:
        print(f"[Main] ❌ Video processing failed: {e}")
        clean_temp_files(downloaded_file, overlay_path)
        return history

    # 6. Upload
    if dry_run:
        print(f"[Main] 🧪 Dry-run flag set. Skipping Facebook upload.")
        print(f"[Main] Caption: \n{ai_meta['fb_caption']}\n")
        history.append({
            "video_id": best_video["video_id"],
            "url": best_video["url"],
            "title": best_video["title"],
            "posted_at": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "page_name": page_name,
            "fb_video_id": "DRY_RUN",
            "caption": ai_meta["fb_caption"]
        })
        # Clean up files for dry-run
        clean_temp_files(downloaded_file, overlay_path, final_video)
    else:
        token = os.getenv(token_env)
        if not token:
            print(f"[Main] ❌ Access token environment variable '{token_env}' not set. Skipping upload.")
            clean_temp_files(downloaded_file, overlay_path, final_video)
            return history
            
        try:
            fb_id = uploader.upload_reel(
                page_id=page_id,
                access_token=token,
                file_path=final_video,
                title=best_video["title"],
                caption=ai_meta["fb_caption"]
            )
            if fb_id:
                history.append({
                    "video_id": best_video["video_id"],
                    "url": best_video["url"],
                    "title": best_video["title"],
                    "posted_at": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "page_name": page_name,
                    "fb_video_id": fb_id,
                    "caption": ai_meta["fb_caption"]
                })
                print(f"[Main] ✅ Post published successfully on page {page_name}!")
                # Clean up everything on success
                clean_temp_files(downloaded_file, overlay_path, final_video)
            else:
                raise RuntimeError("Empty response from uploader")
        except Exception as e:
            print(f"[Main] ❌ Facebook upload failed. Adding metadata to pending retry queue. Error: {e}")
            pending = load_json_file(PENDING_FILE, [])
            pending.append({
                "page_name": page_name,
                "page_id": page_id,
                "access_token_env": token_env,
                "original_url": best_video["url"],
                "title": best_video["title"],
                "caption": ai_meta["fb_caption"],
                "hook": ai_meta["banner_hook"],
                "cta": ai_meta["banner_cta"],
                "edit_style": style,
                "original_video_id": best_video["video_id"],
                "error": str(e),
                "retries_left": 3
            })
            save_json_file(PENDING_FILE, pending)
            # Clean up all local files to prevent disk bloating
            clean_temp_files(downloaded_file, overlay_path, final_video)

    return history

def main():
    parser = argparse.ArgumentParser(description="Advanced Viral Reels Reposter Suite")
    parser.add_argument("--page", type=str, help="Specific page name to process (ignores schedule)")
    parser.add_argument("--force", action="store_true", help="Force processing regardless of schedule")
    parser.add_argument("--dry-run", action="store_true", help="Dry run flow (no upload)")
    args = parser.parse_args()

    print(f"[Main] 🚀 Starting Reposter Suite at {datetime.datetime.now().isoformat()}")

    # Initialize sub-systems
    downloader = Downloader(HISTORY_FILE)
    editor = Editor()
    ai_helper = AIHelper()
    uploader = Uploader()

    # Load history & configs
    history = load_json_file(HISTORY_FILE, [])
    pages = load_json_file(CONFIG_FILE, [])

    # First, attempt to flush any pending retries if we are not in dry-run
    if not args.dry_run:
        history = process_pending_uploads(downloader, editor, uploader, history)
        save_json_file(HISTORY_FILE, history)

    utc_hour = get_utc_hour()
    print(f"[Main] Current UTC Hour: {utc_hour}")

    pages_to_run = []
    for p in pages:
        p_name = p["page_name"]
        
        # If --page specified, run only that page
        if args.page and args.page.lower() != p_name.lower():
            continue
            
        # Check scheduling
        if not args.page and not args.force:
            if utc_hour not in p.get("schedule", []):
                print(f"[Main] Page '{p_name}' is not scheduled for UTC hour {utc_hour}. Skipping.")
                continue
                
            # Rate limiting check
            if is_recent_post(history, p_name, window_minutes=45):
                print(f"[Main] Page '{p_name}' was posted to recently in the last 45 mins. Rate limiting check failed. Skipping.")
                continue

        pages_to_run.append(p)

    if not pages_to_run:
        print("[Main] No pages to run in this cycle.")
        return

    print(f"[Main] Will process {len(pages_to_run)} pages: {[p['page_name'] for p in pages_to_run]}")

    for p in pages_to_run:
        history = run_page_flow(p, downloader, editor, ai_helper, uploader, history, dry_run=args.dry_run)
        save_json_file(HISTORY_FILE, history)

    print(f"[Main] 🎉 Reposter Cycle Completed.")

if __name__ == "__main__":
    main()
