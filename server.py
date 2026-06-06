from flask import Flask, jsonify, request
import requests
from bs4 import BeautifulSoup
import json
import re

app = Flask(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}

def extract_playlist_id(url):
    match = re.search(r'playlist/([a-zA-Z0-9]+)', url)
    if match:
        return match.group(1)
    return None

def scrape_spotify_playlist(playlist_url):
    try:
        playlist_id = extract_playlist_id(playlist_url)
        
        # Use Spotify embed API - returns JSON directly
        embed_url = f"https://open.spotify.com/oembed?url=spotify:playlist:{playlist_id}"
        
        # Try Spotify's internal embed page which has track data
        page_url = f"https://open.spotify.com/embed/playlist/{playlist_id}"
        
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json",
            "Referer": "https://open.spotify.com/",
        }
        
        response = requests.get(page_url, headers=headers, timeout=15)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        tracks = []
        
        # Extract from script tags containing track data
        scripts = soup.find_all('script')
        for script in scripts:
            if script.string and 'trackList' in str(script.string):
                try:
                    # Find JSON data in script
                    text = script.string
                    start = text.find('{')
                    end = text.rfind('}') + 1
                    if start != -1:
                        data = json.loads(text[start:end])
                        # Navigate to trackList
                        track_list = data.get('trackList', [])
                        for track in track_list:
                            tracks.append({
                                'name': track.get('title', ''),
                                'artist': track.get('subtitle', ''),
                                'image': track.get('image', '')
                            })
                except:
                    pass
            
            # Also check for initialState or props
            if script.string and ('initialState' in str(script.string) or 'Spotify.Entity' in str(script.string)):
                try:
                    text = script.string
                    # Extract JSON
                    match = re.search(r'Spotify\.Entity\s*=\s*({.*?});', text, re.DOTALL)
                    if match:
                        data = json.loads(match.group(1))
                        items = data.get('tracks', {}).get('items', [])
                        for item in items:
                            track = item.get('track', {})
                            tracks.append({
                                'name': track.get('name', ''),
                                'artist': track.get('artists', [{}])[0].get('name', ''),
                                'image': track.get('album', {}).get('images', [{}])[0].get('url', '')
                            })
                except:
                    pass
        
        if not tracks:
            return None, "Could not extract tracks from embed page"
            
        return tracks, None
        
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
    tracks, error = scrape_spotify_playlist(url)
    if error:
        return jsonify({"success": False, "error": error}), 500
    return jsonify({
        "success": True,
        "playlist_id": playlist_id,
        "total_tracks": len(tracks),
        "tracks": tracks
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=False)
