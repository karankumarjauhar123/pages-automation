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
    MIN_VIEWS_THRESHOLD = 500

    def __init__(self, history_file="reposter/history.json"):
        self.history_file = history_file
        self.history = self._load_history()
        # Dynamically discovered instances (fetched once per run)
        self._piped_instances = None
        self._invidious_instances = None

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
          - https://www.youtube.com/@channel/videos
          - https://www.youtube.com/@channel/shorts  (channel tab, no ID)
          - https://www.youtube.com/@channel
          - https://www.youtube.com/playlist?list=XXX
        """
        if not url:
            return False
        if 'watch?v=' in url:
            return True
        # /shorts/VIDEO_ID — a real ID is 11 alphanumeric chars
        if re.search(r'youtube\.com/shorts/[a-zA-Z0-9_-]{8,}', url):
            return True
        if re.search(r'youtu\.be/[a-zA-Z0-9_-]{8,}', url):
            return True
        return False

    def _normalize_video_url(self, url):
        """Convert /shorts/ID to standard /watch?v=ID."""
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
            return 30
        try:
            upload_date = datetime.datetime.strptime(upload_date_str, "%Y%m%d")
            today = datetime.datetime.utcnow()
            return (today - upload_date).days
        except Exception:
            return 30

    def calculate_viral_score(self, views, likes, comments, age_days, avg_views):
        """Calculates Composite Viral Score."""
        if avg_views and avg_views > 0:
            view_ratio = views / avg_views
        else:
            view_ratio = 1.0
        view_ratio = min(view_ratio, 10.0)

        like_ratio = (likes / views) if views and views > 0 else 0
        comment_ratio = (comments / views) if views and views > 0 else 0
        scaled_likes = min(like_ratio * 10.0, 2.0)
        scaled_comments = min(comment_ratio * 50.0, 2.0)

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

        score = (view_ratio * 0.40) + (scaled_likes * 0.25) + (scaled_comments * 0.20) + (recency_factor * 0.15)
        return round(score, 3)

    # ─────────────────────────────────────────────────────────────
    #  SCRAPING / DISCOVERY
    # ─────────────────────────────────────────────────────────────

    def scrape_source(self, source_url, platform="youtube", source_type="channel"):
        """Scrapes a source and extracts metadata for candidate short-form videos."""
        candidates = []
        
        ydl_opts = {
            'quiet': True,
            'skip_download': True,
            'extract_flat': True,
            'ignoreerrors': True,
            'no_warnings': True,
            'check_formats': False,
            'extractor_args': {
                'youtube': {'player_client': ['web_creator']},
                'youtubetab': {'skip': ['authcheck']}
            }
        }

        cookie_path = self._get_cookie_path()
        if cookie_path:
            ydl_opts['cookiefile'] = cookie_path
            print(f"[Downloader] Using cookies file: {cookie_path}")

        if platform != "youtube":
            ydl_opts['http_headers'] = {
                'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15'
            }

        print(f"[Downloader] Scraping source: {source_url} (Platform: {platform}, Type: {source_type})")
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(source_url, download=False)
                if not info:
                    return []

                entries = []
                if 'entries' in info:
                    entries = [e for e in info['entries'] if e]
                else:
                    if info.get('id') and info.get('_type') not in ('playlist', 'multi_video', 'channel'):
                        entries = [info]

                if not entries:
                    print(f"[Downloader] No entries found for source: {source_url}")
                    return []

                eval_entries = entries[:10]
                
                detailed_entries = []
                for entry in eval_entries:
                    video_url = entry.get('url') or entry.get('webpage_url')
                    video_id = entry.get('id')
                    
                    if not video_url and video_id:
                        if platform == "youtube":
                            video_url = f"https://www.youtube.com/watch?v={video_id}"
                        
                    if not video_url:
                        continue

                    if not self._is_valid_video_url(video_url):
                        print(f"[Downloader] Skipping non-video URL: {video_url}")
                        continue

                    video_url = self._normalize_video_url(video_url)
                        
                    if self._is_processed(video_id):
                        continue

                    detail_opts = {
                        'quiet': True, 'skip_download': True,
                        'ignoreerrors': True, 'no_warnings': True,
                        'check_formats': False,
                        'extractor_args': {
                            'youtube': {'player_client': ['web_creator']},
                            'youtubetab': {'skip': ['authcheck']}
                        }
                    }
                    if cookie_path:
                        detail_opts['cookiefile'] = cookie_path

                    try:
                        with yt_dlp.YoutubeDL(detail_opts) as ydl_detail:
                            det_info = ydl_detail.extract_info(video_url, download=False, process=False)
                            if det_info and det_info.get('id'):
                                if det_info.get('_type') in ('playlist', 'multi_video'):
                                    continue
                                detailed_entries.append(det_info)
                                print(f"[Downloader] ✅ Got metadata for: {det_info.get('title', 'N/A')} (Views: {det_info.get('view_count', 'N/A')})")
                    except Exception as e:
                        print(f"[Downloader] Error extracting details for {video_url}: {e}")

                if not detailed_entries:
                    print(f"[Downloader] No detailed entries could be extracted for: {source_url}")
                    return []

                views_list = [e.get('view_count', 0) for e in detailed_entries if e.get('view_count') is not None]
                avg_views = np.median(views_list) if views_list else 1000

                for entry in detailed_entries:
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
                    
                    video_dl_url = entry.get('webpage_url') or entry.get('url')
                    if not video_dl_url and video_id:
                        video_dl_url = f"https://www.youtube.com/watch?v={video_id}"
                    video_dl_url = self._normalize_video_url(video_dl_url)

                    if not self._is_valid_video_url(video_dl_url):
                        continue

                    if views < self.MIN_VIEWS_THRESHOLD:
                        continue

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
        """Iterates over sources, scrapes them, returns the absolute best candidate."""
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

        all_candidates.sort(key=lambda x: x["viral_score"], reverse=True)
        best = all_candidates[0]
        print(f"[Downloader] 🏆 Winner chosen: '{best['title']}' (Score: {best['viral_score']}, Views: {best['views']}, Platform: {best['platform']})")
        return best

    # ─────────────────────────────────────────────────────────────
    #  DYNAMIC INSTANCE DISCOVERY
    # ─────────────────────────────────────────────────────────────

    def _get_piped_instances(self):
        """Fetch live Piped API instance URLs from official registry."""
        if self._piped_instances is not None:
            return self._piped_instances
        
        self._piped_instances = []
        try:
            resp = requests.get('https://piped-instances.kavin.rocks/', timeout=10)
            if resp.status_code == 200:
                instances = resp.json()
                for inst in instances:
                    api_url = inst.get('api_url', '').rstrip('/')
                    uptime = inst.get('uptime_24h', 0)
                    if api_url and uptime > 90:
                        self._piped_instances.append(api_url)
                print(f"[Downloader] Found {len(self._piped_instances)} Piped instances with >90% uptime")
        except Exception as e:
            print(f"[Downloader] Could not fetch Piped instances: {e}")
        
        # Hardcoded fallbacks
        fallbacks = [
            'https://api.piped.private.coffee',
            'https://pipedapi.kavin.rocks',
            'https://pipedapi.tokhmi.xyz',
            'https://pipedapi.extravi.dev',
            'https://pipedapi.ox.gy',
            'https://pipedapi.hostux.net',
            'https://pipedapi.adminforge.de',
            'https://pipedapi.suyu.lgbt'
        ]
        for fb in fallbacks:
            if fb not in self._piped_instances:
                self._piped_instances.append(fb)
        
        import random
        random.shuffle(self._piped_instances)
        return self._piped_instances

    def _get_invidious_instances(self):
        """Fetch live Invidious API instance URLs from official registry."""
        if self._invidious_instances is not None:
            return self._invidious_instances
        
        self._invidious_instances = []
        try:
            resp = requests.get('https://api.invidious.io/instances.json', timeout=10)
            if resp.status_code == 200:
                instances = resp.json()
                for entry in instances:
                    if entry and len(entry) >= 2 and isinstance(entry[1], dict):
                        info = entry[1]
                        is_https = info.get('type') == 'https'
                        monitor = info.get('monitor') or {}
                        last_status = monitor.get('last_status')
                        if is_https and last_status == 200:
                            uri = info.get('uri', '').rstrip('/')
                            if uri:
                                self._invidious_instances.append(uri)
                print(f"[Downloader] Found {len(self._invidious_instances)} Invidious API instances")
        except Exception as e:
            print(f"[Downloader] Could not fetch Invidious instances: {e}")
        
        # Hardcoded fallbacks
        fallbacks = [
            'https://inv.nadeko.net',
            'https://yewtu.be',
            'https://invidious.nerdvpn.de',
            'https://invidious.no-logs.com',
            'https://invidious.projectsegfau.lt',
            'https://invidious.privacydev.net',
            'https://invidious.lunar.icu',
            'https://iv.melmac.space'
        ]
        for fb in fallbacks:
            if fb not in self._invidious_instances:
                self._invidious_instances.append(fb)
        
        import random
        random.shuffle(self._invidious_instances)
        return self._invidious_instances

    # ─────────────────────────────────────────────────────────────
    #  DOWNLOAD METHODS
    # ─────────────────────────────────────────────────────────────

    def download_video(self, video_url, output_path="reposter/temp_download.mp4"):
        """
        Downloads a video using multiple strategies:
        1. yt-dlp with PO Token plugin (auto-generates Proof of Origin)
        2. Piped API (dynamically discovered instances)
        3. Invidious API (dynamically discovered, with ?local=true proxy)
        4. Cobalt API (failsafe public instance proxy)
        """
        if os.path.exists(output_path):
            try:
                os.remove(output_path)
            except Exception:
                pass

        video_id = self._extract_video_id(video_url)
        print(f"[Downloader] Downloading {video_url} (ID: {video_id}) to {output_path}...")
        
        # Strategy 1: yt-dlp
        result = self._download_via_ytdlp(video_url, output_path)
        if result:
            return result

        # Strategy 2: Piped API (dynamically fetched instances)
        if video_id:
            result = self._download_via_piped(video_id, output_path)
            if result:
                return result

        # Strategy 3: Invidious API with ?local=true
        if video_id:
            result = self._download_via_invidious(video_id, output_path)
            if result:
                return result

        # Strategy 4: Cobalt API
        result = self._download_via_cobalt(video_url, output_path)
        if result:
            return result

        print(f"[Downloader] ❌ All download strategies exhausted for: {video_url}")
        return None

    def _download_via_cobalt(self, video_url, output_path):
        """Final failsafe: Download via public Cobalt API instance."""
        instances = [
            'https://dog.kittycat.boo',
            'https://fox.kittycat.boo',
            'https://rue-cobalt.xenon.zone',
            'https://nuko-c.meowing.de',
            'https://subito-c.meowing.de',
            'https://cobalt.alpha.wolfy.love',
            'https://melon.clxxped.lol',
            'https://api.cobalt.tools'
        ]
        
        for instance in instances:
            try:
                print(f"[Downloader] Trying Cobalt API: {instance}")
                headers = {
                    'Accept': 'application/json',
                    'Content-Type': 'application/json',
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0'
                }
                payload = {
                    'url': video_url,
                    'videoQuality': '720',  # 720p is perfect and reliable
                    'filenameStyle': 'basic'
                }
                resp = requests.post(instance, json=payload, headers=headers, timeout=30)
                if resp.status_code != 200:
                    print(f"[Downloader] ⚠️ Cobalt {instance} returned HTTP {resp.status_code}: {resp.text}")
                    continue
                
                data = resp.json()
                if data.get('status') == 'error':
                    err_info = data.get('error', {})
                    err_msg = err_info.get('code') or data.get('text') or str(err_info)
                    print(f"[Downloader] ⚠️ Cobalt error from {instance}: {err_msg}")
                    continue
                
                download_url = data.get('url')
                if download_url:
                    print(f"[Downloader] Downloading file from Cobalt redirect...")
                    self._download_file(download_url, output_path)
                    if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                        print(f"[Downloader] ✅ Downloaded via Cobalt ({instance}). Size: {os.path.getsize(output_path)} bytes.")
                        return output_path
            except Exception as e:
                print(f"[Downloader] ⚠️ Cobalt instance {instance} failed: {e}")
                continue
        return None

    def _download_via_ytdlp(self, video_url, output_path):
        """Try yt-dlp with PO Token plugin (yt-dlp-getpot-wpc auto-fetches tokens)."""
        cookie_path = self._get_cookie_path()

        strategies = [
            # 1. Try android_embedded / web_embedded / ios_embedded (best for bypassing signature blocks without cookies)
            {
                'name': 'yt-dlp android_embedded+web_embedded',
                'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best[ext=mp4]/best',
                'player_client': ['android_embedded', 'web_embedded', 'ios_embedded']
            },
            {
                'name': 'yt-dlp pre-merged embedded',
                'format': 'best[ext=mp4]/best',
                'player_client': ['android_embedded', 'web_embedded', 'ios_embedded']
            },
            # 2. Try standard android/ios clients
            {
                'name': 'yt-dlp android+ios',
                'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best[ext=mp4]/best',
                'player_client': ['android', 'ios']
            },
            {
                'name': 'yt-dlp pre-merged android+ios',
                'format': 'best[ext=mp4]/best',
                'player_client': ['android', 'ios']
            },
            # 3. Default yt-dlp client fallback list (highly robust in modern yt-dlp)
            {
                'name': 'yt-dlp default clients',
                'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best[ext=mp4]/best'
            },
            # 4. Pre-merged format with default clients
            {
                'name': 'yt-dlp pre-merged default',
                'format': 'best[ext=mp4]/best'
            },
            # 5. Creator clients with PO token (existing fallback)
            {
                'name': 'yt-dlp web_creator+PO',
                'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best[ext=mp4]/best',
                'player_client': ['web_creator']
            },
            {
                'name': 'yt-dlp default+PO',
                'format': 'bestvideo+bestaudio/best[ext=mp4]/best',
                'player_client': ['default']
            },
            {
                'name': 'yt-dlp mweb+PO',
                'format': 'best[ext=mp4]/best',
                'player_client': ['mweb']
            },
        ]

        for strategy in strategies:
            # We will try both with cookies (if available) and without cookies (anonymous fallback)
            # This is critical if the cookies file is expired/invalid, which blocks authenticated requests.
            cookie_options = [True, False] if cookie_path else [False]
            
            for use_cookies in cookie_options:
                cookie_desc = "with cookies" if use_cookies else "without cookies"
                print(f"[Downloader] Trying {strategy['name']} ({cookie_desc})...")
                
                if os.path.exists(output_path):
                    try: os.remove(output_path)
                    except: pass

                extractor_args = {
                    'youtubetab': {'skip': ['authcheck']}
                }
                if 'player_client' in strategy:
                    extractor_args['youtube'] = {'player_client': strategy['player_client']}

                ydl_opts = {
                    'format': strategy['format'],
                    'outtmpl': output_path,
                    'quiet': False,
                    'no_warnings': True,
                    'check_formats': False,
                    'merge_output_format': 'mp4',
                    'extractor_args': extractor_args
                }
                if use_cookies and cookie_path:
                    ydl_opts['cookiefile'] = cookie_path

                try:
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        ydl.download([video_url])
                    
                    actual_path = self._find_downloaded_file(output_path)
                    if actual_path:
                        if actual_path != output_path:
                            os.rename(actual_path, output_path)
                        print(f"[Downloader] ✅ Downloaded via {strategy['name']} ({cookie_desc}). Size: {os.path.getsize(output_path)} bytes.")
                        return output_path
                    else:
                        print(f"[Downloader] ⚠️ {strategy['name']} ({cookie_desc}) produced no output file.")
                except Exception as e:
                    print(f"[Downloader] ⚠️ {strategy['name']} ({cookie_desc}) failed: {e}")
                    continue
        return None

    def _download_via_piped(self, video_id, output_path):
        """Download via dynamically discovered Piped API instances."""
        instances = self._get_piped_instances()
        
        for instance in instances[:15]:  # Try up to 15 instances
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

                # Method A: HLS stream
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

                # Method B: Video + Audio streams
                video_streams = data.get('videoStreams', [])
                audio_streams = data.get('audioStreams', [])

                best_video = None
                for s in sorted(video_streams, key=lambda x: x.get('height', 0), reverse=True):
                    if not s.get('url'):
                        continue
                    mime = s.get('mimeType', '')
                    if 'video/mp4' in mime or s.get('format') == 'MPEG_4':
                        if s.get('height', 0) <= 1080:
                            best_video = s
                            break

                best_audio = None
                for s in sorted(audio_streams, key=lambda x: x.get('bitrate', 0), reverse=True):
                    if not s.get('url'):
                        continue
                    mime = s.get('mimeType', '')
                    if 'audio/mp4' in mime or 'audio/m4a' in mime or 'audio/webm' in mime:
                        best_audio = s
                        break

                if best_video and best_audio:
                    print(f"[Downloader] Downloading Piped streams (V: {best_video.get('quality', '?')}, A: {best_audio.get('quality', '?')})...")
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
                            if os.path.exists(tmp): os.remove(tmp)

                    if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                        print(f"[Downloader] ✅ Downloaded via Piped streams ({instance}). Size: {os.path.getsize(output_path)} bytes.")
                        return output_path
                    
            except Exception as e:
                print(f"[Downloader] ⚠️ Piped instance {instance} failed: {e}")
                continue
        return None

    def _download_via_invidious(self, video_id, output_path):
        """Download via dynamically discovered Invidious API instances with ?local=true."""
        instances = self._get_invidious_instances()
        
        for instance in instances[:15]:  # Try up to 15 instances
            try:
                print(f"[Downloader] Trying Invidious: {instance}")
                # ?local=true makes Invidious proxy the video data through its server
                api_url = f"{instance}/api/v1/videos/{video_id}?local=true"
                resp = requests.get(api_url, timeout=30, headers={
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0'
                })
                if resp.status_code != 200:
                    print(f"[Downloader] ⚠️ Invidious {instance} returned HTTP {resp.status_code}")
                    continue
                
                data = resp.json()

                # Method A: Pre-muxed streams (video + audio combined)
                format_streams = data.get('formatStreams', [])
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

                # Method B: Adaptive formats (separate video + audio)
                adaptive_formats = data.get('adaptiveFormats', [])
                best_video = None
                best_audio = None
                for fmt in adaptive_formats:
                    if not fmt.get('url'):
                        continue
                    ftype = fmt.get('type', '')
                    if 'video/mp4' in ftype:
                        if best_video is None or fmt.get('bitrate', 0) > best_video.get('bitrate', 0):
                            best_video = fmt
                    elif 'audio' in ftype:
                        if best_audio is None or fmt.get('bitrate', 0) > best_audio.get('bitrate', 0):
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
                            if os.path.exists(tmp): os.remove(tmp)

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
    dl = Downloader()
    sources = [
        {"url": "ytsearch5:psychology facts shorts", "platform": "youtube", "type": "search"}
    ]
    best = dl.find_best_viral_video(sources)
    if best:
        dl.download_video(best["url"])
