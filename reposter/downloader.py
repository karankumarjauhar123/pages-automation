import os
import json
import re
import datetime
import subprocess
import yt_dlp
import requests
import numpy as np

class Downloader:
    # Minimum views to consider a video as a viral candidate.
    # Prevents selecting brand-new videos with 1-2 views that get
    # inflated viral scores from the recency factor.
    MIN_VIEWS_THRESHOLD = 500

    # Piped API instances (proxied YouTube streams - works from datacenter IPs)
    PIPED_INSTANCES = [
        'https://pipedapi.kavin.rocks',
        'https://pipedapi.r4fo.com',
        'https://pipedapi.in.projectsegfau.lt',
    ]

    # Invidious API instances (another YouTube proxy network)
    INVIDIOUS_INSTANCES = [
        'https://inv.nadeko.net',
        'https://invidious.nerdvpn.de',
        'https://invidious.privacyredirect.com',
    ]

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

    def _get_cookie_path(self):
        """Returns the path to the cookies file if available."""
        for cookie_path in ["reposter/cookies.txt", "cookies.txt"]:
            if os.path.exists(cookie_path):
                return cookie_path
        return None

    def _is_valid_video_url(self, url):
        """
        Check if URL points to an individual video.
        
        VALID:
          - https://www.youtube.com/watch?v=VIDEO_ID
          - https://www.youtube.com/shorts/VIDEO_ID  (individual Short)
          - https://youtu.be/VIDEO_ID
        
        INVALID:
          - https://www.youtube.com/@channel/videos   (channel tab)
          - https://www.youtube.com/@channel/shorts    (channel shorts tab)
          - https://www.youtube.com/@channel            (channel home)
          - https://www.youtube.com/playlist?list=XXX   (playlist)
        """
        if not url:
            return False
        # Standard watch URL
        if 'watch?v=' in url:
            return True
        # YouTube Shorts individual video: /shorts/VIDEO_ID
        # A real video ID is 11 chars of [a-zA-Z0-9_-].
        # Channel tabs like /@channel/shorts do NOT have a video ID after /shorts.
        if re.search(r'youtube\.com/shorts/[a-zA-Z0-9_-]{8,}', url):
            return True
        # youtu.be short links
        if re.search(r'youtu\.be/[a-zA-Z0-9_-]{8,}', url):
            return True
        return False

    def _normalize_video_url(self, url):
        """Convert /shorts/ID to standard /watch?v=ID for consistent handling."""
        if not url:
            return url
        match = re.search(r'youtube\.com/shorts/([a-zA-Z0-9_-]+)', url)
        if match:
            return f"https://www.youtube.com/watch?v={match.group(1)}"
        return url

    def _extract_video_id(self, url):
        """Extract YouTube video ID from various URL formats."""
        if not url:
            return None
        match = re.search(r'[?&]v=([a-zA-Z0-9_-]+)', url)
        if match:
            return match.group(1)
        match = re.search(r'/shorts/([a-zA-Z0-9_-]+)', url)
        if match:
            return match.group(1)
        match = re.search(r'youtu\.be/([a-zA-Z0-9_-]+)', url)
        if match:
            return match.group(1)
        return None

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
        
        # Configure yt-dlp options for flat listing
        ydl_opts = {
            'quiet': True,
            'skip_download': True,
            'extract_flat': True,
            'ignoreerrors': True,
            'no_warnings': True,
            'check_formats': False,
            'extractor_args': {
                'youtube': {
                    'player_client': ['web_creator']
                },
                'youtubetab': {
                    'skip': ['authcheck']
                }
            }
        }

        # Load cookies if available
        cookie_path = self._get_cookie_path()
        if cookie_path:
            ydl_opts['cookiefile'] = cookie_path
            print(f"[Downloader] Using cookies file: {cookie_path}")

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
                    # Only treat single results as entries if they look like individual videos
                    if info.get('id') and info.get('_type') not in ('playlist', 'multi_video', 'channel'):
                        entries = [info]

                if not entries:
                    print(f"[Downloader] No entries found for source: {source_url}")
                    return []

                # Limit candidates to evaluate (to save requests and time)
                eval_entries = entries[:10]
                
                # Fetch full detail for these entries using process=False
                # to avoid format selection errors on datacenter IPs
                detailed_entries = []
                for entry in eval_entries:
                    video_url = entry.get('url') or entry.get('webpage_url')
                    video_id = entry.get('id')
                    
                    if not video_url and video_id:
                        if platform == "youtube":
                            video_url = f"https://www.youtube.com/watch?v={video_id}"
                        
                    if not video_url:
                        continue

                    # Validate: must be an individual video URL
                    if not self._is_valid_video_url(video_url):
                        print(f"[Downloader] Skipping non-video URL: {video_url}")
                        continue

                    # Normalize shorts URLs to watch URLs
                    video_url = self._normalize_video_url(video_url)
                        
                    if self._is_processed(video_id):
                        continue

                    # Extract full metadata using process=False to skip format selection
                    detail_opts = {
                        'quiet': True,
                        'skip_download': True,
                        'ignoreerrors': True,
                        'no_warnings': True,
                        'check_formats': False,
                        'extractor_args': {
                            'youtube': {
                                'player_client': ['web_creator']
                            },
                            'youtubetab': {
                                'skip': ['authcheck']
                            }
                        }
                    }
                    if cookie_path:
                        detail_opts['cookiefile'] = cookie_path

                    try:
                        with yt_dlp.YoutubeDL(detail_opts) as ydl_detail:
                            det_info = ydl_detail.extract_info(video_url, download=False, process=False)
                            if det_info and det_info.get('id'):
                                entry_type = det_info.get('_type', 'video')
                                if entry_type in ('playlist', 'multi_video'):
                                    continue
                                detailed_entries.append(det_info)
                                print(f"[Downloader] ✅ Got metadata for: {det_info.get('title', 'N/A')} (Views: {det_info.get('view_count', 'N/A')})")
                    except Exception as e:
                        print(f"[Downloader] Error extracting details for {video_url}: {e}")

                if not detailed_entries:
                    print(f"[Downloader] No detailed entries could be extracted for: {source_url}")
                    return []

                # Calculate baseline views for the source (channel average)
                views_list = [e.get('view_count', 0) for e in detailed_entries if e.get('view_count') is not None]
                avg_views = np.median(views_list) if views_list else 1000

                # Analyze candidates
                for entry in detailed_entries:
                    # Validate duration (Must be Reels/Shorts - < 90s, giving some margin)
                    duration = entry.get('duration', 0)
                    if duration and duration > 90:
                        continue

                    video_id = entry.get('id')
                    title = entry.get('title', '')
                    description = entry.get('description', '')
                    views = entry.get('view_count', 0) or 0
                    likes = entry.get('like_count', 0) or 0
                    comments = entry.get('comment_count', 0) or 0
                    upload_date = entry.get('upload_date', '')
                    age_days = self.get_video_age_days(upload_date)
                    
                    # Construct proper video URL for download
                    video_dl_url = entry.get('webpage_url') or entry.get('url')
                    if not video_dl_url and video_id:
                        video_dl_url = f"https://www.youtube.com/watch?v={video_id}"
                    video_dl_url = self._normalize_video_url(video_dl_url)

                    if not self._is_valid_video_url(video_dl_url):
                        continue

                    # Skip videos below minimum view threshold
                    if views < self.MIN_VIEWS_THRESHOLD:
                        continue

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
                        "url": video_dl_url,
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

    # ─────────────────────────────────────────────────────────────
    #  DOWNLOAD METHODS (multi-strategy with proxy fallbacks)
    # ─────────────────────────────────────────────────────────────

    def download_video(self, video_url, output_path="reposter/temp_download.mp4"):
        """
        Downloads a video using multiple strategies:
        1. yt-dlp (direct, multiple player clients)
        2. Piped API (proxied YouTube streams)
        3. Invidious API (another proxy network)
        """
        if os.path.exists(output_path):
            try:
                os.remove(output_path)
            except Exception:
                pass

        video_id = self._extract_video_id(video_url)
        print(f"[Downloader] Downloading {video_url} (ID: {video_id}) to {output_path}...")
        
        # Strategy 1: yt-dlp direct (tries multiple player clients)
        result = self._download_via_ytdlp(video_url, output_path)
        if result:
            return result

        # Strategy 2: Piped API (proxied streams - bypasses datacenter IP blocks)
        if video_id:
            result = self._download_via_piped(video_id, output_path)
            if result:
                return result

        # Strategy 3: Invidious API (another proxy network)
        if video_id:
            result = self._download_via_invidious(video_id, output_path)
            if result:
                return result

        print(f"[Downloader] ❌ All download strategies exhausted for: {video_url}")
        return None

    def _download_via_ytdlp(self, video_url, output_path):
        """Try downloading via yt-dlp with multiple player client strategies."""
        cookie_path = self._get_cookie_path()

        strategies = [
            {
                'name': 'yt-dlp web_creator',
                'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best[ext=mp4]/best',
                'player_client': ['web_creator'],
            },
            {
                'name': 'yt-dlp ios',
                'format': 'bestvideo+bestaudio/best[ext=mp4]/best',
                'player_client': ['ios'],
            },
            {
                'name': 'yt-dlp mweb',
                'format': 'best[ext=mp4]/best',
                'player_client': ['mweb'],
            },
        ]

        for strategy in strategies:
            print(f"[Downloader] Trying {strategy['name']}...")
            
            if os.path.exists(output_path):
                try:
                    os.remove(output_path)
                except Exception:
                    pass

            ydl_opts = {
                'format': strategy['format'],
                'outtmpl': output_path,
                'quiet': False,
                'no_warnings': True,
                'check_formats': False,
                'merge_output_format': 'mp4',
                'extractor_args': {
                    'youtube': {
                        'player_client': strategy['player_client']
                    },
                    'youtubetab': {
                        'skip': ['authcheck']
                    }
                }
            }

            if cookie_path:
                ydl_opts['cookiefile'] = cookie_path

            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([video_url])
                
                actual_path = self._find_downloaded_file(output_path)
                if actual_path:
                    if actual_path != output_path:
                        os.rename(actual_path, output_path)
                    print(f"[Downloader] ✅ Downloaded via {strategy['name']}. Size: {os.path.getsize(output_path)} bytes.")
                    return output_path
                else:
                    print(f"[Downloader] ⚠️ {strategy['name']} produced no output file.")
            except Exception as e:
                print(f"[Downloader] ⚠️ {strategy['name']} failed: {e}")
                continue

        return None

    def _download_via_piped(self, video_id, output_path):
        """
        Download via Piped API instances. Piped proxies YouTube streams
        through its own servers, bypassing YouTube's datacenter IP blocks.
        """
        for instance in self.PIPED_INSTANCES:
            try:
                print(f"[Downloader] Trying Piped: {instance}")
                api_url = f"{instance}/streams/{video_id}"
                resp = requests.get(api_url, timeout=30, headers={
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0'
                })
                if resp.status_code != 200:
                    print(f"[Downloader] ⚠️ Piped {instance} returned HTTP {resp.status_code}")
                    continue
                
                data = resp.json()

                # ── Method A: Download via HLS stream (simplest) ──
                hls_url = data.get('hls')
                if hls_url:
                    print(f"[Downloader] Trying HLS download from Piped...")
                    try:
                        result = subprocess.run(
                            ['ffmpeg', '-y', '-i', hls_url, '-c', 'copy', '-bsf:a', 'aac_adtstoasc', output_path],
                            capture_output=True, timeout=180
                        )
                        if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                            print(f"[Downloader] ✅ Downloaded via Piped HLS ({instance}). Size: {os.path.getsize(output_path)} bytes.")
                            return output_path
                    except Exception as e:
                        print(f"[Downloader] ⚠️ Piped HLS failed: {e}")

                # ── Method B: Download video + audio streams separately and merge ──
                video_streams = data.get('videoStreams', [])
                audio_streams = data.get('audioStreams', [])

                # Pick the best MP4 video stream (prefer 720p or closest)
                best_video = None
                for s in sorted(video_streams, key=lambda x: x.get('height', 0), reverse=True):
                    if not s.get('url'):
                        continue
                    mime = s.get('mimeType', '')
                    if 'video/mp4' in mime or s.get('format') == 'MPEG_4':
                        if s.get('height', 0) <= 1080:  # cap at 1080p
                            best_video = s
                            break

                # Pick the best M4A/AAC audio stream
                best_audio = None
                for s in sorted(audio_streams, key=lambda x: x.get('bitrate', 0), reverse=True):
                    if not s.get('url'):
                        continue
                    mime = s.get('mimeType', '')
                    if 'audio/mp4' in mime or 'audio/m4a' in mime:
                        best_audio = s
                        break
                # Fallback: any audio
                if not best_audio:
                    for s in sorted(audio_streams, key=lambda x: x.get('bitrate', 0), reverse=True):
                        if s.get('url'):
                            best_audio = s
                            break

                if best_video and best_audio:
                    print(f"[Downloader] Downloading Piped streams (V: {best_video.get('quality', '?')}, A: {best_audio.get('quality', '?')})...")
                    video_tmp = output_path + '.v.tmp'
                    audio_tmp = output_path + '.a.tmp'

                    try:
                        self._download_file(best_video['url'], video_tmp)
                        self._download_file(best_audio['url'], audio_tmp)

                        # Merge with ffmpeg
                        subprocess.run(
                            ['ffmpeg', '-y', '-i', video_tmp, '-i', audio_tmp,
                             '-c:v', 'copy', '-c:a', 'aac', '-shortest', output_path],
                            capture_output=True, timeout=120
                        )
                    finally:
                        for tmp in [video_tmp, audio_tmp]:
                            if os.path.exists(tmp):
                                os.remove(tmp)

                    if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                        print(f"[Downloader] ✅ Downloaded via Piped streams ({instance}). Size: {os.path.getsize(output_path)} bytes.")
                        return output_path
                    
            except Exception as e:
                print(f"[Downloader] ⚠️ Piped instance {instance} failed: {e}")
                continue
        
        return None

    def _download_via_invidious(self, video_id, output_path):
        """
        Download via Invidious API instances. Similar to Piped, Invidious
        proxies YouTube streams through its own servers.
        """
        for instance in self.INVIDIOUS_INSTANCES:
            try:
                print(f"[Downloader] Trying Invidious: {instance}")
                api_url = f"{instance}/api/v1/videos/{video_id}"
                resp = requests.get(api_url, timeout=30, headers={
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0'
                })
                if resp.status_code != 200:
                    print(f"[Downloader] ⚠️ Invidious {instance} returned HTTP {resp.status_code}")
                    continue
                
                data = resp.json()

                # Invidious provides 'formatStreams' (pre-muxed) and 'adaptiveFormats' (separate)
                format_streams = data.get('formatStreams', [])
                adaptive_formats = data.get('adaptiveFormats', [])

                # ── Method A: Pre-muxed stream (has both video + audio) ──
                for stream in format_streams:
                    if not stream.get('url'):
                        continue
                    container = stream.get('container', '')
                    if container == 'mp4' or 'video/mp4' in stream.get('type', ''):
                        print(f"[Downloader] Downloading pre-muxed stream ({stream.get('qualityLabel', '?')})...")
                        self._download_file(stream['url'], output_path)
                        if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                            print(f"[Downloader] ✅ Downloaded via Invidious ({instance}). Size: {os.path.getsize(output_path)} bytes.")
                            return output_path

                # ── Method B: Adaptive formats (separate video + audio) ──
                best_video = None
                best_audio = None
                for fmt in adaptive_formats:
                    if not fmt.get('url'):
                        continue
                    ftype = fmt.get('type', '')
                    if 'video/mp4' in ftype and (best_video is None or fmt.get('bitrate', 0) > best_video.get('bitrate', 0)):
                        best_video = fmt
                    elif 'audio' in ftype and (best_audio is None or fmt.get('bitrate', 0) > best_audio.get('bitrate', 0)):
                        best_audio = fmt

                if best_video and best_audio:
                    print(f"[Downloader] Downloading Invidious adaptive streams...")
                    video_tmp = output_path + '.v.tmp'
                    audio_tmp = output_path + '.a.tmp'
                    try:
                        self._download_file(best_video['url'], video_tmp)
                        self._download_file(best_audio['url'], audio_tmp)
                        subprocess.run(
                            ['ffmpeg', '-y', '-i', video_tmp, '-i', audio_tmp,
                             '-c:v', 'copy', '-c:a', 'aac', '-shortest', output_path],
                            capture_output=True, timeout=120
                        )
                    finally:
                        for tmp in [video_tmp, audio_tmp]:
                            if os.path.exists(tmp):
                                os.remove(tmp)

                    if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                        print(f"[Downloader] ✅ Downloaded via Invidious adaptive ({instance}). Size: {os.path.getsize(output_path)} bytes.")
                        return output_path
                    
            except Exception as e:
                print(f"[Downloader] ⚠️ Invidious instance {instance} failed: {e}")
                continue
        
        return None

    def _download_file(self, url, dest_path, timeout=120):
        """Download a file from URL to local path using requests."""
        with requests.get(url, stream=True, timeout=timeout, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0'
        }) as r:
            r.raise_for_status()
            with open(dest_path, 'wb') as f:
                for chunk in r.iter_content(chunk_size=65536):
                    f.write(chunk)

    def _find_downloaded_file(self, expected_path):
        """Find the actual downloaded file (yt-dlp may change the extension)."""
        if os.path.exists(expected_path) and os.path.getsize(expected_path) > 0:
            return expected_path
        base = os.path.splitext(expected_path)[0]
        for ext in ['.mp4', '.mkv', '.webm']:
            candidate = base + ext
            if os.path.exists(candidate) and os.path.getsize(candidate) > 0:
                return candidate
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
