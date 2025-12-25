#!/usr/bin/env python3
"""
Smart Helmet Camera System v27.2-REDUCED-SIZE
Reduced video file size + keeps uploaded files with tick mark
"""
import time
import os
import csv
import datetime
import sys
import threading
import glob
import socket
import shutil
import logging
import cv2
import numpy as np
import subprocess

from flask import Flask, Response, render_template, request, jsonify, send_from_directory
from picamera2 import Picamera2
from picamera2.encoders import H264Encoder
from libcamera import Transform

# Import uploader module
from uploader import upload_to_cloud

# --- CONFIGURATION ---
VERSION = "v27.2-REDUCED-SIZE"
RECORD_FOLDER = "recordings"
PORT = 5001
CAM_WIDTH, CAM_HEIGHT = 1640, 1232 
FPS = 30.0
STREAM_HEIGHT = 480

# Video bitrate - REDUCED for smaller file sizes
VIDEO_BITRATE = 4000000  # 4 Mbps (was 12 Mbps) - 3x smaller files!

# Device ID for cloud uploads
DEVICE_ID = "smart_hm_02"

# Discovery
DISCOVERY_PORT = 5002
MAGIC_WORD = "WHO_IS_RPI_CAM?"
RESPONSE_PREFIX = "I_AM_RPI_CAM"

# Force Standard Colors
os.environ["LIBCAMERA_RPI_TUNING_FILE"] = "/usr/share/libcamera/ipa/rpi/vc4/imx219.json"

# --- LOGGING ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

# Suppress SSL EOF errors
class SuppressedLogFilter(logging.Filter):
    def filter(self, record):
        return 'SSLEOFError' not in str(record.getMessage())

werkzeug_logger = logging.getLogger('werkzeug')
werkzeug_logger.addFilter(SuppressedLogFilter())

if not os.path.exists(RECORD_FOLDER):
    os.makedirs(RECORD_FOLDER)

app = Flask(__name__)

# --- GLOBAL STATE ---
frame_lock = threading.Lock()
frame_condition = threading.Condition(frame_lock)
latest_frame_jpeg = None
current_gps_data = {"lat": 0.0, "lon": 0.0, "accuracy": 0.0, "speed": 0.0}

app_running = True
req_start_rec = False 
req_stop_rec = False 
is_recording_active = False 

# Track upload status
upload_status = {}
upload_status_lock = threading.Lock()

# ==========================================
# SSL CERTIFICATE GENERATOR
# ==========================================
def generate_ssl_certificates():
    """Generate self-signed SSL certificates if they don't exist"""
    if os.path.exists('cert.pem') and os.path.exists('key.pem'):
        logging.info("[SSL] ✓ Certificates already exist")
        return True

    logging.info("[SSL] Generating self-signed certificates...")
    try:
        cmd = [
            'openssl', 'req', '-x509', '-newkey', 'rsa:2048',
            '-keyout', 'key.pem', '-out', 'cert.pem',
            '-days', '365', '-nodes',
            '-subj', '/C=IN/ST=Maharashtra/L=Nagpur/O=ThinkingRobot/OU=SmartHelmet/CN=raspberrypi'
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode == 0 and os.path.exists('cert.pem') and os.path.exists('key.pem'):
            os.chmod('key.pem', 0o600)
            os.chmod('cert.pem', 0o600)
            logging.info("[SSL] ✓ Certificates generated successfully")
            return True
        else:
            logging.warning(f"[SSL] ✗ Certificate generation failed: {result.stderr}")
            return False
    except Exception as e:
        logging.warning(f"[SSL] ✗ Could not generate certificates: {e}")
        return False

# ==========================================
# VIDEO CONVERTER
# ==========================================
def convert_to_mp4_safe(h264_path, mp4_path):
    """Convert H264 to MP4 in background with low priority"""
    time.sleep(2.0)

    try:
        logging.info(f"[CONVERT] Starting: {h264_path}")
        cmd = [
            "nice", "-n", "19",
            "ffmpeg", "-r", str(int(FPS)), "-i", h264_path, 
            "-c:v", "copy", "-y", mp4_path
        ]

        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        if os.path.exists(mp4_path) and os.path.getsize(mp4_path) > 0:
            os.remove(h264_path)
            logging.info(f"[CONVERT] ✓ Success: {mp4_path}")
        else:
            logging.error("[CONVERT] ✗ Failed")

    except Exception as e:
        logging.error(f"[CONVERT] ✗ Error: {e}")

# ==========================================
# CAMERA WORKER
# ==========================================
def camera_worker():
    """Main camera thread - handles recording and preview"""
    global latest_frame_jpeg, is_recording_active, req_start_rec, req_stop_rec, current_gps_data

    logging.info(f"[CAMERA] Thread started")

    csv_file = None
    csv_writer = None
    last_gps_time = 0
    current_h264_name = None
    current_mp4_name = None
    current_encoder = None

    try:
        logging.info(f"[CAMERA] Initializing Picamera2...")
        picam2 = Picamera2()

        config = picam2.create_video_configuration(
            main={"size": (CAM_WIDTH, CAM_HEIGHT), "format": "YUV420"},
            lores={"size": (640, 480), "format": "YUV420"}, 
            transform=Transform(hflip=True, vflip=True),
            controls={"FrameRate": FPS},
            buffer_count=6 
        )
        config["sensor"]["output_size"] = (CAM_WIDTH, CAM_HEIGHT)

        logging.info(f"[CAMERA] Configuring...")
        picam2.configure(config)

        logging.info(f"[CAMERA] Starting camera...")
        picam2.start()

        picam2.set_controls({"ScalerCrop": (0, 0, 3280, 2464)})

        logging.info(f"[CAMERA] ✓ Ready!")
        time.sleep(0.5)

    except Exception as e:
        logging.critical(f"[CAMERA] ✗ Hardware Error: {e}")
        return

    while app_running:
        try:
            # --- START RECORDING ---
            if req_start_rec:
                req_start_rec = False
                if not is_recording_active:
                    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                    current_h264_name = os.path.join(RECORD_FOLDER, f"temp_{ts}.h264")
                    current_mp4_name = os.path.join(RECORD_FOLDER, f"video_{ts}.mp4")
                    c_path = os.path.join(RECORD_FOLDER, f"gps_{ts}.csv")

                    try:
                        logging.info(f"[RECORD] Creating encoder...")
                        # REDUCED BITRATE for smaller files
                        current_encoder = H264Encoder(bitrate=VIDEO_BITRATE, profile="high")

                        logging.info(f"[RECORD] Starting: {current_h264_name}")
                        logging.info(f"[RECORD] Bitrate: {VIDEO_BITRATE/1000000} Mbps")
                        picam2.start_recording(current_encoder, current_h264_name)

                        csv_file = open(c_path, 'w', newline='')
                        csv_writer = csv.writer(csv_file)
                        csv_writer.writerow(["Timestamp", "Lat", "Lon", "Acc", "Speed"])

                        is_recording_active = True
                        logging.info(f"[RECORD] ✓ STARTED")

                    except Exception as rec_err:
                        logging.error(f"[RECORD] ✗ Start failed: {rec_err}")
                        is_recording_active = False

            # --- STOP RECORDING ---
            if req_stop_rec:
                req_stop_rec = False
                if is_recording_active:
                    try:
                        logging.info(f"[RECORD] Stopping...")
                        picam2.stop_recording()
                        logging.info(f"[RECORD] ✓ Stopped")

                        # FIX: Restart camera (Picamera2 bug)
                        logging.info(f"[CAMERA] Restarting...")
                        picam2.start()
                        logging.info(f"[CAMERA] ✓ Restarted!")

                    except Exception as stop_err:
                        logging.error(f"[RECORD] ✗ Stop error: {stop_err}")

                    is_recording_active = False

                    if csv_file: 
                        csv_file.close()
                    csv_file = None
                    current_encoder = None

                    logging.info(f"[RECORD] Cleaned up")

                    if current_h264_name and current_mp4_name:
                        t = threading.Thread(target=convert_to_mp4_safe, args=(current_h264_name, current_mp4_name))
                        t.daemon = True
                        t.start()
                        logging.info(f"[RECORD] Conversion started")

                    time.sleep(0.05)

            # --- PREVIEW CAPTURE ---
            try:
                raw_yuv = picam2.capture_array("lores")
                if raw_yuv is not None:
                    frame_bgr = cv2.cvtColor(raw_yuv, cv2.COLOR_YUV2BGR_I420)

                    # GPS LOGGING
                    if is_recording_active:
                        now = time.time()
                        if (now - last_gps_time) >= 1.0:
                            ts_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
                            if csv_writer:
                                csv_writer.writerow([
                                    ts_str, current_gps_data['lat'], current_gps_data['lon'],
                                    current_gps_data['accuracy'], current_gps_data['speed']
                                ])
                                csv_file.flush()
                            last_gps_time = now

                    # UPDATE WEB FEED
                    ret, buf = cv2.imencode('.jpg', frame_bgr)
                    if ret:
                        with frame_lock:
                            latest_frame_jpeg = buf.tobytes()
                            frame_condition.notify_all()

            except Exception:
                pass

            time.sleep(0.005)

        except Exception as e:
            logging.error(f"[CAMERA] Loop error: {e}")
            time.sleep(0.1)

    logging.info("[CAMERA] Shutting down...")
    if picam2: 
        try:
            if is_recording_active:
                logging.info("[CAMERA] Stopping active recording...")
                picam2.stop_recording()
        except:
            pass
        logging.info("[CAMERA] Stopping camera...")
        picam2.stop()
        logging.info("[CAMERA] ✓ Stopped")

# ==========================================
# DISCOVERY SERVICE
# ==========================================
def discovery_service():
    """UDP discovery service for network scanning"""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(('', DISCOVERY_PORT))
        reply = f"{RESPONSE_PREFIX}|{socket.gethostname()}".encode('utf-8')
        logging.info(f"[DISCOVERY] Started on port {DISCOVERY_PORT}")
        while app_running:
            try:
                sock.settimeout(1.0)
                data, addr = sock.recvfrom(1024)
                if data.decode().strip() == MAGIC_WORD:
                    sock.sendto(reply, addr)
            except socket.timeout: 
                continue
            except Exception: 
                time.sleep(1)
    except Exception as e:
        logging.error(f"[DISCOVERY] Error: {e}")

# ==========================================
# FLASK ROUTES
# ==========================================

@app.route('/')
def index():
    """Serve main HTML page"""
    return render_template('index.html', version=VERSION)

@app.route('/video_feed')
def video_feed():
    """MJPEG stream for live preview"""
    def generate():
        while True:
            with frame_condition:
                if not frame_condition.wait(timeout=1.0):
                    pass
                frame = latest_frame_jpeg

            if frame:
                try:
                    yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')
                except Exception:
                    break 
    return Response(generate(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/api/start_record')
def start_record():
    """Start recording"""
    global req_start_rec
    if not is_recording_active:
        req_start_rec = True
    return "OK"

@app.route('/api/stop_record', methods=['POST'])
def stop_record():
    """Stop recording"""
    global req_stop_rec
    logging.info(f"STOP REQUEST FROM: {request.remote_addr}")
    if is_recording_active:
        req_stop_rec = True
    return "OK"

@app.route('/api/capture_photo')
def capture_photo():
    """Capture single photo"""
    with frame_lock:
        if latest_frame_jpeg is None: 
            return "ERROR"
        data = latest_frame_jpeg

    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(RECORD_FOLDER, f"img_{ts}.jpg")

    nparr = np.frombuffer(data, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    txt = f"GPS: {current_gps_data['lat']:.5f}, {current_gps_data['lon']:.5f}"
    cv2.putText(img, txt, (10, STREAM_HEIGHT-20), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0,255,0), 2)
    cv2.imwrite(path, img)
    return "OK"

@app.route('/api/update_gps', methods=['POST'])
def update_gps():
    """Update GPS data from browser"""
    global current_gps_data
    if request.json: 
        current_gps_data = request.json
    return "OK"

@app.route('/api/status')
def get_status():
    """Get system status"""
    space = 0
    try: 
        space = round(shutil.disk_usage(RECORD_FOLDER).free / (2**30), 2)
    except: 
        pass
    return jsonify({
        "status": "RECORDING" if is_recording_active else "STANDBY",
        "storage_free_gb": space,
        "is_recording": is_recording_active
    })

@app.route('/api/list_media')
def list_media():
    """List all videos and images including temp/uploaded files"""
    # Get MP4 videos
    v = glob.glob(os.path.join(RECORD_FOLDER, "video_*.mp4"))
    v += glob.glob(os.path.join(RECORD_FOLDER, "failed_upload_*.mp4"))
    v += glob.glob(os.path.join(RECORD_FOLDER, "uploaded_*.mp4"))  # NEW: Include uploaded files

    # Get temp H264 files (still converting)
    temp = glob.glob(os.path.join(RECORD_FOLDER, "temp_*.h264"))

    # Get images
    i = glob.glob(os.path.join(RECORD_FOLDER, "img_*.jpg"))

    files = sorted(v + i + temp, key=os.path.getmtime, reverse=True)
    res = []
    for f in files:
        n = os.path.basename(f)
        try: 
            s = round(os.path.getsize(f)/(1024*1024), 2)
        except: 
            s = 0
        is_failed = n.startswith('failed_upload_')
        is_converting = n.startswith('temp_') and n.endswith('.h264')
        is_uploaded = n.startswith('uploaded_')  # NEW: Check if uploaded

        # Check upload status
        upload_info = None
        with upload_status_lock:
            if n in upload_status:
                upload_info = upload_status[n]

        res.append({
            "name": n, 
            "type": "video" if ("video" in n or "failed" in n or "temp" in n or "uploaded" in n) else "image", 
            "size": s,
            "failed": is_failed,
            "converting": is_converting,
            "uploaded": is_uploaded,  # NEW: Upload flag
            "upload_status": upload_info
        })
    return jsonify(res)

@app.route('/api/upload_cloud', methods=['POST'])
def api_upload_cloud():
    """Upload video to cloud"""
    try:
        data = request.json
        filename = data.get('filename')
        if not filename:
            logging.error("[API] ✗ No filename provided")
            return jsonify({"success": False, "error": "No filename"})

        logging.info(f"[API] Upload request for: {filename}")

        # Set initial status
        with upload_status_lock:
            upload_status[filename] = {"status": "uploading", "message": "Uploading..."}

        video_path = os.path.join(RECORD_FOLDER, filename)
        csv_filename = filename.replace('video_', 'gps_').replace('.mp4', '.csv')
        csv_path = os.path.join(RECORD_FOLDER, csv_filename)

        # Run upload in background
        def upload_thread():
            success, message = upload_to_cloud(video_path, csv_path, DEVICE_ID)

            with upload_status_lock:
                if success:
                    upload_status[filename] = {"status": "success", "message": message}
                    # Remove from status after 3 seconds
                    threading.Timer(3.0, lambda: upload_status.pop(filename, None)).start()
                else:
                    upload_status[filename] = {"status": "failed", "message": message}
                    # Rename to failed
                    try:
                        failed_name = filename.replace('video_', 'failed_upload_')
                        new_path = os.path.join(RECORD_FOLDER, failed_name)
                        if os.path.exists(video_path):
                            os.rename(video_path, new_path)
                            logging.info(f"[API] Renamed to: {failed_name}")

                        if os.path.exists(csv_path):
                            failed_csv = csv_filename.replace('gps_', 'failed_upload_gps_')
                            os.rename(csv_path, os.path.join(RECORD_FOLDER, failed_csv))
                    except Exception as e:
                        logging.error(f"[API] Rename failed: {e}")

        t = threading.Thread(target=upload_thread)
        t.daemon = True
        t.start()

        return jsonify({"success": True, "message": "Upload started"})
    except Exception as e:
        logging.error(f"[API] Upload endpoint error: {e}")
        return jsonify({"success": False, "error": str(e)})

@app.route('/api/download/<path:filename>')
def download(filename):
    """Download file"""
    return send_from_directory(RECORD_FOLDER, filename, as_attachment=True)

@app.route('/api/delete_file', methods=['POST'])
def delete_file():
    """Delete file and associated CSV"""
    n = request.json.get('filename', '')
    p = os.path.join(RECORD_FOLDER, n)
    if os.path.exists(p) and RECORD_FOLDER in os.path.abspath(p):
        os.remove(p)
        # Delete CSV too
        csv_name = n.replace("video_", "gps_").replace("img_", "gps_")
        csv_name = csv_name.replace("failed_upload_", "failed_upload_gps_")
        csv_name = csv_name.replace("uploaded_", "uploaded_gps_")  # NEW: Handle uploaded files
        csv_name = csv_name.replace("temp_", "gps_")
        csv_name = csv_name.replace(".mp4", ".csv").replace(".jpg", ".csv").replace(".h264", ".csv")
        csv_path = os.path.join(RECORD_FOLDER, csv_name)
        if os.path.exists(csv_path): 
            os.remove(csv_path)
        return "OK"
    return "ERROR"

@app.route('/data/<path:filename>')
def serve(filename):
    """Serve recording files"""
    return send_from_directory(RECORD_FOLDER, filename)

# ==========================================
# MAIN
# ==========================================
if __name__ == '__main__':
    from werkzeug.serving import WSGIRequestHandler
    WSGIRequestHandler.protocol_version = "HTTP/1.1"

    print("=" * 70)
    print(f"  SMART HELMET {VERSION}")
    print("=" * 70)
    print(f"  Port: {PORT}")
    print(f"  Device ID: {DEVICE_ID}")
    print(f"  Recording: {RECORD_FOLDER}")
    print(f"  Video Bitrate: {VIDEO_BITRATE/1000000} Mbps (reduced for smaller files)")
    print(f"  Upload URL: https://centrix.co.in/v_api/upload")
    print("=" * 70)

    # Generate SSL certificates if needed
    ssl_available = generate_ssl_certificates()

    logging.info(f"[MAIN] Starting threads...")
    threading.Thread(target=discovery_service, daemon=True).start()
    threading.Thread(target=camera_worker, daemon=True).start()

    logging.info(f"[MAIN] Starting Flask on port {PORT}...")

    try:
        if ssl_available:
            logging.info(f"[MAIN] Starting with HTTPS (SSL enabled)")
            app.run(host='0.0.0.0', port=PORT, ssl_context=('cert.pem', 'key.pem'), debug=False, threaded=True)
        else:
            logging.warning(f"[MAIN] Starting with HTTP (SSL not available)")
            app.run(host='0.0.0.0', port=PORT, debug=False, threaded=True)
    except KeyboardInterrupt:
        logging.info("[MAIN] Keyboard interrupt")
    finally:
        logging.info("[MAIN] Shutting down...")
        app_running = False
        time.sleep(1)
        logging.info("[MAIN] ✓ Done")
