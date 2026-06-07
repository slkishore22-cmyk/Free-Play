from flask import Flask, jsonify, request
from flask_cors import CORS
import requests
import re
import os
from bs4 import BeautifulSoup
import json
from Crypto.Cipher import DES
import base64
from concurrent.futures import ThreadPoolExecutor

app = Flask(__name__)
CORS(app)

# Read Spotify API credentials from environment variables (set on Railway)
ENV_SPOTIFY_CLIENT_ID = os.environ.get('SPOTIFY_CLIENT_ID', '').strip()
ENV_SPOTIFY_CLIENT_SECRET = os.environ.get('SPOTIFY_CLIENT_SECRET', '').strip()

def extract_playlist_id(url):
    match = re.search(r'playlist/([a-zA-Z0-9]+)', url)
    if match:
        return match.group(1)
    return None

def decrypt_saavn_url(encrypted_url):
    try:
        key = b"38346591"
        enc_bytes = base64.b64decode(encrypted_url.strip())
        cipher = DES.new(key, DES.MODE_ECB)
        dec_bytes = cipher.decrypt(enc_bytes)
        
        # PKCS5/7 unpadding
        pad_len = dec_bytes[-1]
        if 1 <= pad_len <= 8:
            if all(b == pad_len for b in dec_bytes[-pad_len:]):
                dec_bytes = dec_bytes[:-pad_len]
                
        dec_str = dec_bytes.decode('utf-8', errors='ignore')
        return dec_str.replace('_96.mp4', '_320.mp4')
    except Exception as e:
        print(f"Decryption error: {e}")
        return None

def resolve_jiosaavn_track(track):
    track_name = track.get('name', '')
    artist_name = track.get('artist', '')
    if not track_name:
        track['streamUrl'] = None
        track['durationMs'] = 0
        track['album'] = ''
        return track

    query = f"{track_name} {artist_name}"
    # Remove parenthesis/brackets to keep search query clean
    query_clean = re.sub(r'[\(\[\{\)\]\}]', '', query)
    
    url = "https://www.jiosaavn.com/api.php"
    params = {
        '__call': 'search.getResults',
        'q': query_clean,
        '_format': 'json',
        '_marker': '0',
        'ctx': 'web6dot0'
    }
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    
    try:
        response = requests.get(url, params=params, headers=headers, timeout=5)
        if response.status_code == 200:
            try:
                data = response.json()
            except ValueError:
                data = {}
                
            results = []
            if isinstance(data, list):
                results = data
            elif isinstance(data, dict):
                results = data.get('results', [])
                
            if results:
                top = results[0]
                enc_url = top.get('encrypted_media_url') or top.get('encrypted_drm_media_url')
                if enc_url:
                    stream_url = decrypt_saavn_url(enc_url)
                    if stream_url:
                        track['streamUrl'] = stream_url
                        try:
                            track['durationMs'] = int(top.get('duration', 0)) * 1000
                        except:
                            track['durationMs'] = 0
                        track['album'] = top.get('album', '')
                        return track
    except Exception as e:
        print(f"Error resolving Saavn track '{query}': {e}")
        
    track['streamUrl'] = None
    track['durationMs'] = 0
    track['album'] = ''
    return track

def scrape_spotify_embed_token(playlist_id):
    """
    Scrape the Spotify embed page to extract the accessToken,
    then use Spotify's internal pathfinder API to fetch all tracks.
    This works for playlists of any size without needing developer credentials.
    """
    try:
        embed_url = f"https://open.spotify.com/embed/playlist/{playlist_id}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://open.spotify.com/"
        }
        
        response = requests.get(embed_url, headers=headers, timeout=15)
        if response.status_code != 200:
            return None, f"Failed to load embed page: {response.status_code}"
            
        soup = BeautifulSoup(response.text, 'html.parser')
        next_data_script = soup.find('script', id='__NEXT_DATA__')
        
        if not next_data_script:
            return None, "__NEXT_DATA__ script not found"
        
        data = json.loads(next_data_script.string)
        
        # Extract the accessToken from the session data
        access_token = data.get('props', {}).get('pageProps', {}).get('state', {}).get('session', {}).get('accessToken', '')
        
        if not access_token:
            return None, "No accessToken found in embed page"
        
        print(f"Got embed accessToken for playlist {playlist_id}")
        
        # Now use the token to fetch playlist data from Spotify's internal API
        api_url = f"https://api.spotify.com/v1/playlists/{playlist_id}"
        api_headers = {
            "Authorization": f"Bearer {access_token}",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        
        res = requests.get(api_url, headers=api_headers, timeout=10)
        if res.status_code != 200:
            return None, f"Spotify API returned {res.status_code} with embed token"
        
        playlist_data = res.json()
        name = playlist_data.get("name", "Imported Playlist")
        description = playlist_data.get("description", "")
        
        cover = ""
        images = playlist_data.get("images", [])
        if images:
            cover = images[0].get("url", "")
        
        # Paginate through all tracks
        tracks = []
        tracks_data = playlist_data.get("tracks", {})
        items = tracks_data.get("items", [])
        
        for item in items:
            t = item.get("track")
            if not t or t.get("type") != "track":
                continue
            track_id = t.get("id", "")
            track_name = t.get("name", "")
            artists = [a.get("name", "") for a in t.get("artists", [])]
            artist_name = ", ".join(artists)
            
            track_cover = cover
            album = t.get("album", {})
            if album and album.get("images"):
                track_cover = album.get("images")[0].get("url", "")
            
            tracks.append({
                "id": track_id,
                "name": track_name,
                "artist": artist_name,
                "image": track_cover,
                "album": album.get("name", "") if album else ""
            })
        
        # Follow pagination
        next_url = tracks_data.get("next")
        while next_url:
            res = requests.get(next_url, headers=api_headers, timeout=10)
            if res.status_code != 200:
                break
            page_data = res.json()
            for item in page_data.get("items", []):
                t = item.get("track")
                if not t or t.get("type") != "track":
                    continue
                track_id = t.get("id", "")
                track_name = t.get("name", "")
                artists = [a.get("name", "") for a in t.get("artists", [])]
                artist_name = ", ".join(artists)
                
                track_cover = cover
                album = t.get("album", {})
                if album and album.get("images"):
                    track_cover = album.get("images")[0].get("url", "")
                
                tracks.append({
                    "id": track_id,
                    "name": track_name,
                    "artist": artist_name,
                    "image": track_cover,
                    "album": album.get("name", "") if album else ""
                })
            next_url = page_data.get("next")
        
        print(f"Fetched {len(tracks)} tracks using embed token for playlist {playlist_id}")
        
        return {
            "name": name,
            "description": description,
            "cover": cover,
            "tracks": tracks
        }, None
        
    except Exception as e:
        return None, str(e)

def scrape_spotify_playlist(playlist_url):
    """Original scraper using __NEXT_DATA__ entity - works for small playlists only."""
    try:
        playlist_id = extract_playlist_id(playlist_url)
        if not playlist_id:
            return None, "Invalid playlist ID"
            
        embed_url = f"https://open.spotify.com/embed/playlist/{playlist_id}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://open.spotify.com/"
        }
        
        response = requests.get(embed_url, headers=headers, timeout=15)
        if response.status_code != 200:
            return None, f"Failed to load embed page: {response.status_code}"
            
        soup = BeautifulSoup(response.text, 'html.parser')
        next_data_script = soup.find('script', id='__NEXT_DATA__')
        
        if not next_data_script:
            return None, "__NEXT_DATA__ script not found in embed response"
            
        data = json.loads(next_data_script.string)
        state = data.get('props', {}).get('pageProps', {}).get('state', {})
        entity = state.get('data', {}).get('entity', {})
        
        if not entity:
            return None, "Playlist entity not found in page state"
            
        playlist_name = entity.get('name') or entity.get('title') or 'Imported Playlist'
        playlist_desc = entity.get('subtitle') or ''
        playlist_cover = entity.get('coverArt', {}).get('sources', [{}])[0].get('url', '')
        raw_tracks = entity.get('trackList', [])
        
        if not raw_tracks:
            return None, "No tracks found in embed entity"
        
        tracks = []
        for item in raw_tracks:
            track_id = item.get('uri', '').split(':')[-1] if item.get('uri') else ''
            tracks.append({
                'name': item.get('title', ''),
                'artist': item.get('subtitle', ''),
                'image': playlist_cover,
                'id': track_id
            })
            
        return {
            'tracks': tracks,
            'name': playlist_name,
            'description': playlist_desc,
            'cover': playlist_cover
        }, None
        
    except Exception as e:
        return None, str(e)

def fetch_playlist_with_keys(playlist_id, client_id, client_secret):
    try:
        # Get access token
        auth_url = "https://accounts.spotify.com/api/token"
        auth_header = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
        res = requests.post(auth_url, headers={
            "Authorization": f"Basic {auth_header}",
            "Content-Type": "application/x-www-form-urlencoded"
        }, data={"grant_type": "client_credentials"}, timeout=10)
        
        if res.status_code != 200:
            return None, f"Failed to authenticate with Spotify API: HTTP {res.status_code} - {res.text}"
            
        access_token = res.json().get("access_token")
        if not access_token:
            return None, "Failed to retrieve access token from response"
            
        # Fetch playlist metadata
        playlist_url = f"https://api.spotify.com/v1/playlists/{playlist_id}"
        res = requests.get(playlist_url, headers={
            "Authorization": f"Bearer {access_token}"
        }, timeout=10)
        
        if res.status_code != 200:
            return None, f"Failed to fetch playlist metadata: HTTP {res.status_code} - {res.text}"
            
        playlist_data = res.json()
        name = playlist_data.get("name", "Imported Playlist")
        description = playlist_data.get("description", "")
        
        cover = ""
        images = playlist_data.get("images", [])
        if images:
            cover = images[0].get("url", "")
            
        # Fetch all tracks (with pagination)
        tracks = []
        tracks_url = f"https://api.spotify.com/v1/playlists/{playlist_id}/tracks?limit=100"
        
        while tracks_url:
            res = requests.get(tracks_url, headers={
                "Authorization": f"Bearer {access_token}"
            }, timeout=10)
            
            if res.status_code != 200:
                break
                
            data = res.json()
            items = data.get("items", [])
            for item in items:
                t = item.get("track")
                if not t:
                    continue
                # Extract track details
                track_id = t.get("id", "")
                track_name = t.get("name", "")
                artists = [a.get("name", "") for a in t.get("artists", [])]
                artist_name = ", ".join(artists)
                
                track_cover = cover
                album = t.get("album", {})
                if album and album.get("images"):
                    track_cover = album.get("images")[0].get("url", "")
                    
                tracks.append({
                    "id": track_id,
                    "name": track_name,
                    "artist": artist_name,
                    "image": track_cover,
                    "album": album.get("name", "")
                })
                
            tracks_url = data.get("next")
            
        return {
            "name": name,
            "description": description,
            "cover": cover,
            "tracks": tracks
        }, None
    except Exception as e:
        return None, str(e)

def scrape_spotify_playlist_metadata(playlist_id):
    try:
        embed_url = f"https://open.spotify.com/embed/playlist/{playlist_id}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://open.spotify.com/"
        }
        
        response = requests.get(embed_url, headers=headers, timeout=15)
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            next_data_script = soup.find('script', id='__NEXT_DATA__')
            if next_data_script:
                data = json.loads(next_data_script.string)
                state = data.get('props', {}).get('pageProps', {}).get('state', {})
                entity = state.get('data', {}).get('entity', {})
                if entity:
                    playlist_name = entity.get('name') or entity.get('title') or 'Imported Playlist'
                    playlist_desc = entity.get('subtitle') or ''
                    playlist_cover = entity.get('coverArt', {}).get('sources', [{}])[0].get('url', '')
                    return playlist_name, playlist_desc, playlist_cover
    except Exception as e:
        print(f"Error scraping metadata: {e}")
    return "Imported Playlist", "", ""

def get_playlist_tracks(playlist_id):
    tracks = []
    offset = 0
    
    headers = {
        "User-Agent": "Mozilla/5.0",
        "origin": "https://spotifydown.com",
        "referer": "https://spotifydown.com/",
    }
    
    while True:
        try:
            url = f"https://api.spotifydown.com/trackList/playlist/{playlist_id}?offset={offset}"
            response = requests.get(url, headers=headers, timeout=15)
            data = response.json()
            
            if not data.get('success'):
                break
            
            items = data.get('trackList', [])
            if not items:
                break
            
            for item in items:
                name = item.get('title', '').strip()
                artist = item.get('artists', '').strip()
                if name:  # only add if track has a name
                    tracks.append({
                        'name': name,
                        'artist': artist,
                        'image': item.get('cover', ''),
                        'id': item.get('id', '')
                    })
            
            # Get next page offset
            next_offset = data.get('nextOffset')
            
            # Stop if no more pages
            if next_offset is None or next_offset == offset:
                break
                
            offset = next_offset
            print(f"Fetched {len(tracks)} tracks so far, getting offset {offset}...")
            
        except Exception as e:
            print(f"Error at offset {offset}: {e}")
            break
    
    print(f"Total tracks fetched: {len(tracks)}")
    return tracks

@app.route('/')
def index():
    return jsonify({"service": "FreePlay Spotify Scraper", "status": "running"})

@app.route('/health')
def health():
    return jsonify({"status": "ok"})

@app.route('/resolve', methods=['GET'])
def resolve_track():
    name = request.args.get('name', '').strip()
    artist = request.args.get('artist', '').strip()
    if not name:
        return jsonify({"success": False, "error": "Missing name parameter"}), 400
        
    track = {'name': name, 'artist': artist}
    resolved = resolve_jiosaavn_track(track)
    
    return jsonify({
        "success": True,
        "track": resolved
    })

@app.route('/playlist', methods=['GET'])
def get_playlist():
    url = request.args.get('url', '').strip()
    if not url:
        return jsonify({"success": False, "error": "Missing url parameter"}), 400
    if 'spotify.com/playlist/' not in url:
        return jsonify({"success": False, "error": "Invalid Spotify playlist URL"}), 400
    
    playlist_id = extract_playlist_id(url)
    if not playlist_id:
        return jsonify({"success": False, "error": "Invalid playlist URL"}), 400
    
    offset_param = request.args.get('offset')
    
    if offset_param is not None:
        try:
            offset = int(offset_param)
        except ValueError:
            offset = 0
            
        print(f"Fetching paginated playlist {playlist_id} at offset {offset}")
        
        # Scrape metadata
        playlist_name, playlist_desc, playlist_cover = scrape_spotify_playlist_metadata(playlist_id)
        
        # Try Strategy A: Fetch page of tracks from spotifydown
        headers = {
            "User-Agent": "Mozilla/5.0",
            "origin": "https://spotifydown.com",
            "referer": "https://spotifydown.com/",
        }
        
        tracks = []
        next_offset = None
        spotifydown_success = False
        try:
            api_url = f"https://api.spotifydown.com/trackList/playlist/{playlist_id}?offset={offset}"
            response = requests.get(api_url, headers=headers, timeout=15)
            data = response.json()
            
            if data.get('success'):
                items = data.get('trackList', [])
                for item in items:
                    name = item.get('title', '').strip()
                    artist = item.get('artists', '').strip()
                    if name:
                        tracks.append({
                            'name': name,
                            'artist': artist,
                            'image': item.get('cover', ''),
                            'id': item.get('id', '')
                        })
                next_offset = data.get('nextOffset')
                spotifydown_success = True
        except Exception as e:
            print(f"Error fetching offset {offset} from spotifydown: {e}")
            
        # Try Strategy B (Resilient Fallback): If spotifydown failed or returned empty tracks,
        # use official Spotify API / embed token / classic embed scraper to fetch all tracks, then slice them!
        if not spotifydown_success or not tracks:
            print(f"[Fallback] spotifydown failed or returned empty. Slicing from official API/embed token/classic scrape.")
            result = None
            
            # Priority 1: Client-provided credentials
            client_id = request.headers.get('x-spotify-client-id', '').strip()
            client_secret = request.headers.get('x-spotify-client-secret', '').strip()
            
            # Priority 2: Server-side environment variable credentials
            if not client_id or not client_secret:
                client_id = ENV_SPOTIFY_CLIENT_ID
                client_secret = ENV_SPOTIFY_CLIENT_SECRET
                
            # Strategy 1: Official Spotify API (if we have credentials)
            if client_id and client_secret:
                print(f"[Strategy 1 Fallback] Using official Spotify API for playlist {playlist_id}")
                result, error = fetch_playlist_with_keys(playlist_id, client_id, client_secret)
                
            # Strategy 2: Embed page accessToken scrape
            if not result:
                print(f"[Strategy 2 Fallback] Using embed token scrape for playlist {playlist_id}")
                result, error = scrape_spotify_embed_token(playlist_id)
                
            # Strategy 3: Classic embed scrape
            if not result:
                print(f"[Strategy 3 Fallback] Using classic embed scrape for playlist {playlist_id}")
                result, error = scrape_spotify_playlist(url)
                
            if result and result.get('tracks'):
                all_tracks = result['tracks']
                playlist_name = result.get('name') or playlist_name
                playlist_desc = result.get('description') or playlist_desc
                playlist_cover = result.get('cover') or playlist_cover
                
                # Slice tracks for the requested offset
                limit = 50
                tracks = all_tracks[offset : offset + limit]
                if offset + limit < len(all_tracks):
                    next_offset = offset + limit
                else:
                    next_offset = None
            
        # Concurrently resolve JioSaavn audio streams for this page
        resolved_tracks = []
        if tracks:
            with ThreadPoolExecutor(max_workers=20) as executor:
                resolved_tracks = list(executor.map(resolve_jiosaavn_track, tracks))
                
        return jsonify({
            "success": True,
            "playlist_id": playlist_id,
            "name": playlist_name,
            "description": playlist_desc,
            "cover": playlist_cover,
            "total_tracks": len(resolved_tracks),
            "resolved_count": len([t for t in resolved_tracks if t.get('streamUrl')]),
            "tracks": resolved_tracks,
            "nextOffset": next_offset
        })

    # Priority 1: Client-provided credentials
    client_id = request.headers.get('x-spotify-client-id', '').strip()
    client_secret = request.headers.get('x-spotify-client-secret', '').strip()
    
    # Priority 2: Server-side environment variable credentials
    if not client_id or not client_secret:
        client_id = ENV_SPOTIFY_CLIENT_ID
        client_secret = ENV_SPOTIFY_CLIENT_SECRET
    
    result = None
    error = None
    
    # Strategy 1: Official Spotify API (if we have credentials)
    if client_id and client_secret:
        print(f"[Strategy 1] Using official Spotify API for playlist {playlist_id}")
        result, error = fetch_playlist_with_keys(playlist_id, client_id, client_secret)
        if result:
            error = None  # Clear any previous error
    
    # Strategy 2: Embed page accessToken scrape (works for any size playlist)
    if not result:
        print(f"[Strategy 2] Using embed token scrape for playlist {playlist_id}")
        result, error = scrape_spotify_embed_token(playlist_id)
        if result:
            error = None
    
    # Strategy 3: Classic embed __NEXT_DATA__ scrape (only works for small playlists)
    if not result:
        print(f"[Strategy 3] Using classic embed scrape for playlist {playlist_id}")
        result, error = scrape_spotify_playlist(url)
        if result:
            error = None

    # Strategy 4: spotifydown loop fallback
    if not result:
        print(f"[Strategy 4] Using spotifydown scraper for playlist {playlist_id}")
        tracks = get_playlist_tracks(playlist_id)
        if tracks:
            playlist_name, playlist_desc, playlist_cover = scrape_spotify_playlist_metadata(playlist_id)
            result = {
                'tracks': tracks,
                'name': playlist_name,
                'description': playlist_desc,
                'cover': playlist_cover
            }
        
    if error or not result:
        return jsonify({"success": False, "error": error or "Could not fetch playlist"}), 500
        
    # Concurrently resolve JioSaavn audio streams
    # Capped at first 50 tracks to prevent timeouts on Railway
    tracks = result['tracks']
    RESOLVE_CAP = 50
    tracks_to_resolve = tracks[:RESOLVE_CAP]
    tracks_remaining = tracks[RESOLVE_CAP:]
    
    resolved_tracks = []
    if tracks_to_resolve:
        with ThreadPoolExecutor(max_workers=20) as executor:
            resolved_tracks = list(executor.map(resolve_jiosaavn_track, tracks_to_resolve))
            
    # For tracks beyond cap, set default unresolved fields
    for t in tracks_remaining:
        t['streamUrl'] = None
        t['durationMs'] = 0
        if 'album' not in t:
            t['album'] = ''
        resolved_tracks.append(t)
    
    return jsonify({
        "success": True,
        "playlist_id": playlist_id,
        "name": result['name'],
        "description": result['description'],
        "cover": result['cover'],
        "total_tracks": len(resolved_tracks),
        "resolved_count": len([t for t in resolved_tracks if t.get('streamUrl')]),
        "tracks": resolved_tracks
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=False)

