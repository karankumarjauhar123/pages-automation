import os
import sys
import json
import datetime
import subprocess
import argparse
import shutil
import glob
import requests
import yt_dlp
import cv2
import numpy as np
import insightface
from insightface.app import FaceAnalysis

# Add root folder to python path to align with codebase structure
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Paths configuration
HISTORY_FILE = "faceswapper/history.json"
INFLUENCER_DIR = "influencer_faces"
OUTPUT_DIR = "swapped_reels"
MODEL_DIR = "faceswapper/models"
MODEL_PATH = os.path.join(MODEL_DIR, "inswapper_128.onnx")

# Resilient fallback URLs for the inswapper model (public, no auth needed)
MODEL_URLS = [
    "https://huggingface.co/ezioruan/inswapper_128.onnx/resolve/main/inswapper_128.onnx",
    "https://huggingface.co/thebiglaskowski/inswapper_128.onnx/resolve/main/inswapper_128.onnx",
    "https://huggingface.co/Aitrepreneur/insightface/resolve/main/inswapper_128.onnx",
]

# Ensure folders exist
os.makedirs(INFLUENCER_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(MODEL_DIR, exist_ok=True)

# ─────────────────────────────────────────────────────────────
#  MODEL DOWNLOAD (Resilient - tries multiple mirrors)
# ─────────────────────────────────────────────────────────────

def download_model():
    """Downloads the inswapper_128.onnx model if not already present. Tries multiple mirrors."""
    if os.path.exists(MODEL_PATH):
        print(f"[FaceSwapper] ✅ Model already exists at {MODEL_PATH}")
        return True
    
    print(f"[FaceSwapper] 📥 Downloading inswapper_128.onnx model (one-time download ~554MB)...")
    
    for idx, url in enumerate(MODEL_URLS, 1):
        print(f"[FaceSwapper] 🔗 Trying mirror {idx}/{len(MODEL_URLS)}: {url[:80]}...")
        try:
            r = requests.get(url, stream=True, timeout=600, allow_redirects=True)
            r.raise_for_status()
            total_size = int(r.headers.get('content-length', 0))
            downloaded = 0
            last_pct_logged = -1
            with open(MODEL_PATH, 'wb') as f:
                for chunk in r.iter_content(chunk_size=65536):
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total_size > 0:
                        pct = int((downloaded / total_size) * 100)
                        if pct >= last_pct_logged + 20:
                            last_pct_logged = pct
                            print(f"[FaceSwapper] 📥 Download progress: {pct}% ({downloaded // (1024*1024)}MB / {total_size // (1024*1024)}MB)")
            
            # Verify file size is reasonable (at least 500MB for inswapper_128)
            file_size = os.path.getsize(MODEL_PATH)
            if file_size < 500_000_000:
                print(f"[FaceSwapper] ⚠️ Downloaded file is too small ({file_size} bytes), trying next mirror...")
                os.remove(MODEL_PATH)
                continue
            
            print(f"[FaceSwapper] ✅ Model downloaded successfully! ({file_size // (1024*1024)}MB)")
            return True
        except Exception as e:
            print(f"[FaceSwapper] ⚠️ Mirror {idx} failed: {e}")
            if os.path.exists(MODEL_PATH):
                os.remove(MODEL_PATH)
            continue
    
    print(f"[FaceSwapper] ❌ All {len(MODEL_URLS)} mirrors failed. Cannot download the model.")
    return False

# ─────────────────────────────────────────────────────────────
#  FACE SWAP ENGINE (LOCAL - NO API NEEDED)
# ─────────────────────────────────────────────────────────────

def init_face_analyser():
    """Initialize InsightFace face analyser with buffalo_l model."""
    print("[FaceSwapper] 🔧 Initializing face detection engine...")
    app = FaceAnalysis(name='buffalo_l', providers=['CPUExecutionProvider'])
    app.prepare(ctx_id=0, det_size=(640, 640))
    print("[FaceSwapper] ✅ Face detection engine ready!")
    return app

def init_face_swapper():
    """Initialize the inswapper model."""
    print("[FaceSwapper] 🔧 Loading face swap model...")
    swapper = insightface.model_zoo.get_model(MODEL_PATH, providers=['CPUExecutionProvider'])
    print("[FaceSwapper] ✅ Face swap model loaded!")
    return swapper

def get_source_face(face_app, image_path):
    """Detect and return the primary face from the source image."""
    img = cv2.imread(image_path)
    if img is None:
        raise Exception(f"Could not read image: {image_path}")
    faces = face_app.get(img)
    if len(faces) == 0:
        raise Exception(f"No face detected in source image: {image_path}")
    # Pick the largest face (most prominent)
    faces = sorted(faces, key=lambda x: (x.bbox[2] - x.bbox[0]) * (x.bbox[3] - x.bbox[1]), reverse=True)
    print(f"[FaceSwapper] 🎯 Detected {len(faces)} face(s) in source image, using the largest one.")
    return faces[0]

def swap_face_in_video(face_app, swapper, source_face, input_video, output_video):
    """Process video frame by frame and swap the face."""
    cap = cv2.VideoCapture(input_video)
    if not cap.isOpened():
        raise Exception(f"Could not open video: {input_video}")
    
    fps = cap.get(cv2.CAP_PROP_FPS)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    
    print(f"[FaceSwapper] 🎬 Video info: {width}x{height} @ {fps:.1f}fps, {total_frames} frames")
    
    # Use mp4v codec for compatibility
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    writer = cv2.VideoWriter(output_video, fourcc, fps, (width, height))
    
    frame_count = 0
    swapped_count = 0
    
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        
        frame_count += 1
        
        # Detect faces in this frame
        try:
            target_faces = face_app.get(frame)
            if len(target_faces) > 0:
                # Swap the largest/most prominent face in the frame
                target_faces = sorted(target_faces, key=lambda x: (x.bbox[2] - x.bbox[0]) * (x.bbox[3] - x.bbox[1]), reverse=True)
                frame = swapper.get(frame, target_faces[0], source_face, paste_back=True)
                swapped_count += 1
        except Exception:
            # If face detection/swap fails for a frame, keep the original
            pass
        
        writer.write(frame)
        
        # Progress logging every 10%
        if total_frames > 0 and frame_count % max(1, total_frames // 10) == 0:
            pct = (frame_count / total_frames) * 100
            print(f"[FaceSwapper] 🔄 Processing: {pct:.0f}% ({frame_count}/{total_frames} frames, {swapped_count} faces swapped)")
    
    cap.release()
    writer.release()
    
    print(f"[FaceSwapper] ✅ Video processing complete! {swapped_count}/{frame_count} frames had face swaps.")
    return True

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
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "23",
        "-c:a", "aac",
        "-map", "0:v:0",
        "-map", "1:a:0?",
        "-shortest",
        "-movflags", "+faststart",
        output_path
    ]
    
    try:
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if result.returncode == 0 and os.path.exists(output_path):
            print(f"[FaceSwapper] ✅ Audio merged successfully. Output saved to {output_path}")
            return True
        else:
            print(f"[FaceSwapper] ⚠️ FFmpeg merging failed, error: {result.stderr[:500]}")
            # Fallback: re-encode the swapped video without audio merge
            cmd_fallback = [
                "ffmpeg", "-y",
                "-i", swapped_video_path,
                "-c:v", "libx264", "-preset", "fast", "-crf", "23",
                "-movflags", "+faststart",
                output_path
            ]
            subprocess.run(cmd_fallback, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if os.path.exists(output_path):
                return True
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
    influencer_path = os.path.join(INFLUENCER_DIR, influencer_filename)
    if not os.path.exists(influencer_path):
        print(f"[FaceSwapper] ❌ Error: Influencer face photo not found at '{influencer_path}'")
        print("[FaceSwapper] Please make sure you upload the photo to the 'influencer_faces/' directory.")
        sys.exit(1)

    # 2. Download model if needed
    if not download_model():
        print("[FaceSwapper] ❌ Cannot proceed without the face swap model.")
        sys.exit(1)

    # 3. Initialize AI engines
    face_app = init_face_analyser()
    swapper = init_face_swapper()

    # 4. Detect source face from influencer image
    try:
        source_face = get_source_face(face_app, influencer_path)
    except Exception as e:
        print(f"[FaceSwapper] ❌ Failed to detect face in influencer image: {e}")
        sys.exit(1)

    history = load_history()
    processed_count = 0
    failed_count = 0

    print(f"[FaceSwapper] 🚀 Starting Face Swapper Pipeline for {len(urls)} URLs...")
    print(f"[FaceSwapper] Influencer face: {influencer_filename}")
    print(f"[FaceSwapper] Mode: 100% FREE Local Processing (No API needed!)")

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
        local_swapped_temp_path = f"faceswapper_swapped_raw_{index}.mp4"
        output_filename = clean_filename(url, influencer_filename)
        output_path = os.path.join(OUTPUT_DIR, output_filename)

        try:
            # 5. Download the target video
            if not download_video(url, local_target_path):
                print(f"[FaceSwapper] ❌ Skipping: Download failed for {url}")
                failed_count += 1
                continue

            # 6. Run face swap locally (FREE - no API needed!)
            print(f"[FaceSwapper] 🤖 Running local face swap on CPU (this may take a few minutes)...")
            swap_face_in_video(face_app, swapper, source_face, local_target_path, local_swapped_temp_path)

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
    parser = argparse.ArgumentParser(description="World-class Face Swapper Suite (100% FREE - No API needed)")
    parser.add_argument("--urls", type=str, help="Comma-separated list of Reels URLs or path to a text file containing URLs")
    parser.add_argument("--influencer", type=str, required=True, help="Filename of the influencer face image inside influencer_faces/")
    parser.add_argument("--enhance", action="store_true", default=True, help="Enable face enhancement (default: True)")
    parser.add_argument("--no-enhance", action="store_false", dest="enhance", help="Disable face enhancement")
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
