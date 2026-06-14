import os
import json
import datetime
import yt_dlp
import numpy as np

class Downloader:
    def __init__(self, history_file="reposter/history.json"):
        self.history_file = history_file
        self.history = self._load_history()

    def _load_history(self):
        if os.path.exists(self.history_file):
            try:
                with open(self.history_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                print(f"[Downloader] Error loading history: {e}")
                return []
        return []

    def _is_processed(self, video_id):
        # Check both direct match and key matching
        for entry in self.history:
            if entry.get("video_id") == video_id:
                return True
        return False

    def get_video_age_days(self, upload_date_str):
        """Parses YYYYMMDD string and returns age in days."""
        if not upload_date_str:
            return 30  # default to 30 days if unknown
        try:
            upload_date = datetime.datetime.strptime(upload_date_str, "%Y%m%d")
            today = datetime.datetime.utcnow()
            return (today - upload_date).days
        except Exception:
            return 30

    def calculate_viral_score(self, views, likes, comments, age_days, avg_views):
        """
        Calculates Composite Viral Score.
        """
        # 1. View Ratio (relative to channel average)
        if avg_views and avg_views > 0:
            view_ratio = views / avg_views
        else:
            view_ratio = 1.0

        # Caps view ratio to prevent extreme outliers skewing other channels
        view_ratio = min(view_ratio, 10.0)

        # 2. Engagement rates
        like_ratio = (likes / views) if views and views > 0 else 0
        comment_ratio = (comments / views) if views and views > 0 else 0

        # Scale engagement rates to be comparable (likes usually ~5-10%, comments ~0.5-2%)
        scaled_likes = min(like_ratio * 10.0, 2.0)
        scaled_comments = min(comment_ratio * 50.0, 2.0)

        # 3. Recency factor
        if age_days <= 3:
            recency_factor = 1.2
        elif age_days <= 7:
            recency_factor = 1.0
        elif age_days <= 14:
            recency_factor = 0.8
        elif age_days <= 30:
            recency_factor = 0.5
        else:
            recency_factor = 0.2

        # Final Score Formula
        score = (view_ratio * 0.40) + (scaled_likes * 0.25) + (scaled_comments * 0.20) + (recency_factor * 0.15)
        return round(score, 3)

    def scrape_source(self, source_url, platform="youtube", source_type="channel"):
        """
        Scrapes a source and extracts metadata for candidate short-form videos.
        Returns a list of candidate dictionaries.
        """
        candidates = []
        
        # Configure yt-dlp options
        ydl_opts = {
            'quiet': True,
            'skip_download': True,
            'extract_flat': True,
            'ignoreerrors': True,
            'no_warnings': True,
            'extractor_args': {
                'youtube': {
                    'player_client': ['default', '-android_sdkless']
                }
            }
        }

        # Load cookies if available
        for cookie_path in ["reposter/cookies.txt", "cookies.txt"]:
            if os.path.exists(cookie_path):
                ydl_opts['cookiefile'] = cookie_path
                print(f"[Downloader] Using cookies file: {cookie_path}")
                break

        # If IG, FB, or TikTok, make sure we use standard headers/cookies/agents
        if platform != "youtube":
            ydl_opts['http_headers'] = {
                'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1'
            }

        print(f"[Downloader] Scraping source: {source_url} (Platform: {platform}, Type: {source_type})")
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                # 1. First extract flat listing
                info = ydl.extract_info(source_url, download=False)
                if not info:
                    return []

                entries = []
                if 'entries' in info:
                    entries = [e for e in info['entries'] if e]
                else:
                    entries = [info]

                # Limit candidates to evaluate (to save requests and time)
                # Take up to 10 entries
                eval_entries = entries[:10]
                
                # Fetch full detail for these entries
                detailed_entries = []
                for entry in eval_entries:
                    video_url = entry.get('url') or entry.get('webpage_url')
                    video_id = entry.get('id')
                    
                    if not video_url and video_id:
                        if platform == "youtube":
                            video_url = f"https://www.youtube.com/watch?v={video_id}"
                        
                    if not video_url:
                        continue
                        
                    if self._is_processed(video_id):
                        # Skip already processed
                        continue

                    # Extract full metadata for the specific video
                    detail_opts = {
                        'quiet': True,
                        'skip_download': True,
                        'ignoreerrors': True,
                        'no_warnings': True,
                        'extractor_args': {
                            'youtube': {
                                'player_client': ['default', '-android_sdkless']
                            }
                        }
                    }
                    if 'cookiefile' in ydl_opts:
                        detail_opts['cookiefile'] = ydl_opts['cookiefile']
                    try:
                        with yt_dlp.YoutubeDL(detail_opts) as ydl_detail:
                            det_info = ydl_detail.extract_info(video_url, download=False)
                            if det_info:
                                detailed_entries.append(det_info)
                    except Exception as e:
                        print(f"[Downloader] Error extracting details for {video_url}: {e}")

                if not detailed_entries:
                    return []

                # Calculate baseline views for the source (channel average)
                views_list = [e.get('view_count', 0) for e in detailed_entries if e.get('view_count') is not None]
                avg_views = np.median(views_list) if views_list else 1000

                # Analyze candidates
                for entry in detailed_entries:
                    # Validate duration (Must be Reels/Shorts - < 60s)
                    duration = entry.get('duration', 0)
                    if duration and duration > 60:
                        continue # Skip longer videos

                    video_id = entry.get('id')
                    title = entry.get('title', '')
                    description = entry.get('description', '')
                    views = entry.get('view_count', 0) or 0
                    likes = entry.get('like_count', 0) or 0
                    comments = entry.get('comment_count', 0) or 0
                    upload_date = entry.get('upload_date', '') # YYYYMMDD
                    age_days = self.get_video_age_days(upload_date)
                    video_url = entry.get('webpage_url') or entry.get('url')

                    # Compute score
                    score = self.calculate_viral_score(views, likes, comments, age_days, avg_views)

                    candidates.append({
                        "video_id": video_id,
                        "title": title,
                        "description": description,
                        "views": views,
                        "likes": likes,
                        "comments": comments,
                        "age_days": age_days,
                        "url": video_url,
                        "viral_score": score,
                        "platform": platform,
                        "duration": duration
                    })
        except Exception as e:
            print(f"[Downloader] Scraper encountered an error: {e}")
            
        return candidates

    def find_best_viral_video(self, sources):
        """
        Iterates over a list of sources, scrapes them, and returns the absolute best candidate.
        """
        all_candidates = []
        for src in sources:
            url = src.get("url")
            plat = src.get("platform", "youtube")
            stype = src.get("type", "channel")
            
            candidates = self.scrape_source(url, platform=plat, source_type=stype)
            all_candidates.extend(candidates)

        if not all_candidates:
            print("[Downloader] ❌ No new candidate videos found after checking all sources.")
            return None

        # Sort by viral score in descending order
        all_candidates.sort(key=lambda x: x["viral_score"], reverse=True)
        best = all_candidates[0]
        print(f"[Downloader] 🏆 Winner chosen: '{best['title']}' (Score: {best['viral_score']}, Views: {best['views']}, Platform: {best['platform']})")
        return best

    def download_video(self, video_url, output_path="reposter/temp_download.mp4"):
        """
        Downloads a video from url using yt-dlp.
        """
        if os.path.exists(output_path):
            try:
                os.remove(output_path)
            except Exception:
                pass

        print(f"[Downloader] Downloading {video_url} to {output_path}...")
        
        ydl_opts = {
            'format': 'mp4',
            'outtmpl': output_path,
            'quiet': False,
            'no_warnings': True,
            'extractor_args': {
                'youtube': {
                    'player_client': ['default', '-android_sdkless']
                }
            }
        }

        # Load cookies if available
        for cookie_path in ["reposter/cookies.txt", "cookies.txt"]:
            if os.path.exists(cookie_path):
                ydl_opts['cookiefile'] = cookie_path
                break

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([video_url])
            
            if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                print(f"[Downloader] ✅ Download completed successfully. Size: {os.path.getsize(output_path)} bytes.")
                return output_path
            else:
                raise FileNotFoundError("Downloaded file does not exist or is empty")
        except Exception as e:
            print(f"[Downloader] ❌ Download failed: {e}")
            return None

if __name__ == "__main__":
    # Small test
    dl = Downloader()
    sources = [
        {"url": "ytsearch5:psychology facts shorts", "platform": "youtube", "type": "search"}
    ]
    best = dl.find_best_viral_video(sources)
    if best:
        dl.download_video(best["url"])
