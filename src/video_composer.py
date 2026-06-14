import os
import numpy as np
import requests
from PIL import Image, ImageDraw, ImageFont
from moviepy.editor import ImageClip, AudioFileClip, concatenate_videoclips, CompositeAudioClip, VideoClip
from dotenv import load_dotenv

load_dotenv()

class VideoComposer:
    def __init__(self, output_width=1080, output_height=1920, fps=30):
        """
        Initialize the Video Composer.
        Target resolution: 1080x1920 (9:16 vertical Reels format).
        """
        self.width = output_width
        self.height = output_height
        self.fps = fps
        self.font_dir = os.path.join("assets", "fonts")
        self.music_dir = os.path.join("assets", "background_music")
        self._temp_clips_to_close = []
        
        # Ensure directories exist
        os.makedirs(self.font_dir, exist_ok=True)
        os.makedirs(self.music_dir, exist_ok=True)
        
        # Download a clean modern font if none exists
        self.font_path = self._ensure_font_exists()

    def _ensure_font_exists(self):
        """
        Ensures a premium bold font (Montserrat Bold) is downloaded for subtitles.
        """
        font_file = os.path.join(self.font_dir, "Montserrat-Bold.ttf")
        if not os.path.exists(font_file):
            print("Downloading premium Montserrat-Bold font for subtitles...")
            font_url = "https://github.com/JulietaUla/Montserrat/raw/master/fonts/ttf/Montserrat-Bold.ttf"
            try:
                r = requests.get(font_url, timeout=15)
                with open(font_file, "wb") as f:
                    f.write(r.content)
                print("Font downloaded successfully.")
            except Exception as e:
                print(f"Warning: Could not download font, falling back to PIL default font. Error: {e}")
                return None
        return font_file

    def _get_font(self, size):
        """
        Load the font at specified size.
        """
        if self.font_path and os.path.exists(self.font_path):
            try:
                return ImageFont.truetype(self.font_path, size)
            except Exception:
                pass
        return ImageFont.load_default()

    def _create_scene_clip(self, media_path, media_type, audio_path, narration_text):
        """
        Creates a single video scene with Ken Burns effect (for images) 
        or raw video frames (for videos), and overlays highlighted subtitles.
        """
        # Load audio and get duration
        audio_clip = AudioFileClip(audio_path)
        duration = audio_clip.duration
        
        # Setup video source
        raw_video_clip = None
        pil_img = None
        if media_type == "video":
            from moviepy.editor import VideoFileClip
            raw_video_clip = VideoFileClip(media_path)
            self._temp_clips_to_close.append(raw_video_clip)
        else:
            # Load image
            pil_img = Image.open(media_path)
            if pil_img.mode != "RGB":
                pil_img = pil_img.convert("RGB")

        # Split narration into words for word-by-word highlights
        words = narration_text.split()
        num_words = len(words)
        
        # Compute display windows of phrases (groups of 3-5 words) to avoid overcrowding
        phrase_size = 4
        phrases = []
        for i in range(0, num_words, phrase_size):
            phrases.append(words[i:i+phrase_size])
            
        num_phrases = len(phrases)
        phrase_duration = duration / max(num_phrases, 1)

        # Dynamic frame generator to run Ken Burns + Subtitles in memory
        def make_frame(t):
            if media_type == "video":
                # Get the frame from video at t (loop if video is shorter than duration)
                v_t = t % raw_video_clip.duration
                frame_array = raw_video_clip.get_frame(v_t)
                
                # Convert to PIL Image for drawing and resizing/cropping
                frame_img_pil = Image.fromarray(frame_array)
                if frame_img_pil.mode != "RGB":
                    frame_img_pil = frame_img_pil.convert("RGB")
                
                w_orig, h_orig = frame_img_pil.size
                
                # Crop center box to vertical aspect ratio (9:16)
                crop_w = w_orig
                crop_h = crop_w * (self.height / self.width)
                
                if crop_h > h_orig:
                    crop_h = h_orig
                    crop_w = crop_h * (self.width / self.height)
                    
                x_offset = (w_orig - crop_w) / 2
                y_offset = (h_orig - crop_h) / 2
                
                cropped = frame_img_pil.crop((
                    x_offset, y_offset, 
                    x_offset + crop_w, y_offset + crop_h
                ))
                frame_img = cropped.resize((self.width, self.height), Image.Resampling.LANCZOS)
            else:
                # 1. Ken Burns Zoom Effect (Slow zoom-in from 1.0 to 1.12)
                zoom = 1.0 + 0.12 * (t / duration)
                w_orig, h_orig = pil_img.size
                
                # Crop center box based on zoom and vertical aspect ratio (9:16)
                crop_w = w_orig / zoom
                crop_h = crop_w * (self.height / self.width)
                
                # Handle height overflow
                if crop_h > h_orig:
                    crop_h = h_orig
                    crop_w = crop_h * (self.width / self.height)
                    
                x_offset = (w_orig - crop_w) / 2
                y_offset = (h_orig - crop_h) / 2
                
                cropped = pil_img.crop((
                    x_offset, y_offset, 
                    x_offset + crop_w, y_offset + crop_h
                ))
                
                # Resize cropped section to target resolution
                frame_img = cropped.resize((self.width, self.height), Image.Resampling.LANCZOS)

            draw = ImageDraw.Draw(frame_img)
            
            # 2. Draw Subtitles (Hormozi style)
            if num_words > 0:
                # Find current phrase and active word index
                phrase_idx = min(int(t / phrase_duration), num_phrases - 1)
                current_phrase = phrases[phrase_idx]
                
                # Active word index inside the current phrase
                time_in_phrase = t - (phrase_idx * phrase_duration)
                word_duration = phrase_duration / len(current_phrase)
                active_word_in_phrase_idx = min(int(time_in_phrase / word_duration), len(current_phrase) - 1)
                
                # Draw text
                font = self._get_font(60) # High impact font size
                text_y = self.height * 0.75 # Lower third area
                
                # Compute total text width to center it
                word_widths = [draw.textbbox((0, 0), w, font=font)[2] for w in current_phrase]
                space_width = draw.textbbox((0, 0), " ", font=font)[2]
                total_width = sum(word_widths) + space_width * (len(current_phrase) - 1)
                
                start_x = (self.width - total_width) / 2
                current_x = start_x
                
                for idx, w in enumerate(current_phrase):
                    # Active word is bright yellow, others are white
                    color = (255, 204, 0) if idx == active_word_in_phrase_idx else (255, 255, 255)
                    
                    # Draw text border (heavy black outline) for readability
                    for dx in [-3, -2, -1, 0, 1, 2, 3]:
                        for dy in [-3, -2, -1, 0, 1, 2, 3]:
                            if dx != 0 or dy != 0:
                                draw.text((current_x + dx, text_y + dy), w, font=font, fill=(0, 0, 0))
                    
                    # Draw word
                    draw.text((current_x, text_y), w, font=font, fill=color)
                    current_x += word_widths[idx] + space_width
                    
            # Return frame as numpy array
            return np.array(frame_img)

        # Create VideoClip from generator
        video_clip = VideoClip(make_frame, duration=duration)
        video_clip = video_clip.set_audio(audio_clip)
        return video_clip

    def compose_video(self, scenes, scene_audio_paths, output_path, bg_music_filename=None):
        """
        scenes: list of dicts, each with {"narration": "...", "image_path": "..."}
        scene_audio_paths: list of paths to TTS files for each scene
        output_path: target video output filename (.mp4)
        """
        print(f"Starting compilation of {len(scenes)} scenes into {output_path}...")
        
        self._temp_clips_to_close = []
        scene_clips = []
        for i, scene in enumerate(scenes):
            media_type = scene.get("media_type", "image")
            media_path = scene.get("video_path") if media_type == "video" else scene.get("image_path")
            aud_path = scene_audio_paths[i]
            narr = scene["narration"]
            
            # Create individual scene video clip
            clip = self._create_scene_clip(media_path, media_type, aud_path, narr)
            scene_clips.append(clip)
            
        # Concatenate all clips with method compose
        final_video = concatenate_videoclips(scene_clips, method="compose")
        total_duration = final_video.duration
        
        # Add background music if available
        bg_music_path = None
        if bg_music_filename:
            bg_music_path = os.path.join(self.music_dir, bg_music_filename)
            
        # Check if there is any mp3 in background_music directory as a fallback
        if not bg_music_path or not os.path.exists(bg_music_path):
            files = [f for f in os.listdir(self.music_dir) if f.endswith(".mp3")]
            if files:
                bg_music_path = os.path.join(self.music_dir, files[0])
                print(f"Selected fallback background music: {files[0]}")
            else:
                bg_music_path = None
                
        if bg_music_path and os.path.exists(bg_music_path):
            try:
                print(f"Adding background music: {bg_music_path}")
                music_clip = AudioFileClip(bg_music_path).loop(duration=total_duration)
                
                # Audio Ducking: lowers background music volume to 10% (0.10) 
                # so the main voiceover is perfectly audible
                music_clip = music_clip.volumex(0.12)
                
                # Merge original voiceover audio and background music
                original_audio = final_video.audio
                mixed_audio = CompositeAudioClip([original_audio, music_clip])
                final_video = final_video.set_audio(mixed_audio)
            except Exception as e:
                print(f"Warning: Could not mix background music: {e}")
        else:
            print("No background music found. Video will be compiled with voiceover only.")

        # Write output video file
        print("Rendering video (this may take a few moments)...")
        try:
            final_video.write_videofile(
                output_path, 
                fps=self.fps, 
                codec="libx264", 
                audio_codec="aac",
                temp_audiofile=os.path.join("assets", "temp_audio.m4a"),
                remove_temp=True,
                logger=None # Hide moviepy verbose logs for clean CLI output
            )
            print(f"Rendering complete! Video saved to: {output_path}")
        finally:
            # Close all clip handlers
            final_video.close()
            for c in scene_clips:
                try:
                    c.close()
                except Exception:
                    pass
            for c in self._temp_clips_to_close:
                try:
                    c.close()
                except Exception:
                    pass
            self._temp_clips_to_close = []
            
        return True
