import os
import asyncio
import edge_tts
from dotenv import load_dotenv

load_dotenv()

class VoiceGenerator:
    def __init__(self):
        """
        Initialize the Voice Generator.
        Supports realistic, natural-sounding voices for Hindi, Hinglish, and English.
        """
        # Map languages to Microsoft Edge Neural TTS voices
        self.voice_map = {
            "hindi": "hi-IN-MadhurNeural",        # Warm male Hindi voice
            "hindi_female": "hi-IN-SwararaNeural",  # Clear female Hindi voice
            "hinglish": "hi-IN-MadhurNeural",     # Hinglish sounds best with Hindi neural voices
            "english": "en-US-AriaNeural",        # Clean female US English voice
            "english_male": "en-US-GuyNeural"     # Clean male US English voice
        }

    async def _generate_voice_async(self, text, output_path, voice_name):
        """
        Internal async function to communicate with Edge TTS and save the file.
        """
        # Ensure target directory exists
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        
        communicate = edge_tts.Communicate(text, voice_name)
        await communicate.save(output_path)

    def generate_voice(self, text, output_path, language="hinglish", gender="male", voice=None):
        """
        Synchronous wrapper to generate the voiceover audio.
        """
        # Select voice based on language and gender preference
        voice_name = voice
        if not voice_name:
            voice_key = language.lower()
            if voice_key == "hindi" and gender.lower() == "female":
                voice_key = "hindi_female"
            elif voice_key == "english" and gender.lower() == "male":
                voice_key = "english_male"
                
            voice_name = self.voice_map.get(voice_key, self.voice_map["hinglish"])
        
        print(f"Generating voiceover using TTS voice '{voice_name}'...")
        print(f"Text to speak: '{text[:80]}...'")
        
        try:
            # Run the async code synchronously
            asyncio.run(self._generate_voice_async(text, output_path, voice_name))
            print(f"Successfully generated voiceover at: {output_path}")
            return True
        except Exception as e:
            print(f"Error generating voiceover: {e}")
            
            # Fallback to default US Aria voice if Hindi voice fails
            if voice_name != self.voice_map["english"]:
                print("Attempting fallback to English voice...")
                try:
                    asyncio.run(self._generate_voice_async(text, output_path, self.voice_map["english"]))
                    print("Fallback voiceover generated successfully.")
                    return True
                except Exception as fallback_err:
                    print(f"Fallback voiceover also failed: {fallback_err}")
            raise e
