import os
import random
import subprocess
import json
import requests
from PIL import Image, ImageDraw, ImageFont

class Editor:
    def __init__(self, font_dir="assets/fonts", output_width=1080, output_height=1920):
        self.font_dir = font_dir
        self.width = output_width
        self.height = output_height
        os.makedirs(self.font_dir, exist_ok=True)

    def _ensure_font_exists(self, font_name):
        """
        Ensures the requested font is downloaded.
        Supports Montserrat-Bold.ttf and NotoSansDevanagari-Bold.ttf.
        """
        font_path = os.path.join(self.font_dir, font_name)
        if os.path.exists(font_path):
            return font_path

        # URL mapping for standard free fonts
        urls = {
            "Montserrat-Bold.ttf": "https://github.com/JulietaUla/Montserrat/raw/master/fonts/ttf/Montserrat-Bold.ttf",
            "NotoSansDevanagari-Bold.ttf": "https://github.com/googlefonts/noto-fonts/raw/main/hinted/ttf/NotoSansDevanagari/NotoSansDevanagari-Bold.ttf"
        }

        if font_name not in urls:
            print(f"[Editor] Unknown font '{font_name}', falling back to default.")
            return None

        url = urls[font_name]
        print(f"[Editor] Downloading font '{font_name}' from {url}...")
        try:
            r = requests.get(url, timeout=20)
            r.raise_for_status()
            with open(font_path, "wb") as f:
                f.write(r.content)
            print(f"[Editor] ✅ Font '{font_name}' downloaded successfully.")
            return font_path
        except Exception as e:
            print(f"[Editor] ⚠️ Error downloading font '{font_name}': {e}")
            return None

    def _has_audio(self, video_path):
        """Checks if the video has an audio stream using ffprobe."""
        cmd = [
            "ffprobe", "-v", "error", "-select_streams", "a",
            "-show_entries", "stream=codec_name", "-of", "json", video_path
        ]
        try:
            output = subprocess.check_output(cmd, stderr=subprocess.STDOUT)
            data = json.loads(output)
            return len(data.get("streams", [])) > 0
        except Exception as e:
            print(f"[Editor] Warning: ffprobe audio check failed: {e}")
            return False

    def _draw_centered_text(self, draw, text, font, color, center_x, center_y, max_width):
        """Helper to draw wrapped and centered text in Pillow."""
        words = text.split()
        lines = []
        current_line = []
        
        for word in words:
            test_line = " ".join(current_line + [word])
            try:
                w = draw.textbbox((0, 0), test_line, font=font)[2]
            except AttributeError:
                w = font.getsize(test_line)[0]
                
            if w <= max_width:
                current_line.append(word)
            else:
                if current_line:
                    lines.append(" ".join(current_line))
                    current_line = [word]
                else:
                    lines.append(word)
        if current_line:
            lines.append(" ".join(current_line))
            
        # Get line heights and total height
        line_heights = []
        for line in lines:
            try:
                bbox = draw.textbbox((0, 0), line, font=font)
                h = bbox[3] - bbox[1]
            except AttributeError:
                h = font.getsize(line)[1]
            line_heights.append(h)
            
        spacing = 8
        total_height = sum(line_heights) + spacing * (len(lines) - 1)
        
        current_y = center_y - total_height / 2
        for line, h in zip(lines, line_heights):
            try:
                w = draw.textbbox((0, 0), line, font=font)[2]
            except AttributeError:
                w = font.getsize(line)[0]
            x = center_x - w / 2
            draw.text((x, current_y), line, fill=color, font=font)
            current_y += h + spacing

    def create_overlay_image(self, hook_text, cta_text, watermark, watermark_opacity, bg_color_rgb, text_color_rgb, font_name, output_path="reposter/temp_overlay.png"):
        """
        Creates a transparent 1080x1920 PNG with top/bottom banners and watermark.
        """
        img = Image.new("RGBA", (self.width, self.height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        # Draw top banner (solid bg)
        top_banner_h = 160
        draw.rectangle([0, 0, self.width, top_banner_h], fill=tuple(bg_color_rgb) + (255,))

        # Draw bottom banner (solid bg)
        bottom_banner_h = 140
        draw.rectangle([0, self.height - bottom_banner_h, self.width, self.height], fill=tuple(bg_color_rgb) + (255,))

        # Load font
        font_path = self._ensure_font_exists(font_name)
        
        # Load banner font (size 48 for hook, size 42 for CTA)
        if font_path:
            hook_font = ImageFont.truetype(font_path, 48)
            cta_font = ImageFont.truetype(font_path, 42)
            watermark_font = ImageFont.truetype(font_path, 32)
        else:
            hook_font = ImageFont.load_default()
            cta_font = ImageFont.load_default()
            watermark_font = ImageFont.load_default()

        # Draw Hook Text (Top)
        self._draw_centered_text(
            draw=draw,
            text=hook_text,
            font=hook_font,
            color=tuple(text_color_rgb) + (255,),
            center_x=self.width // 2,
            center_y=top_banner_h // 2,
            max_width=self.width - 80
        )

        # Draw CTA Text (Bottom)
        self._draw_centered_text(
            draw=draw,
            text=cta_text,
            font=cta_font,
            color=tuple(text_color_rgb) + (255,),
            center_x=self.width // 2,
            center_y=self.height - (bottom_banner_h // 2),
            max_width=self.width - 80
        )

        # Draw Watermark (just above bottom banner)
        if watermark:
            watermark_color = (255, 255, 255, int(255 * watermark_opacity))
            try:
                w_w = draw.textbbox((0, 0), watermark, font=watermark_font)[2]
            except AttributeError:
                w_w = watermark_font.getsize(watermark)[0]
            
            x = (self.width - w_w) // 2
            y = self.height - bottom_banner_h - 60
            draw.text((x, y), watermark, fill=watermark_color, font=watermark_font)

        img.save(output_path, "PNG")
        print(f"[Editor] ✅ Overlay image saved to {output_path}")
        return output_path

    def transform_video(self, input_video, overlay_image, edit_style, output_video="reposter/temp_output.mp4"):
        """
        Runs a highly optimized ffmpeg pipeline applying:
        - Mirror flip (horizontal flip)
        - Crop & zoom (converts any aspect ratio to 9:16 + adds anti-detection crop)
        - Color shifting (brightness/contrast tweaks)
        - Speed warp (audio & video sped up by random factor, preserving pitch)
        - Overlays the transparent banner PNG on top
        """
        if os.path.exists(output_video):
            try:
                os.remove(output_video)
            except Exception:
                pass

        # 1. Randomize transformation parameters based on edit_style
        speed_factor = round(random.uniform(edit_style["speed_range"][0], edit_style["speed_range"][1]), 3)
        zoom_factor = round(random.uniform(edit_style["zoom_range"][0], edit_style["zoom_range"][1]), 3)
        brightness_shift = round(random.uniform(edit_style["brightness_shift"][0], edit_style["brightness_shift"][1]), 3)
        
        # Calculate anti-detection zoom crop factor (smaller crop box = larger zoom-in)
        crop_zoom = round(1.0 / zoom_factor, 3)

        # 2. Check if video has audio stream
        has_aud = self._has_audio(input_video)
        
        # 3. Construct the filter_complex string
        # [0:v] -> Crop to 9:16 & zoom in -> Flip -> Adjust color
        crop_filter = f"crop=w='min(iw,ih*9/16)*{crop_zoom}':h='min(ih,iw*16/9)*{crop_zoom}'"
        scale_filter = f"scale={self.width}:{self.height}"
        eq_filter = f"eq=brightness={brightness_shift}:contrast=1.02:saturation=1.03"
        
        video_filters = [crop_filter, scale_filter]
        if edit_style.get("mirror_flip", True):
            video_filters.append("hflip")
        video_filters.append(eq_filter)
        
        # Speed warp filter
        video_filters.append(f"setpts=PTS/{speed_factor}")
        
        video_filter_chain = ",".join(video_filters)
        
        filter_complex = f"[0:v]{video_filter_chain}[v_transformed]; [v_transformed][1:v]overlay=x=0:y=0"
        
        if has_aud:
            # Sped up audio while maintaining pitch
            filter_complex += f"; [0:a]atempo={speed_factor}"
            
        filter_complex += "[v_out]"
        if has_aud:
            filter_complex += "; [0:a]atempo=1.0" # placeholder stream descriptor placeholder
            # Actually we can map [a_out] directly
            filter_complex = filter_complex.replace("; [0:a]atempo=1.0", "")
            filter_complex = filter_complex.replace(f"; [0:a]atempo={speed_factor}", f"; [0:a]atempo={speed_factor}[a_out]")
        
        # 4. Formulate the subprocess CLI command
        cmd = [
            "ffmpeg", "-y",
            "-i", input_video,
            "-i", overlay_image,
            "-filter_complex", filter_complex,
            "-map", "[v_out]"
        ]
        
        if has_aud:
            cmd.extend(["-map", "[a_out]"])
            
        cmd.extend([
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "22",
            "-c:a", "aac",
            "-b:a", "128k",
            output_video
        ])

        print(f"[Editor] Transforming video with speed: {speed_factor}x, zoom: {zoom_factor}x, brightness shift: {brightness_shift}")
        print(f"[Editor] Executing command: {' '.join(cmd)}")
        
        try:
            # Run the command
            result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
            print("[Editor] ✅ ffmpeg processing finished successfully.")
            
            if os.path.exists(output_video) and os.path.getsize(output_video) > 0:
                return output_video
            else:
                raise FileNotFoundError("Output video file is empty or missing")
        except subprocess.CalledProcessError as e:
            print(f"[Editor] ❌ ffmpeg failed with exit code {e.returncode}")
            print(f"[Editor] stderr: {e.stderr[-1000:]}")
            raise RuntimeError(f"Video transformation failed: {e.stderr[-500:]}")

if __name__ == "__main__":
    # Test script
    editor = Editor()
    overlay = editor.create_overlay_image(
        hook_text="ये गलतियां मत करना ❌",
        cta_text="फॉलो करो और सीखो 🔥",
        watermark="@test.page",
        watermark_opacity=0.4,
        bg_color_rgb=[120, 30, 0],
        text_color_rgb=[255, 215, 0],
        font_name="NotoSansDevanagari-Bold.ttf"
    )
    print("Overlay created:", overlay)
