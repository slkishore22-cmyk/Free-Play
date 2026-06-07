from flask import Flask, jsonify, request
import requests
import re
import json

app = Flask(__name__)

def extract_playlist_id(url):
    match = re.search(r'playlist/([a-zA-Z0-9]+)', url)
    if match:
        return match.group(1)
    return None

def get_spotify_token():
    # Get anonymous Spotify token from their public endpoint
    # No credentials needed - this is what the web player uses
    response = requests.get(
        'https://open.spotify.com/get_access_token?reason=transport&productType=web_player',
        headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'application/json',
            'Referer': 'https://open.spotify.com/',
            'spotify-app-version': '1.2.30.1135',
            'app-platform': 'WebPlayer'
        },
        timeout=10
    )
    data = response.json()
    return data.get('accessToken')

def get_playlist_tracks(playlist_id):
    tracks = []
    
    try:
        # Get anonymous web player token - no credentials needed
        token = get_spotify_token()
        if not token:
            return []
        
        offset = 0
        limit = 100
        
        while True:
            response = requests.get(
                f'https://api.spotify.com/v1/playlists/{playlist_id}/tracks',
                headers={
                    'Authorization': f'Bearer {token}',
                    'User-Agent': 'Mozilla/5.0',
                },
                params={
                    'offset': offset,
                    'limit': limit,
                    'fields': 'items(track(name,artists(name),album(images))),next',
                    'market': 'IN'
                },
                timeout=15
            )
            
            if response.status_code != 200:
                print(f"Spotify API error: {response.status_code} {response.text}")
                break
            
            data = response.json()
            items = data.get('items', [])
            
            if not items:
                break
            
            for item in items:
                try:
                    track = item.get('track')
                    if not track:
                        continue
                    name = track.get('name', '').strip()
                    artists = track.get('artists', [])
                    artist = artists[0].get('name', '') if artists else ''
                    images = track.get('album', {}).get('images', [])
                    image = images[0].get('url', '') if images else ''
                    if name:
                        tracks.append({
                            'name': name,
                            'artist': artist,
                            'image': image,
                            'id': track.get('id', '')
                        })
                except:
                    continue
            
            # Check if more pages
            if not data.get('next'):
                break
            offset += limit
            print(f"Fetched {len(tracks)} tracks, getting next page...")
        
    except Exception as e:
        print(f"Error: {e}")
    
    print(f"Total tracks: {len(tracks)}")
    return tracks

@app.route('/')
def index():
    return jsonify({"service": "FreePlay Server", "status": "running"})

@app.route('/health')
def health():
    return jsonify({"status": "ok"})

@app.route('/playlist', methods=['GET'])
def get_playlist():
    url = request.args.get('url', '').strip()
    if not url:
        return jsonify({"success": False, "error": "Missing url"}), 400
    if 'spotify.com/playlist/' not in url:
        return jsonify({"success": False, "error": "Invalid Spotify URL"}), 400
    
    playlist_id = extract_playlist_id(url)
    if not playlist_id:
        return jsonify({"success": False, "error": "Invalid playlist ID"}), 400
    
    tracks = get_playlist_tracks(playlist_id)
    
    if not tracks:
        return jsonify({"success": False, "error": "Could not fetch playlist"}), 500
    
    return jsonify({
        "success": True,
        "playlist_id": playlist_id,
        "total_tracks": len(tracks),
        "tracks": tracks
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=False)
