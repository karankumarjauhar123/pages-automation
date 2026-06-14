import os
import json
import argparse
import shutil
import random
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont
from dotenv import load_dotenv

from src.script_generator import ScriptGenerator
from src.image_generator import ImageGenerator
from src.voice_generator import VoiceGenerator
from src.video_composer import VideoComposer
from src.fb_uploader import FBUploader
from src.stock_video import StockVideoGenerator

load_dotenv()

def parse_args():
    parser = argparse.ArgumentParser(description="AI Video & Image Automation for Facebook Pages")
    parser.add_argument("--dry-run", action="store_true", help="Generate posts locally but do not upload to Facebook")
    parser.add_argument("--count", type=int, default=1, help="Number of posts to generate per page")
    parser.add_argument("--page", type=str, default=None, help="Name of a specific page in pages.json to process")
    parser.add_argument("--type", type=str, choices=["video", "image"], default=None, help="Force a specific post type (video or image)")
    parser.add_argument("--force", action="store_true", help="Force execution regardless of scheduled hours")
    parser.add_argument("--retry-pending", action="store_true", help="Retry failed uploads saved in the pending queue")
    return parser.parse_args()

def load_pages():
    pages_path = "pages.json"
    if not os.path.exists(pages_path):
        raise FileNotFoundError(f"Configuration file {pages_path} not found.")
    with open(pages_path, "r") as f:
        return json.load(f)

def overlay_text_on_image(image_path, text, output_path, font_path=None):
    """
    Renders text centered on the image with a semi-transparent dark rounded card behind it.
    Makes quotes and facts look highly premium and legible.
    """
    print(f"Overlaying text on image: '{text[:50]}...'")
    img = Image.open(image_path)
    if img.mode != "RGB":
        img = img.convert("RGB")
        
    width, height = img.size
    draw = ImageDraw.Draw(img)
    
    # Try loading bold font
    font = None
    if font_path and os.path.exists(font_path):
        try:
            font = ImageFont.truetype(font_path, 42)
        except Exception:
            pass
    if not font:
        font = ImageFont.load_default()

    # Wrap text to fit about 75% of the image width
    max_w = width * 0.75
    words = text.split()
    lines = []
    current_line = []
    
    for word in words:
        current_line.append(word)
        test_line = " ".join(current_line)
        w = draw.textbbox((0, 0), test_line, font=font)[2]
        if w > max_w:
            if len(current_line) > 1:
                current_line.pop()
                lines.append(" ".join(current_line))
                current_line = [word]
            else:
                lines.append(test_line)
                current_line = []
                
    if current_line:
        lines.append(" ".join(current_line))

    # Calculate height details
    line_bbox = draw.textbbox((0, 0), "Ay", font=font)
    line_height = line_bbox[3] - line_bbox[1]
    line_spacing = 15
    padding = 30
    
    text_w = 0
    for line in lines:
        w = draw.textbbox((0, 0), line, font=font)[2]
        if w > text_w:
            text_w = w
            
    text_h = len(lines) * line_height + (len(lines) - 1) * line_spacing

    # Dimensions for the dark overlay card
    box_x0 = (width - text_w) / 2 - padding
    box_y0 = (height - text_h) / 2 - padding
    box_x1 = (width + text_w) / 2 + padding
    box_y1 = (height + text_h) / 2 + padding

    # Draw semi-transparent card (alpha composite)
    overlay = Image.new('RGBA', img.size, (0, 0, 0, 0))
    overlay_draw = ImageDraw.Draw(overlay)
    overlay_draw.rounded_rectangle([box_x0, box_y0, box_x1, box_y1], radius=25, fill=(0, 0, 0, 160))
    
    img = img.convert("RGBA")
    img = Image.alpha_composite(img, overlay)
    img = img.convert("RGB")
    
    # Draw text lines centered with outlines
    draw = ImageDraw.Draw(img)
    y = (height - text_h) / 2
    for line in lines:
        w = draw.textbbox((0, 0), line, font=font)[2]
        x = (width - w) / 2
        # Outline for crisp text
        for dx in [-2, -1, 0, 1, 2]:
            for dy in [-2, -1, 0, 1, 2]:
                if dx != 0 or dy != 0:
                    draw.text((x + dx, y + dy), line, font=font, fill=(0, 0, 0))
        draw.text((x, y), line, font=font, fill=(255, 255, 255))
        y += line_height + line_spacing

    img.save(output_path, "PNG")
    print(f"Successfully overlaid text and saved image to: {output_path}")

def clean_temp_dir(temp_dir):
    """
    Cleans up all temporary assets to save disk space.
    """
    if os.path.exists(temp_dir):
        shutil.rmtree(temp_dir)
    os.makedirs(temp_dir, exist_ok=True)

def log_post_to_history(page_name, page_id, post_type, fb_id, title, caption, topic):
    """
    Logs successful uploads to a public docs/history.json file.
    This file is displayed in the GitHub Pages control panel UI.
    """
    history_dir = "docs"
    os.makedirs(history_dir, exist_ok=True)
    history_path = os.path.join(history_dir, "history.json")
    
    history = []
    if os.path.exists(history_path):
        try:
            with open(history_path, "r", encoding="utf-8") as f:
                history = json.load(f)
        except Exception as e:
            print(f"Error reading history.json: {e}")
            history = []
            
    fb_link = ""
    if post_type == "video":
        fb_link = f"https://www.facebook.com/reel/{fb_id}"
    else:
        fb_link = f"https://www.facebook.com/photo.php?fbid={fb_id}"
        
    entry = {
        "page_name": page_name,
        "page_id": page_id,
        "post_type": post_type,
        "fb_id": fb_id,
        "fb_link": fb_link,
        "title": title,
        "caption": caption,
        "topic": topic,
        "timestamp": datetime.utcnow().isoformat() + "Z"
    }
    
    history.insert(0, entry)
    history = history[:100]  # Keep last 100 uploads
    
    try:
        with open(history_path, "w", encoding="utf-8") as f:
            json.dump(history, f, indent=2, ensure_ascii=False)
        print(f"Log appended to history.json: {fb_link}")
    except Exception as e:
        print(f"Error writing to history.json: {e}")

def save_to_pending_uploads(page_name, page_id, access_token_env, file_path, post_type, title, caption, error_message):
    pending_dir = os.path.join("docs", "pending_uploads")
    os.makedirs(pending_dir, exist_ok=True)
    
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    file_ext = os.path.splitext(file_path)[1]
    pending_filename = f"{page_name.replace(' ', '_')}_{post_type}_{timestamp}{file_ext}"
    pending_file_path = os.path.join(pending_dir, pending_filename)
    
    try:
        shutil.copy2(file_path, pending_file_path)
        print(f"Copied failed post file to pending queue: {pending_file_path}")
    except Exception as e:
        print(f"Failed to copy file to pending directory: {e}")
        return
        
    queue_path = os.path.join("docs", "pending_uploads.json")
    queue = []
    if os.path.exists(queue_path):
        try:
            with open(queue_path, "r", encoding="utf-8") as f:
                queue = json.load(f)
        except Exception:
            queue = []
            
    entry = {
        "id": f"pending_{timestamp}_{random.randint(1000, 9999)}",
        "page_name": page_name,
        "page_id": page_id,
        "access_token_env": access_token_env,
        "file_path": f"docs/pending_uploads/{pending_filename}",
        "post_type": post_type,
        "title": title,
        "caption": caption,
        "error_message": str(error_message),
        "timestamp": datetime.utcnow().isoformat() + "Z"
    }
    queue.insert(0, entry)
    
    try:
        with open(queue_path, "w", encoding="utf-8") as f:
            json.dump(queue, f, indent=2, ensure_ascii=False)
        print(f"Added upload to docs/pending_uploads.json for page {page_name}")
    except Exception as e:
        print(f"Failed to write to pending_uploads.json: {e}")

def retry_pending_uploads(uploader):
    queue_path = os.path.join("docs", "pending_uploads.json")
    if not os.path.exists(queue_path):
        print("No pending uploads queue found.")
        return
        
    try:
        with open(queue_path, "r", encoding="utf-8") as f:
            queue = json.load(f)
    except Exception as e:
        print(f"Failed to read pending_uploads.json: {e}")
        return
        
    if not queue:
        print("Pending uploads queue is empty.")
        return
        
    print(f"Found {len(queue)} pending uploads. Retrying...")
    remaining_queue = []
    changes_made = False
    
    for entry in queue:
        page_name = entry["page_name"]
        page_id = entry["page_id"]
        env_var_name = entry["access_token_env"]
        file_path = entry["file_path"]
        post_type = entry["post_type"]
        title = entry["title"]
        caption = entry["caption"]
        
        print(f"\nRetrying upload for page '{page_name}' ({post_type})...")
        
        access_token = os.getenv(env_var_name)
        if not access_token:
            print(f"❌ Error: Environment variable {env_var_name} is empty or not set. Skipping.")
            remaining_queue.append(entry)
            continue
            
        if not os.path.exists(file_path):
            print(f"❌ Error: File {file_path} not found. Skipping.")
            remaining_queue.append(entry)
            continue
            
        try:
            if post_type == "video":
                fb_id = uploader.upload_video(
                    page_id=page_id,
                    access_token=access_token,
                    file_path=file_path,
                    title=title,
                    caption=caption
                )
            else:
                fb_id = uploader.upload_photo(
                    page_id=page_id,
                    access_token=access_token,
                    file_path=file_path,
                    caption=caption
                )
                
            if fb_id:
                print(f"✅ Successful retry upload for {page_name}! FB ID: {fb_id}")
                log_post_to_history(page_name, page_id, post_type, fb_id, title, caption, "Retried from pending queue")
                try:
                    os.remove(file_path)
                    print(f"Removed retried file from pending queue: {file_path}")
                except Exception as del_err:
                    print(f"Failed to delete {file_path}: {del_err}")
                changes_made = True
            else:
                print(f"❌ Failed retry for {page_name}: Uploader returned no ID.")
                remaining_queue.append(entry)
        except Exception as retry_err:
            print(f"❌ Failed retry for {page_name}: {retry_err}")
            entry["error_message"] = str(retry_err)
            remaining_queue.append(entry)
            
    if changes_made:
        try:
            with open(queue_path, "w", encoding="utf-8") as f:
                json.dump(remaining_queue, f, indent=2, ensure_ascii=False)
            print("\nUpdated pending_uploads.json successfully.")
        except Exception as e:
            print(f"Failed to write updated pending_uploads.json: {e}")
    else:
        print("\nNo retry uploads succeeded. Queue remains unchanged.")

def process_page(page, args, script_gen, image_gen, voice_gen, composer, uploader, stock_video_gen):
    page_name = page["page_name"]
    page_id = page["page_id"]
    
    # Check Schedule (unless forced or running manual single page trigger)
    schedule = page.get("schedule", [])
    if schedule and not args.force and not args.page:
        current_hour_utc = datetime.utcnow().hour
        if current_hour_utc not in schedule:
            print(f"\nSKIPPING PAGE '{page_name}': Current UTC hour {current_hour_utc} is not in schedule hours {schedule}.")
            return
            
    # Load access token from environment variable if configured
    access_token = page.get("access_token")
    if "access_token_env" in page:
        env_var_name = page["access_token_env"]
        access_token = os.getenv(env_var_name) or access_token
        
    topic = page["topic"]
    language = page["language"]
    
    # Custom Page overrides for ultimate flexibility
    text_model = page.get("text_model")
    image_model = page.get("image_model")
    custom_voice = page.get("voice")
    voice_gender = page.get("voice_gender", "male")
    voice_provider = page.get("voice_provider")
    voice_rate = page.get("voice_rate")
    voice_pitch = page.get("voice_pitch")
    bg_music = page.get("bg_music")
    aspect_ratio_video = page.get("aspect_ratio", "9:16")
    aspect_ratio_image = page.get("aspect_ratio", "1:1")
    video_source = page.get("video_source", "ai_images")
    
    print("\n" + "="*50)
    print(f"PROCESSING FACEBOOK PAGE: {page_name} (Active Hour)")
    print("="*50)

    # Determine post type (video or image)
    post_types = page.get("post_types", ["video"])
    if args.type:
        post_types = [args.type]

    # Setup directories
    temp_dir = os.path.join("assets", "temp")
    output_dir = os.path.join("assets", "output")
    os.makedirs(output_dir, exist_ok=True)

    for i in range(args.count):
        print(f"\nGenerating Post {i+1} of {args.count}...")
        clean_temp_dir(temp_dir)
        
        # Randomly pick between allowed post types for this run
        post_type = random.choice(post_types)
        print(f"Selected Post Type: {post_type.upper()}")

        try:
            if post_type == "video":
                # 1. Generate Script
                script = script_gen.generate_video_script(topic, language, model=text_model, page_name=page_name)
                print(f"Title: {script['title']}")
                print(f"Caption: {script['fb_caption'][:100]}...")

                # 2. Generate Assets (Voice & Images/Videos) per scene
                scene_audio_paths = []
                for idx, scene in enumerate(script["scenes"]):
                    scene_img_path = os.path.join(temp_dir, f"scene_{idx}.png")
                    scene_video_path = os.path.join(temp_dir, f"scene_{idx}.mp4")
                    scene_aud_path = os.path.join(temp_dir, f"scene_{idx}.mp3")
                    
                    # Generate TTS narration
                    voice_gen.generate_voice(
                        scene["narration"], 
                        scene_aud_path, 
                        language=language, 
                        voice=custom_voice,
                        gender=voice_gender,
                        provider=voice_provider,
                        rate=voice_rate,
                        pitch=voice_pitch
                    )
                    scene_audio_paths.append(scene_aud_path)
                    
                    # Decide if this scene uses video or image
                    use_video = False
                    if video_source == "stock_videos":
                        use_video = True
                    elif video_source == "hybrid":
                        # Alternate: even index scenes use video, odd use images
                        use_video = (idx % 2 == 0)
                        
                    downloaded_video = False
                    if use_video:
                        query = scene.get("video_query")
                        if query:
                            success = stock_video_gen.search_and_download_video(query, scene_video_path)
                            if success:
                                scene["video_path"] = scene_video_path
                                scene["media_type"] = "video"
                                downloaded_video = True
                                
                    if not downloaded_video:
                        # Fallback to AI image or primary image choice
                        if use_video:
                            print(f"Pexels fallback: Generating AI image for scene {idx}...")
                        image_gen.generate_image(scene["image_prompt"], scene_img_path, aspect_ratio=aspect_ratio_video, model=image_model)
                        scene["image_path"] = scene_img_path
                        scene["media_type"] = "image"

                # 3. Compose Video
                video_output_path = os.path.join(output_dir, f"{page_name.replace(' ', '_')}_post_{i+1}.mp4")
                composer.compose_video(script["scenes"], scene_audio_paths, video_output_path, bg_music_filename=bg_music)

                # 4. Upload to Facebook
                if not args.dry_run:
                    if not access_token or access_token in ["YOUR_FACEBOOK_PAGE_ACCESS_TOKEN_1", "YOUR_FACEBOOK_PAGE_ACCESS_TOKEN_2"]:
                        print(f"Skipping FB upload: Default placeholders or empty access token found. Check page token.")
                    else:
                        try:
                            fb_id = uploader.upload_video(
                                page_id=page_id,
                                access_token=access_token,
                                file_path=video_output_path,
                                title=script["title"],
                                caption=script["fb_caption"]
                            )
                            if fb_id:
                                log_post_to_history(page_name, page_id, "video", fb_id, script["title"], script["fb_caption"], topic)
                        except Exception as upload_err:
                            print(f"❌ Video upload failed for {page_name}: {upload_err}")
                            save_to_pending_uploads(
                                page_name=page_name,
                                page_id=page_id,
                                access_token_env=page.get("access_token_env", "FB_PAGE_TOKEN"),
                                file_path=video_output_path,
                                post_type="video",
                                title=script["title"],
                                caption=script["fb_caption"],
                                error_message=upload_err
                            )
                            raise upload_err
                else:
                    print(f"[DRY RUN] Generated video saved locally at: {video_output_path} (Facebook upload skipped)")

            elif post_type == "image":
                # 1. Generate Image Post Script
                script = script_gen.generate_image_post(topic, language, model=text_model, page_name=page_name)
                print(f"Overlay text: {script['overlay_text']}")
                print(f"Caption: {script['fb_caption'][:100]}...")

                # 2. Generate Image (Default square 1:1 unless override in pages.json)
                temp_img_path = os.path.join(temp_dir, "raw_image.png")
                image_gen.generate_image(script["image_prompt"], temp_img_path, aspect_ratio=aspect_ratio_image, model=image_model)

                # 3. Overlay Text
                image_output_path = os.path.join(output_dir, f"{page_name.replace(' ', '_')}_post_{i+1}.png")
                font_path = composer.font_path
                overlay_text_on_image(temp_img_path, script["overlay_text"], image_output_path, font_path)

                # 4. Upload to Facebook
                if not args.dry_run:
                    if not access_token or access_token in ["YOUR_FACEBOOK_PAGE_ACCESS_TOKEN_1", "YOUR_FACEBOOK_PAGE_ACCESS_TOKEN_2"]:
                        print(f"Skipping FB upload: Default placeholders or empty access token found. Check page token.")
                    else:
                        try:
                            fb_id = uploader.upload_photo(
                                page_id=page_id,
                                access_token=access_token,
                                file_path=image_output_path,
                                caption=script["fb_caption"]
                            )
                            if fb_id:
                                log_post_to_history(page_name, page_id, "image", fb_id, "", script["fb_caption"], topic)
                        except Exception as upload_err:
                            print(f"❌ Image upload failed for {page_name}: {upload_err}")
                            save_to_pending_uploads(
                                page_name=page_name,
                                page_id=page_id,
                                access_token_env=page.get("access_token_env", "FB_PAGE_TOKEN"),
                                file_path=image_output_path,
                                post_type="image",
                                title="",
                                caption=script["fb_caption"],
                                error_message=upload_err
                            )
                            raise upload_err
                else:
                    print(f"[DRY RUN] Generated image saved locally at: {image_output_path} (Facebook upload skipped)")

        except Exception as e:
            print(f"Error processing post {i+1} for page {page_name}: {e}")
            import traceback
            traceback.print_exc()

    # Clean temp files at the end
    clean_temp_dir(temp_dir)

def main():
    args = parse_args()
    
    # Load configuration
    try:
        pages = load_pages()
    except Exception as e:
        print(f"Error loading pages.json: {e}")
        return

    # Initialize modules
    try:
        script_gen = ScriptGenerator()
        image_gen = ImageGenerator()
        voice_gen = VoiceGenerator()
        composer = VideoComposer()
        uploader = FBUploader()
        stock_video_gen = StockVideoGenerator()
    except ValueError as e:
        print(f"Configuration Error: {e}")
        print("Please make sure NVIDIA_API_KEY is set in your .env file.")
        return
    except Exception as e:
        print(f"Error initializing modules: {e}")
        return

    # Handle retry pending uploads if flag is set
    if args.retry_pending:
        retry_pending_uploads(uploader)
        print("\nRetry process completed.")
        return

    # Filter pages if --page argument is provided
    if args.page:
        pages = [p for p in pages if p["page_name"].lower() == args.page.lower()]
        if not pages:
            print(f"No page found with name: {args.page}")
            return

    # Run loop
    for page in pages:
        process_page(page, args, script_gen, image_gen, voice_gen, composer, uploader, stock_video_gen)

    print("\nAutomation task completed successfully!")

if __name__ == "__main__":
    main()
