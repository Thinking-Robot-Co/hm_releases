import time
import os
import csv
import datetime
import sys
import threading
import atexit
import glob
import socket
import shutil
import logging
from flask import Flask, Response, render_template, request, jsonify, send_from_directory

# --- Configuration ---
VERSION = "v16.1-STABLE"
RECORD_FOLDER = "recordings"
TEMPLATE_FOLDER = "templates"
GPS_LOG_INTERVAL = 1
PORT = 5001

# Discovery
DISCOVERY_PORT = 5002
MAGIC_WORD = "WHO_IS_RPI_CAM?"
RESPONSE_PREFIX = "I_AM_RPI_CAM"

# Camera Settings
CAM_WIDTH, CAM_HEIGHT = 1640, 1232
STREAM_WIDTH, STREAM_HEIGHT = 640, 480
FPS = 15.0 

# --- Logging Setup ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

if not os.path.exists(RECORD_FOLDER):
    os.makedirs(RECORD_FOLDER)

app = Flask(__name__, template_folder=TEMPLATE_FOLDER)

# --- Hardware Imports ---
try:
    import cv2
    from picamera2 import Picamera2
    from libcamera import Transform
    import numpy as np
    MISSING_LIB = None
except ImportError as e:
    MISSING_LIB = str(e)
    logging.error(f"Hardware libraries missing: {e}")

# --- Global State ---
frame_lock = threading.Lock()
latest_frame_jpeg = None
current_gps_data = {"lat": 0.0, "lon": 0.0, "accuracy": 0.0, "speed": 0.0}

# Thread Control Flags
app_running = True
req_start_rec = False 
req_stop_rec = False 
is_recording_active = False 

# ==========================================
# 1. DISCOVERY SERVICE
# ==========================================
def discovery_service():
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(('', DISCOVERY_PORT))
        reply = f"{RESPONSE_PREFIX}|{socket.gethostname()}".encode('utf-8')
        logging.info(f"Discovery Active on UDP {DISCOVERY_PORT}")
        
        while app_running:
            try:
                sock.settimeout(1.0)
                data, addr = sock.recvfrom(1024)
                if data.decode().strip() == MAGIC_WORD:
                    sock.sendto(reply, addr)
            except socket.timeout: continue
            except Exception: time.sleep(1)
    except Exception as e:
        logging.error(f"Discovery Failed: {e}")

# ==========================================
# 2. AUTONOMOUS CAMERA WORKER
# ==========================================
def camera_worker():
    global latest_frame_jpeg, is_recording_active, req_start_rec, req_stop_rec, current_gps_data
    
    video_writer = None
    csv_file = None
    csv_writer = None
    last_gps_time = 0
    last_print = 0

    if MISSING_LIB:
        logging.error("Camera Worker Disabled (Missing Libs)")
        return

    try:
        picam2 = Picamera2()
        config = picam2.create_video_configuration(
            main={"size": (CAM_WIDTH, CAM_HEIGHT), "format": "RGB888"},
            transform=Transform(hflip=True, vflip=True)
        )
        picam2.configure(config)
        picam2.start()
        logging.info("Camera Engine Started")
    except Exception as e:
        logging.critical(f"Camera Hardware Error: {e}")
        return

    while app_running:
        try:
            # --- Handle State Changes ---
            if req_start_rec:
                req_start_rec = False
                if not is_recording_active:
                    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                    v_path = os.path.join(RECORD_FOLDER, f"video_{ts}.mp4")
                    c_path = os.path.join(RECORD_FOLDER, f"gps_{ts}.csv")
                    
                    try:
                        fourcc = cv2.VideoWriter_fourcc(*'avc1')
                        video_writer = cv2.VideoWriter(v_path, fourcc, FPS, (STREAM_WIDTH, STREAM_HEIGHT))
                        if not video_writer.isOpened(): raise Exception("Codec Fail")
                    except:
                        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
                        video_writer = cv2.VideoWriter(v_path, fourcc, FPS, (STREAM_WIDTH, STREAM_HEIGHT))
                    
                    if video_writer.isOpened():
                        csv_file = open(c_path, 'w', newline='')
                        csv_writer = csv.writer(csv_file)
                        csv_writer.writerow(["Timestamp", "Lat", "Lon", "Acc", "Speed"])
                        is_recording_active = True
                        logging.info(f"RECORDING STARTED: {v_path}")

            if req_stop_rec:
                req_stop_rec = False
                if is_recording_active:
                    is_recording_active = False
                    if video_writer: video_writer.release()
                    if csv_file: csv_file.close()
                    video_writer = None
                    csv_file = None
                    logging.info("RECORDING STOPPED & SAVED")

            # --- Capture ---
            raw = picam2.capture_array()
            frame_sm = cv2.resize(raw, (STREAM_WIDTH, STREAM_HEIGHT))
            frame_bgr = cv2.cvtColor(frame_sm, cv2.COLOR_RGB2BGR)

            # --- Write ---
            if is_recording_active and video_writer:
                try:
                    video_writer.write(frame_bgr)
                    now = time.time()
                    if (now - last_gps_time) >= GPS_LOG_INTERVAL:
                        ts_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
                        csv_writer.writerow([
                            ts_str, current_gps_data['lat'], current_gps_data['lon'],
                            current_gps_data['accuracy'], current_gps_data['speed']
                        ])
                        csv_file.flush()
                        last_gps_time = now
                    
                    if (now - last_print) > 5:
                        logging.info(f"[REC] Active | GPS: {current_gps_data['lat']},{current_gps_data['lon']}")
                        last_print = now
                except Exception as e:
                    logging.error(f"Recording Write Error: {e}")

            # --- Encode ---
            ret, buf = cv2.imencode('.jpg', frame_bgr)
            if ret:
                with frame_lock:
                    latest_frame_jpeg = buf.tobytes()

        except Exception as e:
            logging.error(f"Frame Loop Error: {e}")
            time.sleep(0.1)

    if picam2: picam2.stop()
    if video_writer: video_writer.release()
    if csv_file: csv_file.close()

threading.Thread(target=discovery_service, daemon=True).start()
threading.Thread(target=camera_worker, daemon=True).start()

# ==========================================
# 3. FLASK ROUTES
# ==========================================
@app.route('/')
def index():
    return render_template('index.html', version=VERSION, missing_lib=MISSING_LIB)

@app.route('/video_feed')
def video_feed():
    def generate():
        while True:
            with frame_lock:
                frame = latest_frame_jpeg
            if frame:
                yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')
            time.sleep(0.066)
    return Response(generate(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/api/start_record')
def start_record():
    global req_start_rec
    if not is_recording_active:
        req_start_rec = True
    return "OK"

@app.route('/api/stop_record', methods=['POST'])
def stop_record():
    global req_stop_rec
    # Log the IP of who requested the stop for debugging "Ghost Stops"
    logging.info(f"STOP REQUEST RECEIVED FROM: {request.remote_addr}")
    if is_recording_active:
        req_stop_rec = True
    return "OK"

@app.route('/api/capture_photo')
def capture_photo():
    with frame_lock:
        if latest_frame_jpeg is None: return "ERROR"
        data = latest_frame_jpeg
    
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(RECORD_FOLDER, f"img_{ts}.jpg")
    
    nparr = np.frombuffer(data, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    txt = f"GPS: {current_gps_data['lat']:.5f}, {current_gps_data['lon']:.5f}"
    cv2.putText(img, txt, (10, STREAM_HEIGHT-20), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0,255,0), 2)
    cv2.imwrite(path, img)
    
    gps_path = os.path.join(RECORD_FOLDER, f"gps_{ts}.csv")
    try:
        with open(gps_path, 'w', newline='') as f:
            w = csv.writer(f)
            w.writerow(["Timestamp", "Lat", "Lon", "Acc", "Speed"])
            t_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
            w.writerow([t_str, current_gps_data['lat'], current_gps_data['lon'], 0, 0])
            w.writerow([t_str, current_gps_data['lat'], current_gps_data['lon'], 0, 0])
    except: pass

    return "OK"

@app.route('/api/update_gps', methods=['POST'])
def update_gps():
    global current_gps_data
    if request.json: current_gps_data = request.json
    return "OK"

@app.route('/api/status')
def get_status():
    space = 0
    try: space = round(shutil.disk_usage(RECORD_FOLDER).free / (2**30), 2)
    except: pass
    return jsonify({
        "status": "RECORDING" if is_recording_active else "STANDBY",
        "storage_free_gb": space,
        "is_recording": is_recording_active
    })

@app.route('/api/list_media')
def list_media():
    v = glob.glob(os.path.join(RECORD_FOLDER, "video_*.mp4"))
    i = glob.glob(os.path.join(RECORD_FOLDER, "img_*.jpg"))
    files = sorted(v + i, key=os.path.getmtime, reverse=True)
    res = []
    for f in files:
        n = os.path.basename(f)
        try: s = round(os.path.getsize(f)/(1024*1024), 2)
        except: s = 0
        res.append({"name": n, "type": "video" if "video" in n else "image", "size": s})
    return jsonify(res)

@app.route('/api/download/<path:filename>')
def download(filename):
    return send_from_directory(RECORD_FOLDER, filename, as_attachment=True)

@app.route('/api/delete_file', methods=['POST'])
def delete_file():
    n = request.json.get('filename', '')
    p = os.path.join(RECORD_FOLDER, n)
    if os.path.exists(p) and RECORD_FOLDER in os.path.abspath(p):
        os.remove(p)
        csv = p.replace("video_", "gps_").replace("img_", "gps_").replace(".mp4", ".csv").replace(".jpg", ".csv")
        if os.path.exists(csv): os.remove(csv)
        return "OK"
    return "ERROR"

@app.route('/data/<path:filename>')
def serve(filename):
    return send_from_directory(RECORD_FOLDER, filename)

if __name__ == '__main__':
    print(f"SMART HELMET {VERSION} STARTED on {PORT}")
    try:
        app.run(host='0.0.0.0', port=PORT, ssl_context='adhoc', debug=False, threaded=True)
    finally:
        app_running = False