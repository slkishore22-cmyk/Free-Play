from flask import Flask, jsonify, request
import requests
import re

app = Flask(__name__)

def extract_playlist_id(url):
    match = re.search(r'playlist/([a-zA-Z0-9]+)', url)
    if match:
        return match.group(1)
    return None

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
            response = requests.get(url, headers=headers, timeout=10)
            data = response.json()
            
            if not data.get('success'):
                break
                
            items = data.get('trackList', [])
            if not items:
                break
                
            for item in items:
                tracks.append({
                    'name': item.get('title', ''),
                    'artist': item.get('artists', ''),
                    'image': item.get('cover', ''),
                    'id': item.get('id', '')
                })
            
            # Check if more pages
            next_offset = data.get('nextOffset', None)
            if not next_offset:
                break
            offset = next_offset
            
        except Exception as e:
            print(f"Error at offset {offset}: {e}")
            break
    
    return tracks

@app.route('/')
def index():
    return jsonify({"service": "FreePlay Spotify Scraper", "status": "running"})

@app.route('/health')
def health():
    return jsonify({"status": "ok"})

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
