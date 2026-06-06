from flask import Flask, jsonify, request
from flask_cors import CORS
import requests
import re
from bs4 import BeautifulSoup
import json
from Crypto.Cipher import DES
import base64
from concurrent.futures import ThreadPoolExecutor

app = Flask(__name__)
CORS(app)

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

def scrape_spotify_playlist(playlist_url):
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
    
    client_id = request.headers.get('x-spotify-client-id', '').strip()
    client_secret = request.headers.get('x-spotify-client-secret', '').strip()
    
    result = None
    error = None
    
    if client_id and client_secret:
        print(f"Using official Spotify API for playlist {playlist_id}")
        result, error = fetch_playlist_with_keys(playlist_id, client_id, client_secret)
    else:
        print(f"Using scraping fallback for playlist {playlist_id}")
        result, error = scrape_spotify_playlist(url)
        
    if error or not result:
        return jsonify({"success": False, "error": error or "Could not fetch playlist"}), 500
        
    # Concurrently resolve JioSaavn audio streams
    # Capped at first 100 tracks to prevent timeouts
    tracks = result['tracks']
    tracks_to_resolve = tracks[:100]
    tracks_remaining = tracks[100:]
    
    resolved_tracks = []
    if tracks_to_resolve:
        with ThreadPoolExecutor(max_workers=20) as executor:
            resolved_tracks = list(executor.map(resolve_jiosaavn_track, tracks_to_resolve))
            
    # For tracks beyond 100, set default unresolved fields
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
        "tracks": resolved_tracks
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=False)
