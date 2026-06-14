import os
import json
import random
import time
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

# ──────────────────────────────────────────────────────────────
# DIVERSITY POOLS — Every run randomly picks one from each pool
# to guarantee maximum variety across consecutive generations.
# ──────────────────────────────────────────────────────────────

VISUAL_STYLES = [
    "Moody cinematic photography (35mm lens, high contrast, dramatic shadows, realistic skin textures)",
    "Ancient historical oil painting (Chiaroscuro style, warm candle lighting, deep classical textures, Renaissance era)",
    "Mystical dark fantasy digital art (surreal landscapes, glowing particles, deep purples and blues, ethereal fog)",
    "Modern minimalist editorial concept (clean pastel backgrounds, sharp focus, high-fashion aesthetic, studio lighting)",
    "Gritty street photography (neon lights, reflections in rain puddles, raw and atmospheric, urban night)",
    "Vintage retro film look (faded warm colors, light leaks, 1970s film grain, soft bokeh)",
    "Epic dramatic digital art (dynamic action poses, volumetric god-rays, rich saturated color palette)",
    "Japanese anime illustration style (expressive eyes, vibrant colors, clean line art, dynamic composition)",
    "Watercolor painting (soft blending, wet-on-wet technique, delicate textures, dreamlike atmosphere)",
    "Cyberpunk neon futuristic (holographic displays, glowing circuits, dark cityscape, electric blue and pink)",
    "Photorealistic 3D render (Unreal Engine 5, subsurface scattering, ray tracing, hyper-detailed textures)",
    "Ink wash / Sumi-e art (monochrome black ink, brush strokes visible, zen minimalism, Asian aesthetic)",
]

FOCUS_THEMES_VIDEO = [
    "Unspoken rules of social dynamics (reading between the lines, body language secrets)",
    "The power of silence and mystery (why talking less makes you more powerful)",
    "Spotting hidden manipulation (identifying fake friends, gaslighting signs, dark psychology defense)",
    "Ego vs. Self-respect (knowing when to walk away, setting boundaries without guilt)",
    "Mindset shifts for success (overcoming laziness, dopamine detox, discipline over motivation)",
    "Dealing with difficult emotions (stoic advice, control your reaction, letting go of anger)",
    "Love and relationship psychological facts (what attracts people, subtle signs of interest)",
    "Subconscious brain hacks (how to study better, memory tricks, sleeping hacks, focus methods)",
    "How to handle disrespect (calm confidence, psychological reverse psychology hacks)",
    "The psychology of first impressions (how to be unforgettable in the first 7 seconds)",
    "Money mindset and wealth psychology (how rich people think differently, abundance vs. scarcity)",
    "The art of reading people instantly (micro-expressions, eye movement, voice tone analysis)",
    "Loneliness and self-growth (why being alone is your superpower, solitude vs. isolation)",
    "Overcoming fear and anxiety (rewiring your brain, exposure therapy basics, courage hacks)",
    "Power dynamics in conversations (who controls the frame, leading vs. following in dialogue)",
    "The science of habits and addiction (dopamine loops, habit stacking, breaking bad patterns)",
    "Emotional intelligence secrets (understanding others' emotions before they speak)",
    "Signs of a highly intelligent person (unconventional markers of genius, quiet intelligence)",
]

FOCUS_THEMES_IMAGE = [
    "A rare, deep life lesson or wisdom rule that 99% of people learn too late",
    "A shocking psychological human behavior secret backed by science",
    "A critical self-respect or stoic rule for modern life",
    "A dark psychology manipulation warning sign everyone should recognize",
    "A powerful relationship or attraction fact that changes perspective",
    "A mindset shift for focus, study, or success that top performers use",
    "A counterintuitive truth about money, wealth, or financial psychology",
    "A forgotten ancient wisdom quote applied to modern life challenges",
    "A body language secret that reveals hidden intentions",
    "An emotional intelligence rule for handling toxic people",
    "A discipline hack used by elite athletes and CEOs",
    "A philosophical paradox that makes people rethink their life choices",
]

NARRATIVE_TONES = [
    "Suspenseful and mysterious (build tension, reveal at the end, dark undertone)",
    "Motivational and empowering (uplifting energy, inspire action, warrior mindset)",
    "Dark and thought-provoking (uncomfortable truths, raw honesty, wake-up call)",
    "Calm and wise (sage-like delivery, peaceful authority, stoic philosopher vibe)",
    "Urgent and confrontational (challenge the viewer, break their comfort zone, direct)",
    "Storytelling and narrative (tell a mini-story or parable, then reveal the lesson)",
    "Educational and analytical (explain why something works, cite psychology, be the teacher)",
]

HOOK_STYLES = [
    "Start with a provocative question that makes the viewer stop scrolling",
    "Open with a shocking statistic or little-known fact",
    "Begin with a bold controversial statement that challenges common beliefs",
    "Start with an emotional scenario the viewer can deeply relate to",
    "Open with a mysterious incomplete sentence that creates curiosity",
    "Begin with a direct command or challenge to the viewer",
]

CAPTION_STYLES = [
    "Storytelling format — start with a mini-story, end with the lesson and a question for the audience",
    "List format — present 3-5 key takeaways as bullet points with emojis",
    "Question-driven — ask 2-3 thought-provoking questions that spark comments",
    "Call-to-action — end with a strong CTA like 'Save this for later', 'Tag someone who needs this'",
    "Controversial take — start with an unpopular opinion, then defend it with logic",
]


def _load_recent_titles(page_name=None, max_titles=20):
    """
    Reads docs/history.json and returns a list of recent video/post titles
    so the AI can explicitly avoid repeating them.
    """
    history_path = os.path.join("docs", "history.json")
    if not os.path.exists(history_path):
        return []
    try:
        with open(history_path, "r", encoding="utf-8") as f:
            history = json.load(f)
        titles = []
        for entry in history:
            if page_name and entry.get("page_name", "").lower() != page_name.lower():
                continue
            title = entry.get("title", "").strip()
            if title:
                titles.append(title)
            # Also grab caption first line as a fallback topic indicator
            caption = entry.get("caption", "").split("\n")[0].strip()
            if caption and len(caption) < 120:
                titles.append(caption)
        return titles[:max_titles]
    except Exception as e:
        print(f"Warning: Could not load history for dedup: {e}")
        return []


class ScriptGenerator:
    def __init__(self, api_key=None, model="meta/llama-3.1-70b-instruct"):
        """
        Initialize the script generator.
        Supports dual initialization of OpenRouter and NVIDIA clients for robust fallback.
        """
        self.openrouter_key = os.getenv("OPENROUTER_API_KEY")
        self.nvidia_key = api_key or os.getenv("NVIDIA_API_KEY")
        
        self.openrouter_client = None
        self.nvidia_client = None
        
        if self.openrouter_key:
            print("OpenRouter API key detected.")
            self.openrouter_client = OpenAI(
                base_url="https://openrouter.ai/api/v1",
                api_key=self.openrouter_key
            )
            
        if self.nvidia_key and self.nvidia_key != "your_nvidia_api_key_here":
            print("NVIDIA API key detected.")
            self.nvidia_client = OpenAI(
                base_url="https://integrate.api.nvidia.com/v1",
                api_key=self.nvidia_key
            )
            
        if not self.openrouter_client and not self.nvidia_client:
            raise ValueError("Neither NVIDIA_API_KEY nor OPENROUTER_API_KEY is set. Please set at least one in the .env file.")
            
        # Backward compatibility for direct access:
        self.client = self.openrouter_client or self.nvidia_client
        self.model = model if model != "meta/llama-3.1-70b-instruct" else ("meta-llama/llama-3.3-70b-instruct:free" if self.openrouter_key else "meta/llama-3.1-70b-instruct")

    def _completion_with_fallback(self, messages, model_override=None, temperature=0.7):
        """
        Calls chat completions. If using OpenRouter, it tries a list of high-benchmark 
        free models in order of priority. If a model fails with 429, it sleeps and retries.
        If all OpenRouter models fail, it falls back to NVIDIA API models if available.
        """
        # 1. Gather all candidates we want to try
        candidates = []
        
        # Add OpenRouter models if client exists
        if self.openrouter_client:
            default_free_models = [
                "meta-llama/llama-3.3-70b-instruct:free",
                "google/gemma-4-31b-it:free",
                "nousresearch/hermes-3-llama-3.1-405b:free",
                "qwen/qwen3-next-80b-a3b-instruct:free",
                "meta-llama/llama-3.2-3b-instruct:free"
            ]
            if model_override and model_override.endswith(":free"):
                or_models = [model_override] + [m for m in default_free_models if m != model_override]
            else:
                or_models = default_free_models
                
            for m in or_models:
                candidates.append({
                    "client": self.openrouter_client,
                    "model_name": m,
                    "type": "OpenRouter"
                })
                
        # Add NVIDIA models if client exists
        if self.nvidia_client:
            nvidia_models = [
                "meta/llama-3.3-70b-instruct",
                "nvidia/llama-3.1-nemotron-70b-instruct",
                "meta/llama-3.1-70b-instruct",
                "nvidia/nemotron-4-340b-instruct"
            ]
            if model_override and not model_override.endswith(":free"):
                nv_models = [model_override] + [m for m in nvidia_models if m != model_override]
            else:
                nv_models = nvidia_models
                
            for m in nv_models:
                candidates.append({
                    "client": self.nvidia_client,
                    "model_name": m,
                    "type": "NVIDIA"
                })
                
        if not candidates:
            raise ValueError("No API clients or models are configured.")

        last_error = None
        for i, candidate in enumerate(candidates):
            client = candidate["client"]
            model_name = candidate["model_name"]
            client_type = candidate["type"]
            
            # We will try each model up to 2 times, sleeping on 429
            for attempt in range(2):
                try:
                    print(f"Trying model: {model_name} ({client_type}) - Attempt {attempt + 1}...")
                    response = client.chat.completions.create(
                        model=model_name,
                        messages=messages,
                        temperature=temperature
                    )
                    print(f"✅ Success with model: {model_name} ({client_type})")
                    return response
                except Exception as e:
                    err_msg = str(e)
                    last_error = e
                    print(f"⚠️ Failed with model {model_name} ({client_type}): {err_msg}")
                    
                    # If it's a rate limit error (429), sleep for 6 seconds and retry
                    if "429" in err_msg or "rate-limited" in err_msg.lower() or "rate limit" in err_msg.lower():
                        if attempt == 0:
                            sleep_time = 6
                            print(f"Rate limited. Sleeping for {sleep_time} seconds before retrying this model...")
                            time.sleep(sleep_time)
                            continue
                    
                    # For other errors or if second attempt fails, move to the next candidate
                    break
            
            # Add a small delay between trying different models to avoid triggering IP/global limits
            if i < len(candidates) - 1:
                time.sleep(2)
        
        # If all failed, raise the last error
        raise last_error

    def _clean_json_response(self, content):
        """Strips markdown code fences from LLM responses and parses JSON."""
        content = content.strip()
        if content.startswith("```json"):
            content = content[7:]
        if content.startswith("```"):
            content = content[3:]
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()
        return json.loads(content)

    def generate_video_script(self, topic, language, model=None, page_name=None):
        """
        Generates a multi-scene video script with narration, image prompts,
        and stock video search queries. Uses randomized diversity pools and
        history-aware deduplication to ensure every script is unique.
        """
        # ── Pick random diversity parameters ──
        selected_style = random.choice(VISUAL_STYLES)
        selected_theme = random.choice(FOCUS_THEMES_VIDEO)
        selected_tone = random.choice(NARRATIVE_TONES)
        selected_hook = random.choice(HOOK_STYLES)
        selected_caption = random.choice(CAPTION_STYLES)
        random_seed = random.randint(100000, 999999)
        temperature = round(random.uniform(0.65, 0.85), 2)

        # ── Load recent history to avoid repetition ──
        recent_titles = _load_recent_titles(page_name)
        dedup_instruction = ""
        if recent_titles:
            titles_list = "\n".join(f"  - {t}" for t in recent_titles[:15])
            dedup_instruction = (
                f"\n\nCRITICAL: The following topics/titles have ALREADY been posted recently. "
                f"You MUST write about something COMPLETELY DIFFERENT. Do NOT repeat or closely paraphrase any of these:\n{titles_list}\n"
            )

        model_to_use = model or self.model
        system_prompt = (
            "You are a professional content creator and scriptwriter for viral social media videos "
            "(Facebook Reels, TikTok, YouTube Shorts).\n"
            "Your task is to write a highly engaging vertical video script based on the topic and language provided.\n"
            "You MUST respond ONLY with a raw JSON object and nothing else. Do not wrap the JSON in markdown "
            "code blocks or backticks. Ensure the JSON is completely valid."
        )

        user_prompt = (
            f"Generate a video script on the main topic: '{topic}' in language: '{language}'.\n"
            f"FOCUS SUB-THEME: '{selected_theme}' — adapt this sub-theme to naturally fit within the main topic '{topic}'. "
            "Do NOT write a generic summary. Pick ONE hyper-specific lesson, rule, or life situation.\n"
            f"NARRATIVE TONE: '{selected_tone}' — the entire narration should follow this emotional tone.\n"
            f"HOOK STYLE: '{selected_hook}' — the very first scene's narration must use this hook approach.\n"
            "The script should be optimized for a 30-50 second Reels video. It must contain 3 to 5 scenes.\n"
            "EMOTIONAL ARC: Scene 1 = grab attention with the hook. Scenes 2-3 = build tension or deliver value. "
            "Final scene = powerful punchline, twist, or call-to-action that makes the viewer save/share.\n"
            "The narration must flow naturally and sound engaging when converted to speech.\n"
            f"VISUAL STYLE: Use '{selected_style}' for ALL scene image prompts. "
            "Describe the scene visuals in rich detail in English (vertical 9:16 format). "
            "Each scene should have a DIFFERENT visual composition (close-up, wide shot, silhouette, etc.).\n"
            f"CAPTION STYLE: '{selected_caption}' — write the fb_caption following this format.\n"
            f"Unique run seed (for maximum creativity): {random_seed}.\n"
            f"{dedup_instruction}\n"
            "The JSON output MUST follow this exact schema:\n"
            "{\n"
            '  "title": "Short title of the video",\n'
            '  "hook": "Strong opening line to grab attention",\n'
            '  "scenes": [\n'
            "    {\n"
            '      "narration": "Narration text for this scene (in the requested language)",\n'
            '      "image_prompt": "Detailed visual description in English for AI image generator, vertical 9:16 aspect ratio",\n'
            '      "video_query": "A simple 2-3 word English search query for stock video clips (e.g. \'thoughtful man\', \'rainy window\', \'starry sky\'). Keep it simple and conceptual."\n'
            "    }\n"
            "  ],\n"
            '  "fb_caption": "Engaging Facebook post caption with relevant emojis and hashtags"\n'
            "}\n"
        )

        print(f"🎬 Generating script for '{topic}' in '{language}'")
        print(f"   Style: {selected_style[:40]}...")
        print(f"   Theme: {selected_theme[:40]}...")
        print(f"   Tone:  {selected_tone[:40]}...")
        print(f"   Hook:  {selected_hook[:40]}...")
        print(f"   Temp:  {temperature} | Seed: {random_seed}")
        if recent_titles:
            print(f"   Dedup: Avoiding {len(recent_titles)} recent titles")

        response = self._completion_with_fallback(
            model_override=model_to_use,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=temperature
        )

        content = response.choices[0].message.content.strip()
        try:
            return self._clean_json_response(content)
        except json.JSONDecodeError as e:
            print("Failed to parse JSON. Raw output was:")
            print(content)
            raise e

    def generate_image_post(self, topic, language, model=None, page_name=None):
        """
        Generates a single-image post with text overlay and caption.
        Uses randomized diversity pools and history-aware deduplication.
        """
        # ── Pick random diversity parameters ──
        selected_style = random.choice(VISUAL_STYLES)
        selected_theme = random.choice(FOCUS_THEMES_IMAGE)
        selected_tone = random.choice(NARRATIVE_TONES)
        selected_caption = random.choice(CAPTION_STYLES)
        random_seed = random.randint(100000, 999999)
        temperature = round(random.uniform(0.65, 0.85), 2)

        # ── Load recent history to avoid repetition ──
        recent_titles = _load_recent_titles(page_name)
        dedup_instruction = ""
        if recent_titles:
            titles_list = "\n".join(f"  - {t}" for t in recent_titles[:15])
            dedup_instruction = (
                f"\n\nCRITICAL: The following topics/captions have ALREADY been posted recently. "
                f"You MUST create something COMPLETELY DIFFERENT. Do NOT repeat or closely paraphrase any of these:\n{titles_list}\n"
            )

        model_to_use = model or self.model
        system_prompt = (
            "You are a professional social media content creator.\n"
            "Your task is to create a viral single-image post (an AI image prompt and matching overlay text "
            "+ social media caption) based on the topic and language provided.\n"
            "You MUST respond ONLY with a raw JSON object and nothing else. Do not wrap the JSON in markdown "
            "code blocks or backticks."
        )

        user_prompt = (
            f"Generate a single-image post configuration on the topic: '{topic}' in language: '{language}'.\n"
            f"FOCUS SUB-THEME: '{selected_theme}'. Do NOT write a generic summary — pick something hyper-specific.\n"
            f"TONE: '{selected_tone}' — the overlay text and caption should match this emotional energy.\n"
            f"VISUAL STYLE: Use '{selected_style}' for the image prompt. "
            "Make it highly detailed and descriptive (in English), square 1:1 format. "
            "Specify the setting, mood, and composition.\n"
            f"CAPTION STYLE: '{selected_caption}' — write the fb_caption following this format.\n"
            "The overlay text should be a short, punchy quote, fact, or tip (max 10-15 words).\n"
            f"Unique run seed: {random_seed}.\n"
            f"{dedup_instruction}\n"
            "The JSON output MUST follow this exact schema:\n"
            "{\n"
            '  "image_prompt": "Highly detailed visual description in English for FLUX image generator, 1:1 square ratio, high resolution",\n'
            '  "overlay_text": "Short punchy text to overlay on the image (max 10-15 words)",\n'
            '  "fb_caption": "Engaging Facebook post caption with relevant emojis and hashtags"\n'
            "}\n"
        )

        print(f"🖼️ Generating image post for '{topic}' in '{language}'")
        print(f"   Style: {selected_style[:40]}...")
        print(f"   Theme: {selected_theme[:40]}...")
        print(f"   Tone:  {selected_tone[:40]}...")
        print(f"   Temp:  {temperature} | Seed: {random_seed}")
        if recent_titles:
            print(f"   Dedup: Avoiding {len(recent_titles)} recent titles")

        response = self._completion_with_fallback(
            model_override=model_to_use,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=temperature
        )

        content = response.choices[0].message.content.strip()
        try:
            return self._clean_json_response(content)
        except json.JSONDecodeError as e:
            print("Failed to parse JSON. Raw output was:")
            print(content)
            raise e

