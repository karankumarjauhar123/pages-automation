import os
import json
import base64
import requests
import time
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
            raise ValueError("NVIDIA_API_KEY is not set. Please set it in the .env file.")
        
        self.model = model
        # Select the correct endpoint based on the model
        if "flux" in model.lower():
            self.invoke_url = "https://ai.api.nvidia.com/v1/genai/black-forest-labs/flux.1-dev"
        elif "stable-diffusion" in model.lower():
            self.invoke_url = "https://ai.api.nvidia.com/v1/genai/stabilityai/stable-diffusion-3-5-large"
        else:
            self.invoke_url = f"https://ai.api.nvidia.com/v1/genai/{model}"

    def generate_image(self, prompt, output_path, aspect_ratio="9:16", model=None, retries=3, timeout=120):
        """
        Generates an image from prompt and saves it to output_path.
        Supports 9:16 vertical ratio for video scenes, and 1:1 square for standard posts.
        """
        model_to_use = model or self.model
        
        # Select the correct endpoint based on the model
        if "flux" in model_to_use.lower():
            invoke_url = "https://ai.api.nvidia.com/v1/genai/black-forest-labs/flux.1-dev"
        elif "stable-diffusion" in model_to_use.lower():
            invoke_url = "https://ai.api.nvidia.com/v1/genai/stabilityai/stable-diffusion-3-5-large"
        else:
            invoke_url = f"https://ai.api.nvidia.com/v1/genai/{model_to_use}"

        # Determine width and height based on aspect ratio
        if aspect_ratio == "9:16":
            width, height = 768, 1344  # Allowed vertical resolution close to 9:16 for FLUX
        elif aspect_ratio == "16:9":
            width, height = 1344, 768  # Allowed landscape resolution close to 16:9 for FLUX
        elif aspect_ratio == "1:1":
            width, height = 1024, 1024
        else:
            width, height = 1024, 1024

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

        # Payload standard structure
        payload = {
            "prompt": prompt,
            "width": width,
            "height": height,
            "steps": 25,  # Balanced for speed and quality
            "seed": int(time.time()) % 1000000
        }

        print(f"Generating image with model '{model_to_use}'... Prompt: '{prompt[:60]}...'")

        for attempt in range(retries):
            try:
                response = requests.post(invoke_url, headers=headers, json=payload, timeout=timeout)
                
                if response.status_code != 200:
                    print(f"Attempt {attempt + 1} failed. Code {response.status_code}: {response.text}")
                    if attempt < retries - 1:
                        time.sleep(5)
                        continue
                    response.raise_for_status()

                response_body = response.json()
                
                # Robust extraction of base64 image data
                image_b64 = None
                
                # Check for standard NVIDIA NIM artifacts structure
                if "artifacts" in response_body and len(response_body["artifacts"]) > 0:
                    image_b64 = response_body["artifacts"][0].get("base64")
                # Check for direct 'data' field being a base64 string
                elif "data" in response_body:
                    data_val = response_body["data"]
                    if isinstance(data_val, list) and len(data_val) > 0:
                        image_b64 = data_val[0].get("b64_json") or data_val[0].get("base64")
                    elif isinstance(data_val, str):
                        image_b64 = data_val
                # Check for direct 'image' field
                elif "image" in response_body:
                    image_b64 = response_body["image"]

                if not image_b64:
                    raise ValueError(f"Could not find base64 image data in response keys: {list(response_body.keys())}")

                # If there's a prefix like "data:image/png;base64,", strip it
                if "," in image_b64:
                    image_b64 = image_b64.split(",")[1]

                # Decode base64 and save as image file
                image_bytes = base64.b64decode(image_b64)
                img = Image.open(BytesIO(image_bytes))
                
                # Ensure directories exist
                os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
                img.save(output_path, "PNG")
                print(f"Successfully saved generated image to: {output_path}")
                return True

            except Exception as e:
                print(f"Error during image generation (Attempt {attempt + 1}/{retries}): {e}")
                if attempt < retries - 1:
                    time.sleep(5)
                else:
                    raise e
        return False
