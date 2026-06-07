from flask import Flask, jsonify, request
import requests
import re
import json
import cloudscraper

app = Flask(__name__)

def get_jiosaavn_search(query):
    try:
        response = requests.get(
            'https://www.jiosaavn.com/api.php',
            params={
                '__call': 'search.getResults',
                'q': query,
                '_format': 'json',
                '_marker': '0',
                'ctx': 'web6dot0'
            },
            headers={
                'User-Agent': 'Mozilla/5.0',
                'Accept': 'application/json',
            },
            timeout=10
        )
        return response.json()
    except Exception as e:
        return None

def decrypt_jiosaavn_url(encrypted_url):
    try:
        from Crypto.Cipher import DES
        import base64
        key = b'38346591'
        enc = base64.b64decode(encrypted_url.encode())
        cipher = DES.new(key, DES.MODE_ECB)
        decrypted = cipher.decrypt(enc)
        
        # PKCS5/7 padding stripping
        if decrypted:
            pad_len = decrypted[-1]
            if 1 <= pad_len <= 8:
                decrypted = decrypted[:-pad_len]
                
        url = decrypted.decode('utf-8').strip()
        url = url.replace('_96.mp4', '_320.mp4')
        url = url.replace('_160.mp4', '_320.mp4')
        return url
    except Exception as e:
        print(f"Decrypt error: {e}")
        return None

@app.route('/')
def index():
    return jsonify({"service": "FreePlay Server", "status": "running"})

@app.route('/health')
def health():
    return jsonify({"status": "ok"})

@app.route('/search', methods=['GET'])
def search_track():
    query = request.args.get('q', '').strip()
    if not query:
        return jsonify({"success": False, "error": "Missing query"}), 400
    
    try:
        data = get_jiosaavn_search(query)
        if not data:
            return jsonify({"success": False, "error": "JioSaavn search failed"}), 500
        
        results = data.get('results', [])
        import html
        formatted_results = []
        for item in results[:10]: # Return top 10 results
            encrypted_url = (
                item.get('more_info', {}).get('encrypted_media_url') or
                item.get('more_info', {}).get('encryptedMediaUrl') or
                item.get('encrypted_media_url') or
                item.get('encrypted_drm_media_url') or
                ''
            )
            print(f"Raw item: {json.dumps(item)[:500]}")
            print(f"Encrypted URL found: {bool(encrypted_url)}")
            print(f"Encrypted URL value: {encrypted_url[:50] if encrypted_url else 'NONE'}")
            
            stream_url = decrypt_jiosaavn_url(encrypted_url) if encrypted_url else None
            
            name = item.get('title', '') or item.get('song', '') or ''
            artist = item.get('subtitle', '') or item.get('primary_artists', '') or ''
            image = item.get('image', '') or item.get('more_info', {}).get('square_image', '') or ''
            image = image.replace('150x150', '500x500')
            
            formatted_results.append({
                "id": item.get('id', ''),
                "name": html.unescape(name),
                "artist": html.unescape(artist),
                "image": image,
                "stream_url": stream_url,
                "duration": item.get('duration', '') or item.get('more_info', {}).get('duration', '0')
            })
        
        return jsonify({
            "success": True,
            "results": formatted_results
        })
        
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/playlist', methods=['GET'])
def get_playlist():
    # Accept comma separated track names
    # OR a Spotify-like JSON body
    tracks_param = request.args.get('tracks', '')
    
    if not tracks_param:
        return jsonify({"success": False, "error": "Missing tracks parameter"}), 400
    
    track_names = [t.strip() for t in tracks_param.split(',') if t.strip()]
    
    results = []
    import html
    for track_name in track_names[:50]:  # limit to 50 at a time
        try:
            data = get_jiosaavn_search(track_name)
            if data and data.get('results'):
                item = data['results'][0]
                encrypted_url = (
                    item.get('more_info', {}).get('encrypted_media_url') or
                    item.get('more_info', {}).get('encryptedMediaUrl') or
                    item.get('encrypted_media_url') or
                    item.get('encrypted_drm_media_url') or
                    ''
                )
                stream_url = decrypt_jiosaavn_url(encrypted_url) if encrypted_url else None
                
                name = item.get('title', '') or item.get('song', '') or ''
                artist = item.get('subtitle', '') or item.get('primary_artists', '') or ''
                image = item.get('image', '') or item.get('more_info', {}).get('square_image', '') or ''
                image = image.replace('150x150', '500x500')
                
                results.append({
                    "query": track_name,
                    "name": html.unescape(name),
                    "artist": html.unescape(artist),
                    "image": image,
                    "stream_url": stream_url,
                    "duration": item.get('duration', '') or item.get('more_info', {}).get('duration', '0')
                })
        except:
            continue
    
    return jsonify({
        "success": True,
        "total": len(results),
        "tracks": results
    })

@app.after_request
def after_request(response):
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization')
    response.headers.add('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE,OPTIONS')
    return response

def get_spotify_token():
    try:
        scraper = cloudscraper.create_scraper()
        response = scraper.get(
            'https://open.spotify.com/get_access_token?reason=transport&productType=web_player',
            headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'application/json',
                'Referer': 'https://open.spotify.com/',
                'spotify-app-version': '1.2.30.1135',
                'app-platform': 'WebPlayer'
            },
            timeout=5
        )
        if response.status_code == 200:
            return response.json().get('accessToken')
    except Exception as e:
        print(f"Error getting Spotify token: {e}")
    return None

def fetch_spotify_tracks_api(playlist_id, token):
    tracks = []
    offset = 0
    limit = 100
    scraper = cloudscraper.create_scraper()
    while True:
        try:
            response = scraper.get(
                f'https://api.spotify.com/v1/playlists/{playlist_id}/tracks?offset={offset}&limit={limit}&fields=items(track(name,id,artists(name),album(images))),next&market=IN',
                headers={
                    'Authorization': f'Bearer {token}',
                    'User-Agent': 'Mozilla/5.0'
                },
                timeout=5
            )
            if response.status_code != 200:
                break
            data = response.json()
            items = data.get('items', [])
            if not items:
                break
            for item in items:
                track_data = item.get('track')
                if not track_data:
                    continue
                name = (track_data.get('name') or '').strip()
                artists = track_data.get('artists', [])
                artist = artists[0].get('name', '').strip() if artists else 'Unknown Artist'
                images = track_data.get('album', {}).get('images', [])
                image = images[0].get('url', '') if images else ''
                track_id = track_data.get('id', '')
                
                if name:
                    tracks.append({
                        "id": track_id if track_id else str(hash(f"{name}_{artist}")),
                        "name": name,
                        "artist": artist,
                        "image": image
                    })
            if not data.get('next'):
                break
            offset += limit
        except Exception as e:
            print(f"Error fetching API tracks: {e}")
            break
    return tracks

@app.route('/test-spotify', methods=['GET'])
def test_spotify():
    playlist_id = '37i9dQZF1DWXRqP4y8JdFk'
    
    token = get_spotify_token()
    token_status = "SUCCESS" if token else "FAILED"
    
    embed_url = f"https://open.spotify.com/embed/playlist/{playlist_id}"
    scraper = cloudscraper.create_scraper()
    response = scraper.get(
        embed_url,
        headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept-Language': 'en-US,en;q=0.9',
        },
        timeout=10
    )
    
    html = response.text
    match_next = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html)
    
    tracks_preview = []
    keys_found = []
    status = None
    title = None
    tracks_count = 0
    
    if match_next:
        data = json.loads(match_next.group(1))
        pageProps = data.get('props', {}).get('pageProps', {})
        status = pageProps.get('status')
        title = pageProps.get('title')
        
        entity = pageProps.get('state', {}).get('data', {}).get('entity', {})
        keys_found = list(entity.keys())
        
        track_list = entity.get('trackList', []) or entity.get('tracks', [])
        tracks_count = len(track_list)
        for item in track_list[:5]:
            tracks_preview.append({
                "title": item.get('title') or item.get('name'),
                "subtitle": item.get('subtitle') or item.get('artist')
            })
            
    return jsonify({
        "token_status": token_status,
        "embed_status_code": response.status_code,
        "next_data_found": bool(match_next),
        "props_status": status,
        "props_title": title,
        "entity_keys": keys_found,
        "tracks_preview": tracks_preview,
        "tracks_count": tracks_count
    })

@app.route('/spotify-playlist', methods=['GET'])
def get_spotify_playlist():
    url = request.args.get('url', '').strip()
    if not url:
        return jsonify({"success": False, "error": "Missing URL"}), 400
    
    playlist_id = None
    match = re.search(r'playlist/([a-zA-Z0-9]+)', url)
    if match:
        playlist_id = match.group(1)
        
    if not playlist_id:
        return jsonify({"success": False, "error": "Invalid Spotify playlist URL"}), 400
        
    # 1. Try Web API first using anonymous token
    token = get_spotify_token()
    if token:
        tracks = fetch_spotify_tracks_api(playlist_id, token)
        if tracks:
            return jsonify({
                "success": True,
                "name": "Spotify Playlist",
                "tracks": tracks
            })
            
    # 2. Try Embed scraping as a fallback
    try:
        query_params = ""
        if '?' in url:
            query_params = url[url.index('?'):]
            
        embed_url = f"https://open.spotify.com/embed/playlist/{playlist_id}{query_params}"
        scraper = cloudscraper.create_scraper()
        response = scraper.get(
            embed_url,
            headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept-Language': 'en-US,en;q=0.9',
            },
            timeout=10
        )
        
        if response.status_code == 200:
            html = response.text
            match_next = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html)
            if match_next:
                data = json.loads(match_next.group(1))
                entity = data.get('props', {}).get('pageProps', {}).get('state', {}).get('data', {}).get('entity', {})
                playlist_name = entity.get('name', 'Spotify Playlist')
                
                track_list = entity.get('trackList', []) or entity.get('tracks', [])
                
                tracks = []
                for item in track_list:
                    name = (item.get('title') or item.get('name') or '').strip()
                    artist = (item.get('subtitle') or item.get('artist') or 'Unknown Artist').strip()
                    image = (item.get('image') or '')
                    track_id = item.get('id', '')
                    
                    if name:
                        tracks.append({
                            "id": track_id if track_id else str(hash(f"{name}_{artist}")),
                            "name": name,
                            "artist": artist,
                            "image": image
                        })
                        
                if tracks:
                    return jsonify({
                        "success": True,
                        "name": playlist_name,
                        "tracks": tracks
                    })
                    
        return jsonify({"success": False, "error": "No tracks found in the playlist metadata (Make sure it is public)"}), 404
        
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=False)
