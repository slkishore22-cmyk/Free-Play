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
        response = requests.get(playlist_url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(response.text, 'html.parser')
        tracks = []
        
        # Method 1: JSON-LD
        json_ld = soup.find('script', type='application/ld+json')
        if json_ld:
            try:
                data = json.loads(json_ld.string)
                if 'track' in data:
                    for track in data['track']:
                        name = track.get('name', '')
                        artist = ''
                        if 'byArtist' in track:
                            a = track['byArtist']
                            artist = a[0].get('name','') if isinstance(a,list) else a.get('name','')
                        if name:
                            tracks.append({'name': name, 'artist': artist, 'image': track.get('image','')})
            except:
                pass
        
        # Method 2: Next.js data
        if not tracks:
            next_data = soup.find('script', id='__NEXT_DATA__')
            if next_data:
                try:
                    data = json.loads(next_data.string)
                    items = data['props']['pageProps']['state']['data']['entity']['trackList']
                    for item in items:
                        tracks.append({
                            'name': item.get('title',''),
                            'artist': item.get('subtitle',''),
                            'image': item.get('image','')
                        })
                except:
                    pass

        # Method 3: og:description meta tag parsing
        if not tracks:
            desc = soup.find('meta', property='og:description')
            if desc:
                return None, "Playlist is private or Spotify blocked scraping"

        if not tracks:
            return None, "Could not extract tracks"
            
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
