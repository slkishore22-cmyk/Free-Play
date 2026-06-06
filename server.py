from flask import Flask, jsonify, request
from flask_cors import CORS
import requests
import re

app = Flask(__name__)
CORS(app)

def extract_playlist_id(url):
    match = re.search(r'playlist/([a-zA-Z0-9]+)', url)
    if match:
        return match.group(1)
    return None

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
            
        from bs4 import BeautifulSoup
        import json
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
    
    result, error = scrape_spotify_playlist(url)
    
    if error or not result:
        return jsonify({"success": False, "error": error or "Could not fetch playlist"}), 500
    
    return jsonify({
        "success": True,
        "playlist_id": playlist_id,
        "name": result['name'],
        "description": result['description'],
        "cover": result['cover'],
        "total_tracks": len(result['tracks']),
        "tracks": result['tracks']
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=False)
