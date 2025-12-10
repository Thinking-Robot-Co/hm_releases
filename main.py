import time
import os
import csv
import datetime
import sys
import threading
import atexit
import glob
import socket  # Added for Discovery
import numpy as np
from flask import Flask, Response, render_template_string, request, jsonify, send_from_directory

# --- Version 11.0: Full Feature Restoration + Discovery ---
VERSION = "v11.0"

# --- Hardware Imports ---
try:
    import cv2
    from picamera2 import Picamera2
    from libcamera import Transform
    MISSING_LIB = None
except ImportError as e:
    MISSING_LIB = str(e)
    print(f"\nCRITICAL ERROR: {e}")

# --- Configuration ---
RECORD_FOLDER = "recordings"
GPS_LOG_INTERVAL = 1
PORT = 5001

# Discovery Config
DISCOVERY_PORT = 5002
MAGIC_WORD = "WHO_IS_RPI_CAM?"
RESPONSE_PREFIX = "I_AM_RPI_CAM"

# Resolutions
CAM_WIDTH, CAM_HEIGHT = 1640, 1232
STREAM_WIDTH, STREAM_HEIGHT = 640, 480
FPS = 24.0

if not os.path.exists(RECORD_FOLDER):
    os.makedirs(RECORD_FOLDER)

app = Flask(__name__)

# --- Global State ---
picam2 = None
rec_lock = threading.Lock()
cam_lock = threading.Lock()
is_recording = False
video_writer = None
csv_file = None
csv_writer = None
recording_start_time = 0
last_gps_log_time = 0
current_gps_data = {"lat": 0.0, "lon": 0.0, "accuracy": 0.0, "speed": 0.0}
system_status = "Ready"
last_error = ""

# ==========================================
# 1. DISCOVERY SERVICE (New Feature)
# ==========================================
def discovery_service():
    """Listens for broadcasts and replies with 'I_AM_RPI_CAM|MyHostname'"""
    print(f"[{VERSION}] Discovery Service Started on UDP {DISCOVERY_PORT}")
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(('', DISCOVERY_PORT))
        
        hostname = socket.gethostname()
        reply_msg = f"{RESPONSE_PREFIX}|{hostname}"
        
        while True:
            try:
                data, addr = sock.recvfrom(1024)
                message = data.decode('utf-8').strip()
                
                if message == MAGIC_WORD:
                    sock.sendto(reply_msg.encode('utf-8'), addr)
                    print(f"Discovery: Sent identification to {addr[0]}")
            except Exception as e:
                print(f"Discovery Error: {e}")
                time.sleep(1)
    except Exception as e:
        print(f"Could not start discovery: {e}")

# Start Discovery Background Thread
discovery_thread = threading.Thread(target=discovery_service, daemon=True)
discovery_thread.start()


# ==========================================
# 2. HTML UI (Original Full Features)
# ==========================================
HTML_UI = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>RPi Cam {VERSION}</title>
    <!-- Leaflet CSS for Maps -->
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
    <style>
        body {{ font-family: sans-serif; background: #1a1a1a; color: #eee; text-align: center; margin: 0; padding: 0; padding-bottom: 80px; }}
        
        /* Header */
        .header {{ padding: 15px; background: #333; margin-bottom: 10px; box-shadow: 0 2px 5px rgba(0,0,0,0.5); }}
        h2 {{ margin: 0; font-size: 1.2rem; color: #fff; }}

        /* Live Monitor */
        .monitor-container {{ position: relative; width: 100%; max-width: 640px; margin: 0 auto; background: #000; border: 1px solid #444; }}
        .monitor {{ width: 100%; height: auto; display: block; min-height: 240px; }}
        
        /* Controls */
        .control-panel {{ padding: 20px; max-width: 600px; margin: 0 auto; }}
        .btn-group {{ display: flex; gap: 15px; justify-content: center; }}
        button {{
            padding: 15px 0; font-size: 18px; border: none; border-radius: 8px;
            cursor: pointer; font-weight: bold; width: 48%; transition: transform 0.1s;
            color: white; text-transform: uppercase; letter-spacing: 1px;
        }}
        button:active {{ transform: scale(0.98); }}
        button:disabled {{ opacity: 0.3; cursor: not-allowed; }}
        #startBtn {{ background: linear-gradient(135deg, #28a745, #218838); }}
        #stopBtn {{ background: linear-gradient(135deg, #dc3545, #c82333); }}
        
        /* Recordings List */
        .library-section {{ max-width: 640px; margin: 20px auto; text-align: left; padding: 10px; }}
        .library-header {{ font-size: 1.1rem; border-bottom: 1px solid #444; padding-bottom: 5px; margin-bottom: 10px; color: #aaa; }}
        .video-item {{ 
            background: #2a2a2a; padding: 15px; margin-bottom: 10px; border-radius: 8px; 
            display: flex; justify-content: space-between; align-items: center; cursor: pointer;
        }}
        .video-item:hover {{ background: #333; }}
        .vid-name {{ font-family: monospace; font-size: 14px; }}
        .vid-icon {{ font-size: 20px; }}

        /* Playback Modal */
        #playbackModal {{
            display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%;
            background: rgba(0,0,0,0.95); z-index: 200; overflow-y: auto;
        }}
        .modal-content {{ max-width: 800px; margin: 20px auto; padding: 10px; }}
        .close-btn {{ float: right; font-size: 30px; cursor: pointer; color: #fff; margin-bottom: 10px; }}
        video {{ width: 100%; border-radius: 8px; margin-bottom: 10px; }}
        #map {{ height: 300px; width: 100%; border-radius: 8px; background: #222; }}

        /* Status Bar */
        .status-bar {{
            position: fixed; bottom: 0; left: 0; width: 100%; height: 50px;
            background: #000; border-top: 1px solid #444;
            display: flex; justify-content: space-between; align-items: center;
            padding: 0 15px; box-sizing: border-box; font-size: 12px; z-index: 100;
        }}
        .stat-val {{ font-weight: bold; font-family: monospace; font-size: 14px; color: #0f0; }}
        .rec-time {{ color: #ff4444; display: none; }}
    </style>
    <!-- Leaflet JS -->
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
</head>
<body>

    <div class="header">
        <h2>RPi Mobile Link ({VERSION})</h2>
    </div>

    {{% if missing_lib %}}
    <div style="background:#900; padding:20px; margin:20px;">
        <h3>SYSTEM ERROR</h3>
        <p>Libraries missing. Run: sudo apt install python3-picamera2 python3-opencv</p>
    </div>
    {{% else %}}
    
    <!-- LIVE VIEW -->
    <div class="monitor-container">
        <img src="/video_feed" class="monitor" id="camStream" />
    </div>

    <!-- CONTROLS -->
    <div class="control-panel">
        <div class="btn-group">
            <button id="startBtn" onclick="startRecording()">Start Rec</button>
            <button id="stopBtn" onclick="stopRecording()" disabled>Stop Rec</button>
        </div>
    </div>

    <!-- LIBRARY -->
    <div class="library-section">
        <div class="library-header">Recordings Library</div>
        <div id="videoList">Loading...</div>
    </div>

    <!-- PLAYBACK MODAL -->
    <div id="playbackModal">
        <div class="modal-content">
            <span class="close-btn" onclick="closeModal()">&times;</span>
            <h3 id="modalTitle">Video Playback</h3>
            <video id="videoPlayer" controls playsinline></video>
            <div id="map"></div>
        </div>
    </div>

    <!-- STATUS BAR -->
    <div class="status-bar">
        <div>GPS: <span id="gpsStat" class="stat-val" style="color:#888">WAIT</span></div>
        <div>
             <span id="sysMsg" style="color:#ccc;">Ready</span>
             <span id="recTimer" class="stat-val rec-time">00:00</span>
        </div>
    </div>
    {{% endif %}}

    <script>
        let recStartTime = 0;
        let recInterval = null;
        let map = null;
        let marker = null;
        let gpsTrack = []; // Array of {{time, lat, lon}}

        // --- GPS Logic ---
        function initGPS() {{
            if ("geolocation" in navigator) {{
                navigator.geolocation.watchPosition(
                    (pos) => {{
                        const d = {{
                            lat: pos.coords.latitude, lon: pos.coords.longitude,
                            accuracy: pos.coords.accuracy, speed: pos.coords.speed || 0
                        }};
                        document.getElementById('gpsStat').innerText = "OK"; 
                        document.getElementById('gpsStat').style.color = "#0f0";
                        fetch('/update_gps', {{
                            method: 'POST', headers: {{'Content-Type': 'application/json'}},
                            body: JSON.stringify(d)
                        }});
                    }},
                    (err) => {{ console.log(err); }}, {{ enableHighAccuracy: true }}
                );
            }}
        }}

        // --- Recording Logic ---
        async function startRecording() {{
            const res = await fetch('/start_record');
            if (await res.text() === "OK") updateRecUI(true);
        }}

        async function stopRecording() {{
            const res = await fetch('/stop_record');
            if (await res.text() === "OK") {{
                updateRecUI(false);
                setTimeout(loadLibrary, 1000); // Refresh list
            }}
        }}

        function updateRecUI(isRecording) {{
            const startBtn = document.getElementById('startBtn');
            const stopBtn = document.getElementById('stopBtn');
            const timer = document.getElementById('recTimer');
            const msg = document.getElementById('sysMsg');

            if (isRecording) {{
                startBtn.disabled = true; stopBtn.disabled = false;
                timer.style.display = "block"; msg.style.display = "none";
                recStartTime = Date.now();
                recInterval = setInterval(() => {{
                    const diff = Math.floor((Date.now() - recStartTime) / 1000);
                    const m = Math.floor(diff / 60).toString().padStart(2,'0');
                    const s = (diff % 60).toString().padStart(2,'0');
                    timer.innerText = `${{m}}:${{s}}`;
                }}, 1000);
            }} else {{
                startBtn.disabled = false; stopBtn.disabled = true;
                timer.style.display = "none"; msg.style.display = "block"; msg.innerText = "Saved";
                if(recInterval) clearInterval(recInterval);
            }}
        }}

        // --- Library & Map Logic ---
        async function loadLibrary() {{
            const r = await fetch('/list_recordings');
            const files = await r.json();
            const list = document.getElementById('videoList');
            list.innerHTML = "";
            
            if (files.length === 0) list.innerHTML = "<div style='color:#666'>No recordings found.</div>";
            
            files.forEach(f => {{
                const div = document.createElement('div');
                div.className = "video-item";
                div.innerHTML = `<span class="vid-icon">â?¶</span> <span class="vid-name">${{f}}</span>`;
                div.onclick = () => openPlayback(f);
                list.appendChild(div);
            }});
        }}

        async function openPlayback(filename) {{
            document.getElementById('playbackModal').style.display = 'block';
            document.getElementById('modalTitle').innerText = filename;
            
            const vid = document.getElementById('videoPlayer');
            vid.src = `/data/${{filename}}`;
            
            // Fetch GPS Data
            gpsTrack = [];
            try {{
                const csvName = filename.replace("video_", "gps_").replace(".mp4", ".csv");
                const res = await fetch(`/data/${{csvName}}`);
                if(res.ok) {{
                    const text = await res.text();
                    parseCSV(text);
                    initMap();
                }} else {{
                    document.getElementById('map').innerHTML = "No GPS data for this video.";
                }}
            }} catch(e) {{ console.error(e); }}
        }}
        
        function parseCSV(text) {{
            const lines = text.trim().split('\\n');
            if(lines.length < 2) return;
            
            // Assume first row (after header) is start time (t=0)
            const startRow = lines[1].split(',');
            // Fix: Handle timestamps with or without millis
            const startTime = new Date(startRow[0]).getTime();
            
            gpsTrack = lines.slice(1).map(line => {{
                const cols = line.split(',');
                if(cols.length < 3) return null;
                const t = new Date(cols[0]).getTime();
                return {{
                    relTime: (t - startTime) / 1000, // Seconds from start
                    lat: parseFloat(cols[1]),
                    lon: parseFloat(cols[2])
                }};
            }}).filter(p => p !== null);
        }}

        function initMap() {{
            if(gpsTrack.length === 0) return;
            
            const startPos = [gpsTrack[0].lat, gpsTrack[0].lon];
            
            // Cleanup old map
            if(map) {{ map.remove(); map = null; }}
            
            // Create Map
            map = L.map('map').setView(startPos, 16);
            L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
                attribution: '&copy; OpenStreetMap'
            }}).addTo(map);
            
            // Draw Path
            const latlngs = gpsTrack.map(p => [p.lat, p.lon]);
            L.polyline(latlngs, {{color: 'red'}}).addTo(map);
            
            marker = L.marker(startPos).addTo(map);
            
            // Sync Video
            const vid = document.getElementById('videoPlayer');
            vid.ontimeupdate = () => {{
                if (gpsTrack.length === 0) return;
                const ct = vid.currentTime;
                // Find closest point (Simple O(N) is fine for short clips)
                let closest = gpsTrack[0];
                let minDiff = Math.abs(closest.relTime - ct);
                
                for(let i=1; i<gpsTrack.length; i++) {{
                    const diff = Math.abs(gpsTrack[i].relTime - ct);
                    if(diff < minDiff) {{
                        minDiff = diff;
                        closest = gpsTrack[i];
                    }}
                }}
                
                if(closest) {{
                    marker.setLatLng([closest.lat, closest.lon]);
                    // Optional: map.panTo([closest.lat, closest.lon]);
                }}
            }};
        }}

        function closeModal() {{
            document.getElementById('playbackModal').style.display = 'none';
            document.getElementById('videoPlayer').pause();
            document.getElementById('videoPlayer').src = "";
            if(map) {{ map.remove(); map = null; }}
        }}

        // Status Polling
        setInterval(async () => {{
            try {{
                const r = await fetch('/status');
                const j = await r.json();
                if(!recInterval) document.getElementById('sysMsg').innerText = j.status;
            }} catch(e) {{}}
        }}, 2000);

        window.onload = () => {{ initGPS(); loadLibrary(); }};
    </script>
</body>
</html>
"""

# ==========================================
# 3. CAMERA & SERVER LOGIC
# ==========================================
def init_camera():
    global picam2, last_error
    if MISSING_LIB: return

    with cam_lock:
        try:
            if picam2 is None:
                picam2 = Picamera2()
            else:
                try: picam2.stop()
                except: pass

            transform = Transform(hflip=True, vflip=True)
            config = picam2.create_video_configuration(
                main={"size": (CAM_WIDTH, CAM_HEIGHT), "format": "RGB888"},
                transform=transform
            )
            picam2.configure(config)
            picam2.start()
            print(f"[{VERSION}] Camera Started!")
            last_error = ""
            
        except Exception as e:
            last_error = str(e)
            print(f"[{VERSION}] INIT ERROR: {e}")

def get_frames():
    global picam2, is_recording, video_writer, csv_writer, last_gps_log_time, last_error
    
    while True:
        if MISSING_LIB or last_error:
            time.sleep(1)
            continue

        try:
            with cam_lock:
                if picam2:
                    raw = picam2.capture_array()
                else:
                    time.sleep(0.1)
                    continue
            
            frame = cv2.resize(raw, (STREAM_WIDTH, STREAM_HEIGHT))
            frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)

            with rec_lock:
                if is_recording and video_writer:
                    video_writer.write(frame)
                    
                    # GPS Log
                    now = time.time()
                    if (now - last_gps_log_time) >= GPS_LOG_INTERVAL:
                        if csv_writer:
                            ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
                            csv_writer.writerow([
                                ts, current_gps_data['lat'], current_gps_data['lon'],
                                current_gps_data['accuracy'], current_gps_data['speed']
                            ])
                            csv_file.flush()
                            last_gps_log_time = now

            ret, buf = cv2.imencode('.jpg', frame)
            yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + buf.tobytes() + b'\r\n')

        except Exception as e:
            time.sleep(0.01)

def cleanup():
    global picam2
    if picam2:
        try: picam2.stop()
        except: pass

atexit.register(cleanup)

# ==========================================
# 4. FLASK ROUTES (Endpoints)
# ==========================================
@app.route('/')
def index():
    return render_template_string(HTML_UI, missing_lib=MISSING_LIB)

@app.route('/video_feed')
def video_feed():
    return Response(get_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/start_record')
def start_record():
    global is_recording, video_writer, csv_file, csv_writer, last_gps_log_time, system_status
    
    with rec_lock:
        if not is_recording and not MISSING_LIB:
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            v_name = os.path.join(RECORD_FOLDER, f"video_{ts}.mp4")
            c_name = os.path.join(RECORD_FOLDER, f"gps_{ts}.csv")
            
            try:
                # Browser-friendly H.264
                fourcc = cv2.VideoWriter_fourcc(*'avc1')
                video_writer = cv2.VideoWriter(v_name, fourcc, FPS, (STREAM_WIDTH, STREAM_HEIGHT))
                if not video_writer.isOpened():
                     # Fallback
                    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
                    video_writer = cv2.VideoWriter(v_name, fourcc, FPS, (STREAM_WIDTH, STREAM_HEIGHT))
            except:
                fourcc = cv2.VideoWriter_fourcc(*'mp4v')
                video_writer = cv2.VideoWriter(v_name, fourcc, FPS, (STREAM_WIDTH, STREAM_HEIGHT))
            
            csv_file = open(c_name, 'w', newline='')
            csv_writer = csv.writer(csv_file)
            csv_writer.writerow(["Timestamp", "Lat", "Lon", "Acc", "Speed"])
            
            is_recording = True
            last_gps_log_time = 0
            system_status = "Recording..."
            print(f"Recording: {v_name}")
    return "OK"

@app.route('/stop_record')
def stop_record():
    global is_recording, video_writer, csv_file, system_status
    
    with rec_lock:
        if is_recording:
            is_recording = False
            if video_writer:
                video_writer.release()
                video_writer = None
            if csv_file:
                csv_file.close()
                csv_file = None
            system_status = "Saved"
            print("Stopped.")
    return "OK"

@app.route('/update_gps', methods=['POST'])
def update_gps():
    global current_gps_data
    if request.json:
        current_gps_data = request.json
    return "OK"

@app.route('/status')
def get_status():
    return jsonify({"status": system_status})

@app.route('/list_recordings')
def list_recordings():
    files = glob.glob(os.path.join(RECORD_FOLDER, "video_*.mp4"))
    files.sort(key=os.path.getmtime, reverse=True)
    filenames = [os.path.basename(f) for f in files]
    return jsonify(filenames)

@app.route('/data/<path:filename>')
def serve_data(filename):
    return send_from_directory(RECORD_FOLDER, filename)

if __name__ == '__main__':
    init_camera()
    print(f"Server {VERSION} running on port {PORT}")
    app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0
    app.run(host='0.0.0.0', port=PORT, ssl_context='adhoc', debug=False, threaded=True)
