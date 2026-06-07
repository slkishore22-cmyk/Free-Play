from flask import Flask, jsonify, request
import requests
import re
import json

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
        if not results:
            return jsonify({"success": False, "error": "No results found"}), 404
        
        top = results[0]
        encrypted_url = top.get('more_info', {}).get('encrypted_media_url', '')
        
        stream_url = None
        if encrypted_url:
            stream_url = decrypt_jiosaavn_url(encrypted_url)
        
        return jsonify({
            "success": True,
            "name": top.get('title', ''),
            "artist": top.get('subtitle', ''),
            "image": top.get('image', '').replace('150x150', '500x500'),
            "stream_url": stream_url,
            "duration": top.get('more_info', {}).get('duration', '0')
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
    for track_name in track_names[:50]:  # limit to 50 at a time
        try:
            data = get_jiosaavn_search(track_name)
            if data and data.get('results'):
                top = data['results'][0]
                encrypted_url = top.get('more_info', {}).get('encrypted_media_url', '')
                stream_url = decrypt_jiosaavn_url(encrypted_url) if encrypted_url else None
                results.append({
                    "query": track_name,
                    "name": top.get('title', ''),
                    "artist": top.get('subtitle', ''),
                    "image": top.get('image', '').replace('150x150', '500x500'),
                    "stream_url": stream_url,
                    "duration": top.get('more_info', {}).get('duration', '0')
                })
        except:
            continue
    
    return jsonify({
        "success": True,
        "total": len(results),
        "tracks": results
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=False)
