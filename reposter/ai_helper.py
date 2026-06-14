import os
import json
import random
import time
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

class AIHelper:
    def __init__(self, api_key=None, model="meta/llama-3.1-70b-instruct"):
        """
        Initialize the AI helper for the reposter.
        Reuses fallback logic to try OpenRouter first, then NVIDIA.
        """
        self.openrouter_key = os.getenv("OPENROUTER_API_KEY")
        self.nvidia_key = api_key or os.getenv("NVIDIA_API_KEY")
        
        self.openrouter_client = None
        self.nvidia_client = None
        
        if self.openrouter_key:
            self.openrouter_client = OpenAI(
                base_url="https://openrouter.ai/api/v1",
                api_key=self.openrouter_key
            )
            
        if self.nvidia_key and self.nvidia_key != "your_nvidia_api_key_here":
            self.nvidia_client = OpenAI(
                base_url="https://integrate.api.nvidia.com/v1",
                api_key=self.nvidia_key
            )
            
        # Backward compatibility for direct access:
        self.client = self.openrouter_client or self.nvidia_client
        self.model = model if model != "meta/llama-3.1-70b-instruct" else ("meta-llama/llama-3.3-70b-instruct:free" if self.openrouter_key else "meta/llama-3.1-70b-instruct")

    def _completion_with_fallback(self, messages, model_override=None, temperature=0.75):
        """
        Calls chat completions. If using OpenRouter, it tries a list of high-benchmark 
        free models. If a model fails with 429, it sleeps and retries.
        If all OpenRouter models fail, it falls back to NVIDIA API models if available.
        """
        candidates = []
        
        if self.openrouter_client:
            default_free_models = [
                "meta-llama/llama-3.3-70b-instruct:free",
                "google/gemma-2-9b-it:free",
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
                
        if self.nvidia_client:
            nvidia_models = [
                "meta/llama-3.3-70b-instruct",
                "nvidia/llama-3.1-nemotron-70b-instruct",
                "meta/llama-3.1-70b-instruct",
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
            
            for attempt in range(2):
                try:
                    print(f"[AIHelper] Trying model: {model_name} ({client_type}) - Attempt {attempt + 1}...")
                    response = client.chat.completions.create(
                        model=model_name,
                        messages=messages,
                        temperature=temperature
                    )
                    print(f"[AIHelper] ✅ Success with model: {model_name} ({client_type})")
                    return response
                except Exception as e:
                    err_msg = str(e)
                    last_error = e
                    print(f"[AIHelper] ⚠️ Failed with model {model_name} ({client_type}): {err_msg}")
                    
                    if "429" in err_msg or "rate-limited" in err_msg.lower() or "rate limit" in err_msg.lower():
                        if attempt == 0:
                            sleep_time = 6
                            print(f"[AIHelper] Rate limited. Sleeping for {sleep_time} seconds before retrying...")
                            time.sleep(sleep_time)
                            continue
                    break
            
            if i < len(candidates) - 1:
                time.sleep(2)
        
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

    def generate_repost_metadata(self, original_title, page_name, language, topic, original_description=""):
        """
        Generates AI-powered viral caption, top banner hook, and bottom banner CTA.
        Uses translation/adaptation guidelines for Hinglish (Devnagari script).
        """
        # Formulate instructions based on language
        lang_instruction = ""
        example_json = ""
        
        if "hinglish" in language.lower() or "hindi" in language.lower():
            lang_instruction = (
                "LANGUAGE RULE:\n"
                "1. For 'fb_caption', you must write in a conversational Hinglish (Hindi/English mix) using Devnagari script (Hindi alphabet).\n"
                "   Example: 'ये बातें आपका दिमाग घुमा देंगी! 🧠 क्या आप सहमत हैं? कमेंट में बताएं! 👇'\n"
                "2. For 'banner_hook', write a super catchy short title in Hindi/Hinglish using Devnagari script (max 30 characters).\n"
                "   Example: 'ये गलतियां मत करना ❌' or 'सच्ची बातें 💯'\n"
                "3. For 'banner_cta', write a short call-to-action in Hindi/Hinglish using Devnagari script (max 25 characters).\n"
                "   Example: 'रोज नया सीखें! 🔥' or 'फॉलो करना न भूलें! 👇'"
            )
            example_json = (
                "{\n"
                '  "fb_caption": "ये Psychology Tricks आपकी जिंदगी बदल देंगी! 🧠 क्या आपने कभी इसे आजमाया है? कमेंट में बताएं! 👇 #PsychologyFacts #HindiMotivation #ChanakyaNiti",\n'
                '  "banner_hook": "ये Tricks बदल देंगी जिंदगी 🧠",\n'
                '  "banner_cta": "फॉलो करो और स्मार्ट बनो 🔥"\n'
                "}"
            )
        else:
            lang_instruction = (
                "LANGUAGE RULE:\n"
                "1. For 'fb_caption', you must write in highly engaging conversational English.\n"
                "2. For 'banner_hook', write a catchy, short title in English (max 30 characters).\n"
                "3. For 'banner_cta', write a short CTA in English (max 25 characters)."
            )
            example_json = (
                "{\n"
                '  "fb_caption": "These 5 psychological tricks will change how you view people! 🧠 Which one shocked you the most? Drop a comment below! 👇 #PsychologyFacts #MindHacks #SuccessTips",\n'
                '  "banner_hook": "5 Psychology Tricks 🧠",\n'
                '  "banner_cta": "Save this for later! 🔥"\n'
                "}"
            )

        system_prompt = (
            "You are a professional social media manager and growth expert specialized in viral reels.\n"
            "Your task is to analyze the original video's title and description, and generate highly engaging assets (Facebook Caption, Top Banner Hook, Bottom Banner CTA) optimized for virality.\n"
            "You MUST respond ONLY with a raw JSON object and nothing else. Do not wrap the JSON in markdown code blocks or backticks."
        )

        user_prompt = (
            f"Page Name: '{page_name}'\n"
            f"Niche Topic: '{topic}'\n"
            f"Original Video Title: '{original_title}'\n"
            f"Original Description: '{original_description}'\n\n"
            f"{lang_instruction}\n\n"
            f"GUIDELINES:\n"
            f"- Caption should include a strong hook (first line), a question to drive comments, and 3-5 trending relevant hashtags.\n"
            f"- Banner Hook must be short, punchy, and make scroll-stoppers stop (max 30 chars). It will be printed at the top of the video.\n"
            f"- Banner CTA must encourage engagement or following (max 25 chars). It will be printed at the bottom of the video.\n"
            f"- Do NOT use the exact same title as original. Re-phrase it to be much more dramatic and viral.\n\n"
            f"You must return a valid JSON object matching this schema:\n"
            f"{example_json}"
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]

        try:
            response = self._completion_with_fallback(messages)
            content = response.choices[0].message.content
            parsed = self._clean_json_response(content)
            
            # Basic validation
            if "fb_caption" in parsed and "banner_hook" in parsed and "banner_cta" in parsed:
                return parsed
            else:
                raise ValueError("Parsed JSON missing required keys")
                
        except Exception as e:
            print(f"[AIHelper] ⚠️ Error generating AI metadata, using fallback: {e}")
            # Safe Fallback
            if "hinglish" in language.lower() or "hindi" in language.lower():
                return {
                    "fb_caption": f"क्या आप इससे सहमत हैं? 💯 कमेंट में बताएं! 👇 \n\n#reels #viral #motivation #wisdom",
                    "banner_hook": "सच्ची बातें 🧠",
                    "banner_cta": "फॉलो करना न भूलें! 🔥"
                }
            else:
                return {
                    "fb_caption": f"Watch until the end! 🔥 What do you think about this? Let me know in the comments! 👇 \n\n#reels #viral #trending #mindset",
                    "banner_hook": "Wait For It... 🧠",
                    "banner_cta": "Follow for more! 🔥"
                }

if __name__ == "__main__":
    # Test script if run directly
    helper = AIHelper()
    res = helper.generate_repost_metadata(
        original_title="3 signs of fake friends that you should ignore",
        page_name="mindhack",
        language="English",
        topic="Psychology facts"
    )
    print("English Result:", json.dumps(res, indent=2, ensure_ascii=False))
    
    res_hin = helper.generate_repost_metadata(
        original_title="Why you should never share your secrets with anyone",
        page_name="Chanakya Niti",
        language="Hinglish",
        topic="Chanakya Niti wisdom"
    )
    print("Hinglish Result:", json.dumps(res_hin, indent=2, ensure_ascii=False))
