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

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=False)
