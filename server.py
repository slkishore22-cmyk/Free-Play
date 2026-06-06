from flask import Flask, jsonify, request
import requests
from bs4 import BeautifulSoup
import json
import re

app = Flask(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
}

def extract_playlist_id(url):
    match = re.search(r'playlist/([a-zA-Z0-9]+)', url)
    if match:
        return match.group(1)
    return None

def scrape_spotify_playlist(playlist_url):
    try:
        response = requests.get(playlist_url, headers=HEADERS, timeout=10)
        if response.status_code != 200:
            return None, f"Failed to fetch: {response.status_code}"
        soup = BeautifulSoup(response.text, 'html.parser')
        tracks = []
        json_ld = soup.find('script', type='application/ld+json')
        if json_ld:
            try:
                data = json.loads(json_ld.string)
                if 'track' in data:
                    for track in data['track']:
                        name = track.get('name', '')
                        artist = ''
                        if 'byArtist' in track:
                            artist_data = track['byArtist']
                            if isinstance(artist_data, list):
                                artist = artist_data[0].get('name', '')
                            elif isinstance(artist_data, dict):
                                artist = artist_data.get('name', '')
                        if name:
                            tracks.append({
                                'name': name,
                                'artist': artist,
                                'image': track.get('image', ''),
                            })
                if tracks:
                    return tracks, None
            except Exception as e:
                print(f"Error: {e}")
        if not tracks:
            return None, "Could not extract tracks. Playlist may be private."
        return tracks, None
    except Exception as e:
        return None, str(e)

@app.route('/')
def index():
    return jsonify({"service": "FreePlay Spotify Scraper", "status": "running"})

@app.route('/health')
def health():
    return jsonify({"status": "ok"})

@app.route('/playlist')
def get_playlist():
    url = request.args.get('url', '').strip()
    if not url:
        return jsonify({"success": False, "error": "Missing url parameter"}), 400
    if 'spotify.com/playlist/' not in url:
        return jsonify({"success": False, "error": "Invalid Spotify playlist URL"}), 400
    playlist_id = extract_playlist_id(url)
    if not playlist_id:
        return jsonify({"success": False, "error": "Could not extract playlist ID"}), 400
    tracks, error = scrape_spotify_playlist(url)
    if error:
        return jsonify({"success": False, "error": error}), 500
    return jsonify({"success": True, "playlist_id": playlist_id, "total_tracks": len(tracks), "tracks": tracks})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=False)
