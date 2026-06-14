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
            self.model = model if model != "meta/llama-3.1-70b-instruct" else "meta-llama/llama-3.3-70b-instruct:free"
        else:
            self.api_key = api_key or os.getenv("NVIDIA_API_KEY")
            if not self.api_key or self.api_key == "your_nvidia_api_key_here":
                raise ValueError("NVIDIA_API_KEY or OPENROUTER_API_KEY is not set. Please set it in the .env file.")
            
            self.client = OpenAI(
                base_url="https://integrate.api.nvidia.com/v1",
                api_key=self.api_key
            )
            self.model = model
            
    def _completion_with_fallback(self, messages, model_override=None, temperature=0.7):
        """
        Calls chat completions. If using OpenRouter, it tries a list of high-benchmark 
        free models in order of priority if one fails (due to rate limits, server errors, etc.).
        """
        # Determine the initial model list
        if self.openrouter_key:
            # Priority list of best benchmarked free models on OpenRouter
            default_free_models = [
                "meta-llama/llama-3.3-70b-instruct:free",
                "google/gemma-4-31b-it:free",
                "nousresearch/hermes-3-llama-3.1-405b:free",
                "qwen/qwen3-next-80b-a3b-instruct:free",
                "meta-llama/llama-3.2-3b-instruct:free"
            ]
            
            if model_override:
                # If user specified a model (e.g. override), try it first, then fall back to defaults
                models_to_try = [model_override] + [m for m in default_free_models if m != model_override]
            else:
                models_to_try = default_free_models
        else:
            # For NVIDIA API, use the specified model or fallback to default
            models_to_try = [model_override or self.model]

        last_error = None
        for model_name in models_to_try:
            try:
                print(f"Trying model: {model_name}...")
                response = self.client.chat.completions.create(
                    model=model_name,
                    messages=messages,
                    temperature=temperature
                )
                print(f"✅ Success with model: {model_name}")
                return response
            except Exception as e:
                print(f"⚠️ Failed with model {model_name}: {str(e)}")
                last_error = e
                # Continue to next model
                continue
        
        # If all failed, raise the last error
        raise last_error


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
            "To ensure variety, choose a highly specific, unique angle, sub-topic, or lesson under the main theme (do not just generate a generic summary). "
            "For example, pick a single specific quote or one exact life situation (like dealing with fake friends, achieving success through silence, etc.).\n"
            "The script should be optimized for a 30-50 second Reels video. It must contain 3 to 5 scenes.\n"
            "The narration must flow naturally and sound engaging when converted to speech.\n"
            "The first scene must have a powerful hook (first 3 seconds).\n"
            "The visual prompts for each scene will be sent to an AI Image Generator (Flux), so describe them in detail in English. "
            "For this video, select a specific artistic style for all scenes (e.g. choose one of: realistic photography, historical ancient oil painting, moody dark fantasy, or dramatic digital art) so the visuals look cohesive across this video but unique compared to other runs. Use vertical framing (9:16).\n\n"
            "The JSON output MUST follow this exact schema:\n"
            "{\n"
            '  "title": "Short title of the video",\n'
            '  "hook": "Strong opening line to grab attention",\n'
            '  "scenes": [\n'
            "    {\n"
            '      "narration": "Narration text for this scene (in the requested language)",\n'
            '      "image_prompt": "Detailed visual description in English for AI image generator, vertical 9:16 aspect ratio",\n'
            '      "video_query": "A simple 2-3 word English search query for stock video clips representing this scene (e.g. \'thoughtful man\', \'stressed student\', \'meditation forest\'). Keep it simple, common, and conceptual to ensure high search success on stock video sites."\n'
            "    }\n"
            "  ],\n"
            '  "fb_caption": "Engaging Facebook post caption with relevant emojis and hashtags"\n'
            "}\n"
        )

        print(f"Generating script for topic: '{topic}' in '{language}'...")
        response = self._completion_with_fallback(
            model_override=model_to_use,
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
            "To ensure variety, choose a highly specific, unique quote, tip, or lesson under the main theme (do not just generate a generic summary).\n"
            "The visual prompt will be used with FLUX image generator, so make it highly detailed and descriptive (in English). Select a unique visual style (e.g., realistic photography, historical oil painting, minimalist concept art, or dramatic digital art) to keep it fresh and engaging. Specify the style, setting, and mood.\n"
            "The overlay text should be a short, punchy quote, fact, or tip that will be written directly on the image.\n\n"
            "The JSON output MUST follow this exact schema:\n"
            "{\n"
            '  "image_prompt": "Highly detailed visual description in English for FLUX image generator, 1:1 square ratio, high resolution",\n'
            '  "overlay_text": "Short punchy text to overlay on the image (max 10-15 words)",\n'
            '  "fb_caption": "Engaging Facebook post caption with relevant emojis and hashtags"\n'
            "}\n"
        )

        print(f"Generating image post content for topic: '{topic}' in '{language}'...")
        response = self._completion_with_fallback(
            model_override=model_to_use,
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
