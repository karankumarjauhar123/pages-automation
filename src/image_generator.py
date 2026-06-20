import os
import json
import base64
import requests
import time
import urllib.parse
from io import BytesIO
from PIL import Image
from dotenv import load_dotenv

load_dotenv()

class ImageGenerator:
    def __init__(self, api_key=None, model="black-forest-labs/flux-1-dev"):
        """
        Initialize the Image Generator using NVIDIA NIM API.
        Default model: black-forest-labs/flux-1-dev
        """
        self.api_key = api_key or os.getenv("NVIDIA_API_KEY")
        if not self.api_key or self.api_key == "your_nvidia_api_key_here":
            print("WARNING: NVIDIA_API_KEY is not set or placeholder. Will default to Pollinations.ai for image generation.")
            self.api_key = None
        
        self.model = model
        # Select the correct endpoint based on the model
        if self.api_key:
            if "flux" in model.lower():
                self.invoke_url = "https://ai.api.nvidia.com/v1/genai/black-forest-labs/flux.1-dev"
            elif "stable-diffusion" in model.lower():
                self.invoke_url = "https://ai.api.nvidia.com/v1/genai/stabilityai/stable-diffusion-3-5-large"
            else:
                self.invoke_url = f"https://ai.api.nvidia.com/v1/genai/{model}"

    def _generate_via_pollinations(self, prompt, output_path, width, height):
        """
        Fallback generator using Pollinations.ai (Free, keyless, and unlimited).
        Uses the high-quality Flux model.
        """
        print(f"Generating image via Pollinations.ai... Prompt: '{prompt[:60]}...'")
        encoded_prompt = urllib.parse.quote(prompt)
        seed = int(time.time()) % 1000000
        # Pollinations image URL structure
        pollinations_url = f"https://image.pollinations.ai/p/{encoded_prompt}?width={width}&height={height}&seed={seed}&model=flux&nologo=true"
        
        for attempt in range(3):
            try:
                response = requests.get(pollinations_url, timeout=90)
                if response.status_code == 200:
                    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
                    with open(output_path, "wb") as f:
                        f.write(response.content)
                    # Verify it's a valid image
                    try:
                        with Image.open(output_path) as img:
                            img.verify()
                        print(f"Successfully generated and saved Pollinations image to: {output_path}")
                        return True
                    except Exception as img_err:
                        print(f"Downloaded file is not a valid image: {img_err}")
                else:
                    print(f"Pollinations attempt {attempt + 1} failed with status code: {response.status_code}")
            except Exception as e:
                print(f"Error during Pollinations image generation (Attempt {attempt + 1}/3): {e}")
            time.sleep(3)
        return False

    def generate_image(self, prompt, output_path, aspect_ratio="9:16", model=None, retries=3, timeout=120):
        """
        Generates an image from prompt and saves it to output_path.
        Attempts NVIDIA NIM API if key is present, and automatically falls back to Pollinations.ai on failure.
        """
        model_to_use = model or self.model
        
        # Determine width and height based on aspect ratio
        if aspect_ratio == "9:16":
            width, height = 768, 1344  # Allowed vertical resolution close to 9:16 for FLUX
        elif aspect_ratio == "16:9":
            width, height = 1344, 768  # Allowed landscape resolution close to 16:9 for FLUX
        elif aspect_ratio == "1:1":
            width, height = 1024, 1024
        else:
            width, height = 1024, 1024

        # 1. Try NVIDIA NIM API if key is available
        if self.api_key and self.api_key != "your_nvidia_api_key_here":
            if "flux" in model_to_use.lower():
                invoke_url = "https://ai.api.nvidia.com/v1/genai/black-forest-labs/flux.1-dev"
            elif "stable-diffusion" in model_to_use.lower():
                invoke_url = "https://ai.api.nvidia.com/v1/genai/stabilityai/stable-diffusion-3-5-large"
            else:
                invoke_url = f"https://ai.api.nvidia.com/v1/genai/{model_to_use}"

            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            }

            payload = {
                "prompt": prompt,
                "width": width,
                "height": height,
                "steps": 25,
                "seed": int(time.time()) % 1000000
            }

            print(f"Generating image with model '{model_to_use}' via NVIDIA NIM... Prompt: '{prompt[:60]}...'")

            for attempt in range(retries):
                try:
                    response = requests.post(invoke_url, headers=headers, json=payload, timeout=timeout)
                    
                    if response.status_code != 200:
                        print(f"NVIDIA Attempt {attempt + 1} failed. Code {response.status_code}: {response.text}")
                        if attempt < retries - 1:
                            time.sleep(5)
                            continue
                        response.raise_for_status()

                    response_body = response.json()
                    image_b64 = None
                    
                    if "artifacts" in response_body and len(response_body["artifacts"]) > 0:
                        image_b64 = response_body["artifacts"][0].get("base64")
                    elif "data" in response_body:
                        data_val = response_body["data"]
                        if isinstance(data_val, list) and len(data_val) > 0:
                            image_b64 = data_val[0].get("b64_json") or data_val[0].get("base64")
                        elif isinstance(data_val, str):
                            image_b64 = data_val
                    elif "image" in response_body:
                        image_b64 = response_body["image"]

                    if not image_b64:
                        raise ValueError(f"Could not find base64 image data in response keys: {list(response_body.keys())}")

                    if "," in image_b64:
                        image_b64 = image_b64.split(",")[1]

                    image_bytes = base64.b64decode(image_b64)
                    img = Image.open(BytesIO(image_bytes))
                    
                    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
                    img.save(output_path, "PNG")
                    print(f"Successfully saved generated image to: {output_path}")
                    return True

                except Exception as e:
                    print(f"Error during NVIDIA image generation (Attempt {attempt + 1}/{retries}): {e}")
                    if attempt < retries - 1:
                        time.sleep(5)
            
            print("NVIDIA image generation failed. Falling back to Pollinations.ai...")

        else:
            print("NVIDIA API key not configured. Using Pollinations.ai directly...")

        # 2. Fallback to Pollinations.ai
        return self._generate_via_pollinations(prompt, output_path, width, height)
