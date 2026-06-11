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

load_dotenv()

def parse_args():
    parser = argparse.ArgumentParser(description="AI Video & Image Automation for Facebook Pages")
    parser.add_argument("--dry-run", action="store_true", help="Generate posts locally but do not upload to Facebook")
    parser.add_argument("--count", type=int, default=1, help="Number of posts to generate per page")
    parser.add_argument("--page", type=str, default=None, help="Name of a specific page in pages.json to process")
    parser.add_argument("--type", type=str, choices=["video", "image"], default=None, help="Force a specific post type (video or image)")
    parser.add_argument("--force", action="store_true", help="Force execution regardless of scheduled hours")
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

def process_page(page, args, script_gen, image_gen, voice_gen, composer, uploader):
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
    bg_music = page.get("bg_music")
    aspect_ratio_video = page.get("aspect_ratio", "9:16")
    aspect_ratio_image = page.get("aspect_ratio", "1:1")
    
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
                script = script_gen.generate_video_script(topic, language, model=text_model)
                print(f"Title: {script['title']}")
                print(f"Caption: {script['fb_caption'][:100]}...")

                # 2. Generate Assets (Voice & Images) per scene
                scene_audio_paths = []
                for idx, scene in enumerate(script["scenes"]):
                    scene_img_path = os.path.join(temp_dir, f"scene_{idx}.png")
                    scene_aud_path = os.path.join(temp_dir, f"scene_{idx}.mp3")
                    
                    # Generate AI image
                    image_gen.generate_image(scene["image_prompt"], scene_img_path, aspect_ratio=aspect_ratio_video, model=image_model)
                    # Generate TTS narration
                    voice_gen.generate_voice(scene["narration"], scene_aud_path, language=language, voice=custom_voice)
                    
                    scene["image_path"] = scene_img_path
                    scene_audio_paths.append(scene_aud_path)

                # 3. Compose Video
                video_output_path = os.path.join(output_dir, f"{page_name.replace(' ', '_')}_post_{i+1}.mp4")
                composer.compose_video(script["scenes"], scene_audio_paths, video_output_path, bg_music_filename=bg_music)

                # 4. Upload to Facebook
                if not args.dry_run:
                    if not access_token or access_token in ["YOUR_FACEBOOK_PAGE_ACCESS_TOKEN_1", "YOUR_FACEBOOK_PAGE_ACCESS_TOKEN_2"]:
                        print(f"Skipping FB upload: Default placeholders or empty access token found. Check page token.")
                    else:
                        uploader.upload_video(
                            page_id=page_id,
                            access_token=access_token,
                            file_path=video_output_path,
                            title=script["title"],
                            caption=script["fb_caption"]
                        )
                else:
                    print(f"[DRY RUN] Generated video saved locally at: {video_output_path} (Facebook upload skipped)")

            elif post_type == "image":
                # 1. Generate Image Post Script
                script = script_gen.generate_image_post(topic, language, model=text_model)
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
                        uploader.upload_photo(
                            page_id=page_id,
                            access_token=access_token,
                            file_path=image_output_path,
                            caption=script["fb_caption"]
                        )
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
    except ValueError as e:
        print(f"Configuration Error: {e}")
        print("Please make sure NVIDIA_API_KEY is set in your .env file.")
        return
    except Exception as e:
        print(f"Error initializing modules: {e}")
        return

    # Filter pages if --page argument is provided
    if args.page:
        pages = [p for p in pages if p["page_name"].lower() == args.page.lower()]
        if not pages:
            print(f"No page found with name: {args.page}")
            return

    # Run loop
    for page in pages:
        process_page(page, args, script_gen, image_gen, voice_gen, composer, uploader)

    print("\nAutomation task completed successfully!")

if __name__ == "__main__":
    main()

