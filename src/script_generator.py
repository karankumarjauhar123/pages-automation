import os
import json
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

class ScriptGenerator:
    def __init__(self, api_key=None, model="meta/llama-3.1-70b-instruct"):
        """
        Initialize the script generator.
        Default model: meta/llama-3.1-70b-instruct.
        """
        self.openrouter_key = os.getenv("OPENROUTER_API_KEY")
        if self.openrouter_key:
            print("Using OpenRouter for Script Generation.")
            self.client = OpenAI(
                base_url="https://openrouter.ai/api/v1",
                api_key=self.openrouter_key
            )
            # Default model for OpenRouter if not specified
            self.model = model if model != "meta/llama-3.1-70b-instruct" else "meta-llama/llama-3.1-8b-instruct:free"
        else:
            self.api_key = api_key or os.getenv("NVIDIA_API_KEY")
            if not self.api_key or self.api_key == "your_nvidia_api_key_here":
                raise ValueError("NVIDIA_API_KEY or OPENROUTER_API_KEY is not set. Please set it in the .env file.")
            
            self.client = OpenAI(
                base_url="https://integrate.api.nvidia.com/v1",
                api_key=self.api_key
            )
            self.model = model

    def generate_video_script(self, topic, language, model=None):
        """
        Generates a multi-scene video script with narration and image prompts.
        """
        model_to_use = model or self.model
        system_prompt = (
            "You are a professional content creator and scriptwriter for viral social media videos (Facebook Reels, TikTok, YouTube Shorts).\n"
            "Your task is to write a highly engaging vertical video script based on the topic and language provided.\n"
            "You MUST respond ONLY with a raw JSON object and nothing else. Do not wrap the JSON in markdown code blocks or backticks. "
            "Ensure the JSON is completely valid."
        )

        user_prompt = (
            f"Generate a video script on the topic: '{topic}' in language: '{language}'.\n"
            "The script should be optimized for a 30-50 second Reels video. It must contain 3 to 5 scenes.\n"
            "The narration must flow naturally and sound engaging when converted to speech.\n"
            "The first scene must have a powerful hook (first 3 seconds).\n"
            "The visual prompts for each scene will be sent to an AI Image Generator (Flux), so describe them in detail in English. Specify style (e.g., 'photorealistic', 'cinematic lighting', 'dramatic digital art'), subject, colors, and vertical framing (9:16).\n\n"
            "The JSON output MUST follow this exact schema:\n"
            "{\n"
            '  "title": "Short title of the video",\n'
            '  "hook": "Strong opening line to grab attention",\n'
            '  "scenes": [\n'
            "    {\n"
            '      "narration": "Narration text for this scene (in the requested language)",\n'
            '      "image_prompt": "Detailed visual description in English for AI image generator, vertical 9:16 aspect ratio"\n'
            "    }\n"
            "  ],\n"
            '  "fb_caption": "Engaging Facebook post caption with relevant emojis and hashtags"\n'
            "}\n"
        )

        print(f"Generating script for topic: '{topic}' in '{language}' using model '{model_to_use}'...")
        response = self.client.chat.completions.create(
            model=model_to_use,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.7
        )

        content = response.choices[0].message.content.strip()
        
        # Clean up code blocks if present
        if content.startswith("```json"):
            content = content[7:]
        if content.startswith("```"):
            content = content[3:]
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()

        try:
            return json.loads(content)
        except json.JSONDecodeError as e:
            print("Failed to parse JSON. Raw output was:")
            print(content)
            raise e

    def generate_image_post(self, topic, language, model=None):
        """
        Generates a single-image post with text overlay and caption.
        """
        model_to_use = model or self.model
        system_prompt = (
            "You are a professional social media content creator.\n"
            "Your task is to create a viral single-image post (an AI image prompt and matching overlay text + social media caption) based on the topic and language provided.\n"
            "You MUST respond ONLY with a raw JSON object and nothing else. Do not wrap the JSON in markdown code blocks or backticks."
        )

        user_prompt = (
            f"Generate a single-image post configuration on the topic: '{topic}' in language: '{language}'.\n"
            "The visual prompt will be used with FLUX image generator, so make it highly detailed and descriptive (in English). Specify the style, setting, and mood.\n"
            "The overlay text should be a short, punchy quote, fact, or tip that will be written directly on the image.\n\n"
            "The JSON output MUST follow this exact schema:\n"
            "{\n"
            '  "image_prompt": "Highly detailed visual description in English for FLUX image generator, 1:1 square ratio, high resolution",\n'
            '  "overlay_text": "Short punchy text to overlay on the image (max 10-15 words)",\n'
            '  "fb_caption": "Engaging Facebook post caption with relevant emojis and hashtags"\n'
            "}\n"
        )

        print(f"Generating image post content for topic: '{topic}' in '{language}' using model '{model_to_use}'...")
        response = self.client.chat.completions.create(
            model=model_to_use,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.7
        )

        content = response.choices[0].message.content.strip()
        
        if content.startswith("```json"):
            content = content[7:]
        if content.startswith("```"):
            content = content[3:]
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()

        try:
            return json.loads(content)
        except json.JSONDecodeError as e:
            print("Failed to parse JSON. Raw output was:")
            print(content)
            raise e
