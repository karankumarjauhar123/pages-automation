import os
import asyncio
import requests
import edge_tts
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

class VoiceGenerator:
    def __init__(self):
        """
        Initialize the Voice Generator.
        Supports free Microsoft Edge TTS as primary provider, with speed/pitch controls.
        Also supports premium OpenAI and ElevenLabs TTS as optional fallbacks if API keys are set.
        """
        # Map languages to Microsoft Edge Neural TTS voices (Fixed hi-IN-SwararaNeural typo!)
        self.edge_voice_map = {
            "hindi": "hi-IN-MadhurNeural",        # Warm male Hindi voice
            "hindi_female": "hi-IN-SwaraNeural",  # Clear female Hindi voice
            "hinglish": "hi-IN-MadhurNeural",     # Hinglish sounds best with Hindi neural voices
            "indian_english": "en-IN-NeerjaNeural",        # Female Indian English (great for Hinglish!)
            "indian_english_male": "en-IN-PrabhatNeural",  # Male Indian English
            "english": "en-US-AriaNeural",        # Clean female US English voice
            "english_male": "en-US-GuyNeural"     # Clean male US English voice
        }
        
        # Initialize optional OpenAI client if API key is present
        self.openai_key = os.getenv("OPENAI_API_KEY")
        self.openai_client = None
        if self.openai_key:
            self.openai_client = OpenAI(api_key=self.openai_key)
            
        # ElevenLabs API key (optional)
        self.elevenlabs_key = os.getenv("ELEVENLABS_API_KEY")

    async def _generate_edge_tts(self, text, output_path, voice_name, rate, pitch):
        """
        Internal async function to communicate with Edge TTS and save the file.
        """
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        # Use rate and pitch parameters to make the speech sound more energetic
        communicate = edge_tts.Communicate(text, voice_name, rate=rate, pitch=pitch)
        await communicate.save(output_path)

    def _generate_openai_tts(self, text, output_path, voice, gender):
        """
        Generate voiceover using OpenAI TTS (requires OPENAI_API_KEY).
        """
        if not self.openai_client:
            raise ValueError("OPENAI_API_KEY is not set in the environment.")
            
        openai_voice = voice
        if not openai_voice:
            openai_voice = "onyx" if gender.lower() == "male" else "nova"
            
        print(f"Generating voiceover using OpenAI TTS voice '{openai_voice}'...")
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        
        response = self.openai_client.audio.speech.create(
            model="tts-1",
            voice=openai_voice,
            input=text
        )
        response.stream_to_file(output_path)
        print(f"Successfully generated OpenAI TTS voiceover at: {output_path}")

    def _generate_elevenlabs_tts(self, text, output_path, voice, gender):
        """
        Generate voiceover using ElevenLabs TTS API (requires ELEVENLABS_API_KEY).
        """
        if not self.elevenlabs_key:
            raise ValueError("ELEVENLABS_API_KEY is not set in the environment.")
            
        voice_id = voice
        if not voice_id:
            voice_id = "pNInz6obpgfrhhF21HLc" if gender.lower() == "male" else "21m00Tcm4TlvDq8ikWAM"
            
        print(f"Generating voiceover using ElevenLabs TTS voice '{voice_id}'...")
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        
        headers = {
            "xi-api-key": self.elevenlabs_key,
            "Content-Type": "application/json"
        }
        data = {
            "text": text,
            "model_id": "eleven_multilingual_v2",
            "voice_settings": {
                "stability": 0.5,
                "similarity_boost": 0.75
            }
        }
        
        response = requests.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}", 
            json=data, 
            headers=headers
        )
        
        if response.status_code != 200:
            raise Exception(f"ElevenLabs API failed: {response.text}")
            
        with open(output_path, "wb") as f:
            f.write(response.content)
        print(f"Successfully generated ElevenLabs TTS voiceover at: {output_path}")

    def generate_voice(self, text, output_path, language="hinglish", gender="male", voice=None, provider=None, rate=None, pitch=None):
        """
        Generate the voiceover audio using the selected provider (defaults to free Edge TTS).
        """
        # Determine provider automatically based on keys if not specified
        if not provider:
            if self.elevenlabs_key:
                provider = "elevenlabs"
            elif self.openai_key:
                provider = "openai"
            else:
                provider = "edge"
                
        provider = provider.lower()
        print(f"Voice generation provider: '{provider}'")
        print(f"Text to speak: '{text[:80]}...'")
        
        try:
            if provider == "elevenlabs":
                self._generate_elevenlabs_tts(text, output_path, voice, gender)
                return True
            elif provider == "openai":
                self._generate_openai_tts(text, output_path, voice, gender)
                return True
            else:
                # Default to completely free Edge TTS
                voice_name = voice
                if not voice_name:
                    voice_key = language.lower()
                    if voice_key == "hindi" and gender.lower() == "female":
                        voice_key = "hindi_female"
                    elif voice_key == "english" and gender.lower() == "male":
                        voice_key = "english_male"
                    elif voice_key == "indian_english" and gender.lower() == "male":
                        voice_key = "indian_english_male"
                        
                    voice_name = self.edge_voice_map.get(voice_key, self.edge_voice_map["hinglish"])
                
                # Dynamic defaults for rate to make free voices sound natural & conversational
                if not rate:
                    if "hindi" in language.lower() or "hinglish" in language.lower():
                        rate = "+10%"  # Speed up slow Microsoft Hindi voice
                    else:
                        rate = "+5%"   # Speed up English voice slightly
                        
                if not pitch:
                    pitch = "+0Hz"
                    
                print(f"Generating voiceover using Edge TTS voice '{voice_name}' (Rate: {rate}, Pitch: {pitch})...")
                asyncio.run(self._generate_edge_tts(text, output_path, voice_name, rate, pitch))
                print(f"Successfully generated Edge TTS voiceover at: {output_path}")
                return True
                
        except Exception as e:
            print(f"❌ Error generating voiceover with provider '{provider}': {e}")
            
            # Fallback to Edge TTS if premium providers fail
            if provider != "edge":
                print("Attempting fallback to free Edge TTS...")
                try:
                    voice_name = self.edge_voice_map.get(language.lower(), self.edge_voice_map["hinglish"])
                    rate = "+10%" if ("hindi" in language.lower() or "hinglish" in language.lower()) else "+5%"
                    asyncio.run(self._generate_edge_tts(text, output_path, voice_name, rate, "+0Hz"))
                    print("Fallback Edge TTS voiceover generated successfully.")
                    return True
                except Exception as fallback_err:
                    print(f"Fallback Edge TTS voiceover also failed: {fallback_err}")
            raise e
