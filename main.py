#!/usr/bin/env python3
"""
Smart Helmet Camera System v27.13-ULTIMATE

ALL FIXES:
- GPS tracking from browser ✓
- Orphaned file recovery ✓
- Recording timer smooth ✓
- Upload renaming ✓
- GPS frequency 5s ✓
- GPS CSV lookup after rename ✓
- Batch grouping by timestamp ✓
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
import re
import cv2
import numpy as np
import subprocess
from flask import Flask, Response, render_template, request, jsonify, send_from_directory
from picamera2 import Picamera2
from picamera2.encoders import H264Encoder
from libcamera import Transform
from uploader import upload_to_cloud

VERSION = "v27.13-ULTIMATE"
RECORD_FOLDER = "recordings"
PORT = 5001
CAM_WIDTH, CAM_HEIGHT = 1640, 1232
FPS = 30.0
STREAM_HEIGHT = 480
VIDEO_BITRATE = 1500000

AUTO_CHUNK_ENABLED = True
CHUNK_SIZE_MB = 60
CHUNK_CHECK_INTERVAL = 10

AUDIO_ENABLED_DEFAULT = True
AUDIO_SAMPLE_RATE = 44100
AUDIO_CHANNELS = 1
USB_MIC_DEVICE = "hw:3,0"

GPS_RECORD_INTERVAL = 5.0

DEVICE_ID = "smart_hm_02"

def get_serial_number():
    """Get Raspberry Pi Serial Number"""
    try:
        with open('/proc/cpuinfo', 'r') as f:
            for line in f:
                if line.startswith('Serial'):
                    return line.split(':')[1].strip()
    except:
        pass
    return "smart_hm_02"

DEVICE_ID = get_serial_number()
logging.info(f"[SYSTEM] Device ID: {DEVICE_ID}")

DISCOVERY_PORT = 5002
MAGIC_WORD = "WHO_IS_RPI_CAM?"
RESPONSE_PREFIX = "I_AM_RPI_CAM"

os.environ["LIBCAMERA_RPI_TUNING_FILE"] = "/usr/share/libcamera/ipa/rpi/vc4/imx219.json"

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

class SuppressedLogFilter(logging.Filter):
    def filter(self, record):
        return 'SSLEOFError' not in str(record.getMessage())

werkzeug_logger = logging.getLogger('werkzeug')
werkzeug_logger.addFilter(SuppressedLogFilter())

if not os.path.exists(RECORD_FOLDER):
    os.makedirs(RECORD_FOLDER)

app = Flask(__name__)

frame_lock = threading.Lock()
frame_condition = threading.Condition(frame_lock)
latest_frame_jpeg = None
current_gps_data = {"lat": 0.0, "lon": 0.0, "accuracy": 0.0, "speed": 0.0}
app_running = True
req_start_rec = False
req_stop_rec = False
is_recording_active = False
recording_start_time = None
audio_enabled = AUDIO_ENABLED_DEFAULT
audio_process = None
upload_status = {}
upload_status_lock = threading.Lock()
chunk_number = 0
last_chunk_check = 0
current_recording_files = []
current_recording_lock = threading.Lock()
converting_files = set()
converting_files_lock = threading.Lock()
incomplete_files = set()
incomplete_files_lock = threading.Lock()

def extract_timestamp(filename):
    """Extract timestamp from filename (e.g., video_20251228_112233_chunk000.mp4 -> 20251228_112233)"""
    match = re.search(r'(\d{8}_\d{6})', filename)
    return match.group(1) if match else None

def recover_orphaned_files():
    """Find and mark orphaned temp_*.h264 files from previous crash"""
    orphaned = glob.glob(os.path.join(RECORD_FOLDER, "temp_*.h264"))

    if not orphaned:
        logging.info("[RECOVERY] ✓ No orphaned files found")
        return

    logging.info(f"[RECOVERY] Found {len(orphaned)} orphaned file(s)")

    for temp_file in orphaned:
        try:
            temp_name = os.path.basename(temp_file)
            incomplete_name = temp_name.replace('temp_', 'incomplete_')
            incomplete_path = os.path.join(RECORD_FOLDER, incomplete_name)

            os.rename(temp_file, incomplete_path)

            with incomplete_files_lock:
                incomplete_files.add(incomplete_name)

            csv_name = temp_name.replace('temp_', 'gps_').replace('.h264', '.csv')
            csv_path = os.path.join(RECORD_FOLDER, csv_name)
            if os.path.exists(csv_path):
                incomplete_csv = csv_name.replace('gps_', 'incomplete_gps_')
                incomplete_csv_path = os.path.join(RECORD_FOLDER, incomplete_csv)
                os.rename(csv_path, incomplete_csv_path)

            audio_name = temp_name.replace('temp_', 'audio_').replace('.h264', '.wav')
            audio_path = os.path.join(RECORD_FOLDER, audio_name)
            if os.path.exists(audio_path):
                incomplete_audio = audio_name.replace('audio_', 'incomplete_audio_')
                incomplete_audio_path = os.path.join(RECORD_FOLDER, incomplete_audio)
                os.rename(audio_path, incomplete_audio_path)

            logging.info(f"[RECOVERY] ⚠️ Marked as incomplete: {incomplete_name}")

        except Exception as e:
            logging.error(f"[RECOVERY] Error processing {temp_file}: {e}")

    logging.info(f"[RECOVERY] ✓ Marked {len(orphaned)} orphaned files as incomplete")

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

def start_audio_recording(audio_file):
    """Start audio recording using arecord"""
    global audio_process
    if not audio_enabled:
        logging.info("[AUDIO] Audio disabled by user")
        return None

    try:
        check_cmd = ["arecord", "-l"]
        result = subprocess.run(check_cmd, capture_output=True, text=True)
        if f"card {USB_MIC_DEVICE.split(':')[1].split(',')[0]}" not in result.stdout:
            logging.warning(f"[AUDIO] USB microphone not found at {USB_MIC_DEVICE}, skipping audio")
            return None

        cmd = [
            "arecord",
            "-D", USB_MIC_DEVICE,
            "-f", "S16_LE",
            "-c", str(AUDIO_CHANNELS),
            "-r", str(AUDIO_SAMPLE_RATE),
            audio_file
        ]

        audio_process = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        logging.info(f"[AUDIO] Started recording to {audio_file}")
        return audio_process
    except Exception as e:
        logging.error(f"[AUDIO] Failed to start: {e}")
        return None

def stop_audio_recording():
    """Stop audio recording"""
    global audio_process
    if audio_process:
        try:
            audio_process.terminate()
            audio_process.wait(timeout=5)
            logging.info("[AUDIO] Stopped recording")
        except Exception as e:
            logging.error(f"[AUDIO] Error stopping: {e}")
            try:
                audio_process.kill()
            except:
                pass
        finally:
            audio_process = None

def convert_and_merge(h264_path, audio_path, mp4_path):
    """Convert H264 to MP4 and merge with audio"""
    h264_name = os.path.basename(h264_path)
    mp4_name = os.path.basename(mp4_path)

    with converting_files_lock:
        converting_files.add(mp4_name)

    time.sleep(2.0)

    try:
        logging.info(f"[CONVERT] Starting: {h264_path}")
        has_audio = os.path.exists(audio_path) and os.path.getsize(audio_path) > 1000

        if has_audio:
            cmd = [
                "nice", "-n", "19",
                "ffmpeg",
                "-r", str(int(FPS)),
                "-i", h264_path,
                "-i", audio_path,
                "-c:v", "copy",
                "-c:a", "aac",
                "-b:a", "128k",
                "-shortest",
                "-y", mp4_path
            ]
            logging.info("[CONVERT] Merging video + audio")
        else:
            cmd = [
                "nice", "-n", "19",
                "ffmpeg",
                "-r", str(int(FPS)),
                "-i", h264_path,
                "-c:v", "copy",
                "-y", mp4_path
            ]
            logging.info("[CONVERT] Video only (no audio)")

        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        if os.path.exists(mp4_path) and os.path.getsize(mp4_path) > 0:
            os.remove(h264_path)
            if has_audio:
                os.remove(audio_path)
            logging.info(f"[CONVERT] ✓ Success: {mp4_path}")
        else:
            logging.error("[CONVERT] ✗ Failed")

    except Exception as e:
        logging.error(f"[CONVERT] ✗ Error: {e}")

    finally:
        with converting_files_lock:
            converting_files.discard(mp4_name)


def camera_worker():
    """Main camera thread - handles recording with audio"""
    global latest_frame_jpeg, is_recording_active, req_start_rec, req_stop_rec, current_gps_data
    global chunk_number, last_chunk_check, recording_start_time, audio_process
    global current_recording_files

    logging.info(f"[CAMERA] Thread started")

    csv_file = None
    csv_writer = None
    last_gps_time = 0
    current_h264_name = None
    current_audio_name = None
    current_mp4_name = None
    current_encoder = None
    recording_session_start = None

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
            if req_start_rec:
                req_start_rec = False
                if not is_recording_active:
                    chunk_number = 0
                    recording_session_start = datetime.datetime.now()
                    recording_start_time = time.time()
                    last_chunk_check = time.time()
                    ts = recording_session_start.strftime("%Y%m%d_%H%M%S")

                    current_h264_name = os.path.join(RECORD_FOLDER, f"temp_{ts}_chunk{chunk_number:03d}.h264")
                    current_audio_name = os.path.join(RECORD_FOLDER, f"audio_{ts}_chunk{chunk_number:03d}.wav")
                    current_mp4_name = os.path.join(RECORD_FOLDER, f"video_{ts}_chunk{chunk_number:03d}.mp4")
                    c_path = os.path.join(RECORD_FOLDER, f"gps_{ts}_chunk{chunk_number:03d}.csv")

                    try:
                        logging.info(f"[RECORD] Creating encoder...")
                        current_encoder = H264Encoder(bitrate=VIDEO_BITRATE, profile="high")

                        logging.info(f"[RECORD] Starting video chunk {chunk_number}: {current_h264_name}")
                        picam2.start_recording(current_encoder, current_h264_name)
                        start_audio_recording(current_audio_name)

                        csv_file = open(c_path, 'w', newline='')
                        csv_writer = csv.writer(csv_file)
                        csv_writer.writerow(["Timestamp", "Lat", "Lon", "Acc", "Speed"])

                        is_recording_active = True

                        with current_recording_lock:
                            current_recording_files.append({
                                "h264": os.path.basename(current_h264_name),
                                "mp4": os.path.basename(current_mp4_name),
                                "started": recording_session_start.strftime("%Y-%m-%d %H:%M:%S")
                            })

                        logging.info(f"[RECORD] ✓ STARTED (Audio: {audio_enabled})")

                    except Exception as rec_err:
                        logging.error(f"[RECORD] ✗ Start failed: {rec_err}")
                        is_recording_active = False

            if is_recording_active and AUTO_CHUNK_ENABLED:
                now = time.time()
                if (now - last_chunk_check) >= CHUNK_CHECK_INTERVAL:
                    last_chunk_check = now
                    try:
                        if os.path.exists(current_h264_name):
                            file_size_mb = os.path.getsize(current_h264_name) / (1024 * 1024)
                            if file_size_mb >= CHUNK_SIZE_MB:
                                logging.info(f"[CHUNK] Rotating chunk {chunk_number} at {file_size_mb:.1f} MB")
                                picam2.stop_recording()
                                stop_audio_recording()
                                if csv_file:
                                    csv_file.close()
                                    csv_file = None

                                if current_h264_name and current_mp4_name:
                                    t = threading.Thread(
                                        target=convert_and_merge,
                                        args=(current_h264_name, current_audio_name, current_mp4_name)
                                    )
                                    t.daemon = True
                                    t.start()

                                chunk_number += 1
                                ts = recording_session_start.strftime("%Y%m%d_%H%M%S")
                                current_h264_name = os.path.join(RECORD_FOLDER, f"temp_{ts}_chunk{chunk_number:03d}.h264")
                                current_audio_name = os.path.join(RECORD_FOLDER, f"audio_{ts}_chunk{chunk_number:03d}.wav")
                                current_mp4_name = os.path.join(RECORD_FOLDER, f"video_{ts}_chunk{chunk_number:03d}.mp4")
                                c_path = os.path.join(RECORD_FOLDER, f"gps_{ts}_chunk{chunk_number:03d}.csv")

                                current_encoder = H264Encoder(bitrate=VIDEO_BITRATE, profile="high")
                                picam2.start_recording(current_encoder, current_h264_name)
                                start_audio_recording(current_audio_name)

                                csv_file = open(c_path, 'w', newline='')
                                csv_writer = csv.writer(csv_file)
                                csv_writer.writerow(["Timestamp", "Lat", "Lon", "Acc", "Speed"])

                                with current_recording_lock:
                                    current_recording_files.append({
                                        "h264": os.path.basename(current_h264_name),
                                        "mp4": os.path.basename(current_mp4_name),
                                        "started": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                    })

                                logging.info(f"[CHUNK] ✓ Started chunk {chunk_number}")

                    except Exception as chunk_err:
                        logging.error(f"[CHUNK] ✗ Size check failed: {chunk_err}")

            if req_stop_rec:
                req_stop_rec = False
                if is_recording_active:
                    try:
                        logging.info(f"[RECORD] Stopping (total chunks: {chunk_number + 1})...")
                        picam2.stop_recording()
                        stop_audio_recording()
                        logging.info(f"[RECORD] ✓ Stopped")

                        logging.info(f"[CAMERA] Restarting...")
                        picam2.start()
                        logging.info(f"[CAMERA] ✓ Restarted!")

                    except Exception as stop_err:
                        logging.error(f"[RECORD] ✗ Stop error: {stop_err}")

                    is_recording_active = False
                    recording_start_time = None
                    if csv_file:
                        csv_file.close()
                        csv_file = None
                    current_encoder = None

                    with current_recording_lock:
                        current_recording_files = []

                    logging.info(f"[RECORD] Cleaned up")

                    if current_h264_name and current_mp4_name:
                        t = threading.Thread(
                            target=convert_and_merge,
                            args=(current_h264_name, current_audio_name, current_mp4_name)
                        )
                        t.daemon = True
                        t.start()
                        logging.info(f"[RECORD] Conversion started")

            time.sleep(0.05)

            try:
                raw_yuv = picam2.capture_array("lores")
                if raw_yuv is not None:
                    frame_bgr = cv2.cvtColor(raw_yuv, cv2.COLOR_YUV2BGR_I420)

                    if is_recording_active:
                        now = time.time()
                        if (now - last_gps_time) >= GPS_RECORD_INTERVAL:
                            ts_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
                            if csv_writer:
                                csv_writer.writerow([
                                    ts_str, current_gps_data['lat'], current_gps_data['lon'],
                                    current_gps_data['accuracy'], current_gps_data['speed']
                                ])
                                csv_file.flush()
                            last_gps_time = now

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
                stop_audio_recording()
        except:
            pass
        logging.info("[CAMERA] Stopping camera...")
        picam2.stop()
        logging.info("[CAMERA] ✓ Stopped")

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


@app.route('/')
def index():
    return render_template('index.html', version=VERSION)

@app.route('/video_feed')
def video_feed():
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
    global req_start_rec
    if not is_recording_active:
        req_start_rec = True
    return "OK"

@app.route('/api/stop_record', methods=['POST'])
def stop_record():
    global req_stop_rec
    logging.info(f"STOP REQUEST FROM: {request.remote_addr}")
    if is_recording_active:
        req_stop_rec = True
    return "OK"

@app.route('/api/toggle_audio', methods=['POST'])
def toggle_audio():
    """Toggle audio recording on/off"""
    global audio_enabled
    data = request.json
    audio_enabled = data.get('enabled', True)
    logging.info(f"[AUDIO] Toggled: {audio_enabled}")
    return jsonify({"success": True, "audio_enabled": audio_enabled})

@app.route('/api/capture_photo')
def capture_photo():
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
    global current_gps_data
    if request.json:
        current_gps_data = request.json
        # logging.debug(f"[GPS] Update: {current_gps_data['lat']}, {current_gps_data['lon']}")
    return "OK"

@app.route('/api/status')
def get_status():
    """Get system status with recording timer, audio state, and current recording files"""
    space = 0
    try:
        space = round(shutil.disk_usage(RECORD_FOLDER).free / (2**30), 2)
    except:
        pass

    recording_time = 0
    if is_recording_active and recording_start_time:
        recording_time = int(time.time() - recording_start_time)

    current_files = []
    with current_recording_lock:
        for rec_file in current_recording_files:
            h264_path = os.path.join(RECORD_FOLDER, rec_file["h264"])
            size_mb = 0
            if os.path.exists(h264_path):
                size_mb = round(os.path.getsize(h264_path) / (1024 * 1024), 2)
            current_files.append({
                "name": rec_file["mp4"],
                "h264": rec_file["h264"],
                "size": size_mb,
                "started": rec_file["started"]
            })

    return jsonify({
        "status": "RECORDING" if is_recording_active else "STANDBY",
        "storage_free_gb": space,
        "is_recording": is_recording_active,
        "recording_time": recording_time,
        "audio_enabled": audio_enabled,
        "current_recording": current_files
    })

@app.route('/api/rename_file', methods=['POST'])
def rename_file():
    """Rename a single video file"""
    try:
        data = request.json
        old_name = data.get('old_name')
        new_name = data.get('new_name')

        if not old_name or not new_name:
            return jsonify({"success": False, "error": "Missing parameters"})

        new_name = new_name.strip()
        if not new_name.endswith('.mp4'):
            new_name += '.mp4'
        new_name = os.path.basename(new_name)

        old_path = os.path.join(RECORD_FOLDER, old_name)
        new_path = os.path.join(RECORD_FOLDER, new_name)

        if not os.path.exists(old_path):
            return jsonify({"success": False, "error": "File not found"})
        if os.path.exists(new_path):
            return jsonify({"success": False, "error": "File name already exists"})

        os.rename(old_path, new_path)

        old_csv = old_name.replace('video_', 'gps_').replace('.mp4', '.csv')
        new_csv = new_name.replace('video_', 'gps_').replace('.mp4', '.csv')
        old_csv_path = os.path.join(RECORD_FOLDER, old_csv)
        new_csv_path = os.path.join(RECORD_FOLDER, new_csv)

        if os.path.exists(old_csv_path):
            os.rename(old_csv_path, new_csv_path)

        logging.info(f"[RENAME] {old_name} → {new_name}")
        return jsonify({"success": True, "new_name": new_name})

    except Exception as e:
        logging.error(f"[RENAME] Error: {e}")
        return jsonify({"success": False, "error": str(e)})

@app.route('/api/rename_batch', methods=['POST'])
def rename_batch():
    """Rename all chunks in a batch/video session"""
    try:
        data = request.json
        base = data.get('base')
        new_name = data.get('new_name')

        if not base or not new_name:
            return jsonify({"success": False, "error": "Missing parameters"})

        new_name = new_name.strip().replace(' ', '_')
        new_name = new_name.replace('.mp4', '').replace('.csv', '')

        base_ts = extract_timestamp(base)
        if not base_ts:
            return jsonify({"success": False, "error": "Cannot extract timestamp from base"})

        chunks = glob.glob(os.path.join(RECORD_FOLDER, f"*{base_ts}_chunk*.mp4"))
        chunks += glob.glob(os.path.join(RECORD_FOLDER, f"*{base_ts}_chunk*.h264"))

        if not chunks:
            return jsonify({"success": False, "error": "No chunks found"})

        renamed_count = 0

        for old_path in chunks:
            old_filename = os.path.basename(old_path)

            if '_chunk' in old_filename:
                chunk_part = old_filename.split('_chunk')[1]
                chunk_num = chunk_part.split('.')[0]
                ext = old_filename.split('.')[-1]

                if ext == 'h264':
                    if 'incomplete_' in old_filename:
                        new_filename = f"incomplete_{new_name}_chunk{chunk_num}.h264"
                    else:
                        new_filename = f"temp_{new_name}_chunk{chunk_num}.h264"
                else:
                    if 'uploaded_' in old_filename:
                        new_filename = f"uploaded_{new_name}_chunk{chunk_num}.mp4"
                    elif 'failed_upload_' in old_filename:
                        new_filename = f"failed_upload_{new_name}_chunk{chunk_num}.mp4"
                    else:
                        new_filename = f"video_{new_name}_chunk{chunk_num}.mp4"

                new_path = os.path.join(RECORD_FOLDER, new_filename)

                if os.path.exists(new_path):
                    return jsonify({"success": False, "error": f"File {new_filename} already exists"})

                os.rename(old_path, new_path)
                renamed_count += 1

                if ext == 'mp4':
                    for prefix in ['gps_', 'uploaded_gps_', 'failed_upload_gps_']:
                        old_csv = old_filename.replace('video_', prefix).replace('uploaded_', prefix).replace('failed_upload_', prefix).replace('.mp4', '.csv')
                        old_csv_path = os.path.join(RECORD_FOLDER, old_csv)
                        if os.path.exists(old_csv_path):
                            new_csv = new_filename.replace('video_', prefix).replace('uploaded_', prefix).replace('failed_upload_', prefix).replace('.mp4', '.csv')
                            new_csv_path = os.path.join(RECORD_FOLDER, new_csv)
                            os.rename(old_csv_path, new_csv_path)
                            break
                elif ext == 'h264':
                    if 'incomplete_' in old_filename:
                        old_csv = old_filename.replace('incomplete_', 'incomplete_gps_').replace('.h264', '.csv')
                    else:
                        old_csv = old_filename.replace('temp_', 'gps_').replace('.h264', '.csv')
                    old_csv_path = os.path.join(RECORD_FOLDER, old_csv)
                    if os.path.exists(old_csv_path):
                        if 'incomplete_' in new_filename:
                            new_csv = new_filename.replace('incomplete_', 'incomplete_gps_').replace('.h264', '.csv')
                        else:
                            new_csv = new_filename.replace('temp_', 'gps_').replace('.h264', '.csv')
                        new_csv_path = os.path.join(RECORD_FOLDER, new_csv)
                        os.rename(old_csv_path, new_csv_path)

        logging.info(f"[BATCH RENAME] {base} → {new_name} ({renamed_count} files)")
        return jsonify({"success": True, "renamed_count": renamed_count, "new_base": f"video_{new_name}"})

    except Exception as e:
        logging.error(f"[BATCH RENAME] Error: {e}")
        return jsonify({"success": False, "error": str(e)})


@app.route('/api/list_media')
def list_media():
    """List media with batch grouping by TIMESTAMP (not prefix)"""
    v = glob.glob(os.path.join(RECORD_FOLDER, "video_*.mp4"))
    v += glob.glob(os.path.join(RECORD_FOLDER, "failed_upload_*.mp4"))
    v += glob.glob(os.path.join(RECORD_FOLDER, "uploaded_*.mp4"))
    temp = glob.glob(os.path.join(RECORD_FOLDER, "temp_*.h264"))
    incomplete = glob.glob(os.path.join(RECORD_FOLDER, "incomplete_*.h264"))
    i = glob.glob(os.path.join(RECORD_FOLDER, "img_*.jpg"))

    files = sorted(v + i + temp + incomplete, key=os.path.getmtime, reverse=True)

    groups = {}
    standalone = []

    for f in files:
        n = os.path.basename(f)
        try:
            s = round(os.path.getsize(f)/(1024*1024), 2)
        except:
            s = 0

        is_failed = n.startswith('failed_upload_')
        is_converting_h264 = n.startswith('temp_') and n.endswith('.h264')
        is_incomplete = n.startswith('incomplete_') and n.endswith('.h264')
        is_uploaded = n.startswith('uploaded_')
        is_video = ("video" in n or "failed" in n or "temp" in n or "uploaded" in n or "incomplete" in n)

        mp4_name = n.replace('temp_', 'video_').replace('incomplete_', 'video_').replace('.h264', '.mp4')
        is_converting_mp4 = False
        with converting_files_lock:
            is_converting_mp4 = mp4_name in converting_files

        upload_info = None
        with upload_status_lock:
            if n in upload_status:
                upload_info = upload_status[n]

        file_obj = {
            "name": n,
            "type": "video" if is_video else "image",
            "size": s,
            "failed": is_failed,
            "converting": is_converting_h264 or is_converting_mp4,
            "incomplete": is_incomplete,
            "uploaded": is_uploaded,
            "upload_status": upload_info
        }

        if "_chunk" in n and is_video:
            ts = extract_timestamp(n)
            if ts:
                if ts not in groups:
                    groups[ts] = {
                        "base": f"video_{ts}",
                        "timestamp": ts,
                        "chunks": [],
                        "total_size": 0,
                        "chunk_count": 0,
                        "type": "batch",
                        "uploaded_count": 0,
                        "failed_count": 0,
                        "converting_count": 0,
                        "incomplete_count": 0
                    }

                groups[ts]["chunks"].append(file_obj)
                groups[ts]["total_size"] += s
                groups[ts]["chunk_count"] += 1
                if is_uploaded:
                    groups[ts]["uploaded_count"] += 1
                if is_failed:
                    groups[ts]["failed_count"] += 1
                if is_converting_h264 or is_converting_mp4:
                    groups[ts]["converting_count"] += 1
                if is_incomplete:
                    groups[ts]["incomplete_count"] += 1
            else:
                standalone.append(file_obj)
        else:
            standalone.append(file_obj)

    result = []
    for ts, group in sorted(groups.items(), reverse=True):
        result.append(group)
    result.extend(standalone)

    return jsonify(result)

@app.route('/api/get_gps_data/<filename>')
def get_gps_data(filename):
    """Get GPS data for a video file - FIX: Try multiple CSV name variations"""
    csv_variations = [
        filename.replace('video_', 'gps_').replace('.mp4', '.csv'),
        filename.replace('uploaded_', 'gps_').replace('.mp4', '.csv'),
        filename.replace('uploaded_', 'uploaded_gps_').replace('.mp4', '.csv'),
        filename.replace('failed_upload_', 'gps_').replace('.mp4', '.csv'),
        filename.replace('failed_upload_', 'failed_upload_gps_').replace('.mp4', '.csv'),
    ]

    csv_path = None
    for csv_name in csv_variations:
        test_path = os.path.join(RECORD_FOLDER, csv_name)
        if os.path.exists(test_path):
            csv_path = test_path
            break

    if not csv_path:
        return jsonify({"error": "GPS data not found"})

    try:
        gps_points = []
        with open(csv_path, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    lat = float(row['Lat'])
                    lon = float(row['Lon'])
                    if lat != 0.0 or lon != 0.0:
                        gps_points.append({
                            "lat": lat,
                            "lon": lon,
                            "timestamp": row['Timestamp']
                        })
                except:
                    continue

        if not gps_points:
            return jsonify({"error": "No valid GPS data"})

        return jsonify({
            "points": gps_points,
            "start": gps_points[0] if gps_points else None,
            "end": gps_points[-1] if gps_points else None
        })

    except Exception as e:
        return jsonify({"error": str(e)})

@app.route('/api/upload_cloud', methods=['POST'])
def api_upload_cloud():
    try:
        data = request.json
        filename = data.get('filename')
        if not filename:
            return jsonify({"success": False, "error": "No filename"})

        logging.info(f"[API] Upload request for: {filename}")

        with upload_status_lock:
            upload_status[filename] = {"status": "uploading", "message": "Uploading..."}

        video_path = os.path.join(RECORD_FOLDER, filename)

        csv_variations = [
            filename.replace('video_', 'gps_').replace('.mp4', '.csv'),
            filename.replace('uploaded_', 'gps_').replace('.mp4', '.csv'),
        ]
        csv_path = None
        for csv_name in csv_variations:
            test_path = os.path.join(RECORD_FOLDER, csv_name)
            if os.path.exists(test_path):
                csv_path = test_path
                break

        def upload_thread():
            success, message = upload_to_cloud(video_path, csv_path if csv_path else "", DEVICE_ID)
            with upload_status_lock:
                if success:
                    upload_status[filename] = {"status": "success", "message": message}
                    try:
                        uploaded_name = filename.replace('video_', 'uploaded_')
                        new_path = os.path.join(RECORD_FOLDER, uploaded_name)
                        if os.path.exists(video_path):
                            os.rename(video_path, new_path)
                            logging.info(f"[UPLOAD] ✓ Renamed to: {uploaded_name}")
                        if csv_path and os.path.exists(csv_path):
                            uploaded_csv = os.path.basename(csv_path).replace('gps_', 'uploaded_gps_')
                            os.rename(csv_path, os.path.join(RECORD_FOLDER, uploaded_csv))
                    except Exception as e:
                        logging.error(f"[UPLOAD] Rename failed: {e}")

                    threading.Timer(3.0, lambda: upload_status.pop(filename, None)).start()
                else:
                    upload_status[filename] = {"status": "failed", "message": message}
                    try:
                        failed_name = filename.replace('video_', 'failed_upload_')
                        new_path = os.path.join(RECORD_FOLDER, failed_name)
                        if os.path.exists(video_path):
                            os.rename(video_path, new_path)
                            logging.info(f"[UPLOAD] ✗ Renamed to: {failed_name}")
                        if csv_path and os.path.exists(csv_path):
                            failed_csv = os.path.basename(csv_path).replace('gps_', 'failed_upload_gps_')
                            os.rename(csv_path, os.path.join(RECORD_FOLDER, failed_csv))
                    except Exception as e:
                        logging.error(f"[UPLOAD] Rename failed: {e}")

        t = threading.Thread(target=upload_thread)
        t.daemon = True
        t.start()

        return jsonify({"success": True, "message": "Upload started"})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

@app.route('/api/batch_upload', methods=['POST'])
def batch_upload():
    """Upload all chunks in a batch"""
    try:
        data = request.json
        base = data.get('base')
        if not base:
            return jsonify({"success": False, "error": "No base provided"})

        ts = extract_timestamp(base)
        if not ts:
            return jsonify({"success": False, "error": "Cannot extract timestamp"})

        chunks = glob.glob(os.path.join(RECORD_FOLDER, f"video_{ts}_chunk*.mp4"))
        chunks = sorted(chunks)

        logging.info(f"[BATCH] Uploading {len(chunks)} chunks for {base}")

        def batch_upload_thread():
            for chunk_path in chunks:
                chunk_name = os.path.basename(chunk_path)

                csv_variations = [
                    chunk_name.replace('video_', 'gps_').replace('.mp4', '.csv'),
                ]
                csv_path = None
                for csv_name in csv_variations:
                    test_path = os.path.join(RECORD_FOLDER, csv_name)
                    if os.path.exists(test_path):
                        csv_path = test_path
                        break

                with upload_status_lock:
                    upload_status[chunk_name] = {"status": "uploading", "message": "Uploading..."}

                success, message = upload_to_cloud(chunk_path, csv_path if csv_path else "", DEVICE_ID)

                with upload_status_lock:
                    if success:
                        upload_status[chunk_name] = {"status": "success", "message": message}
                        try:
                            uploaded_name = chunk_name.replace('video_', 'uploaded_')
                            new_path = os.path.join(RECORD_FOLDER, uploaded_name)
                            if os.path.exists(chunk_path):
                                os.rename(chunk_path, new_path)
                            if csv_path and os.path.exists(csv_path):
                                uploaded_csv = os.path.basename(csv_path).replace('gps_', 'uploaded_gps_')
                                os.rename(csv_path, os.path.join(RECORD_FOLDER, uploaded_csv))
                        except Exception as e:
                            logging.error(f"[BATCH] Rename failed: {e}")
                    else:
                        upload_status[chunk_name] = {"status": "failed", "message": message}
                        try:
                            failed_name = chunk_name.replace('video_', 'failed_upload_')
                            new_path = os.path.join(RECORD_FOLDER, failed_name)
                            if os.path.exists(chunk_path):
                                os.rename(chunk_path, new_path)
                            if csv_path and os.path.exists(csv_path):
                                failed_csv = os.path.basename(csv_path).replace('gps_', 'failed_upload_gps_')
                                os.rename(csv_path, os.path.join(RECORD_FOLDER, failed_csv))
                        except Exception as e:
                            logging.error(f"[BATCH] Rename failed: {e}")

                time.sleep(1)

        t = threading.Thread(target=batch_upload_thread)
        t.daemon = True
        t.start()

        return jsonify({"success": True, "message": f"Batch upload started for {len(chunks)} chunks"})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route('/api/download/<filename>')
def download(filename):
    return send_from_directory(RECORD_FOLDER, filename, as_attachment=True)

@app.route('/api/delete_file', methods=['POST'])
def delete_file():
    n = request.json.get('filename', '')
    p = os.path.join(RECORD_FOLDER, n)
    if os.path.exists(p) and RECORD_FOLDER in os.path.abspath(p):
        os.remove(p)

        csv_variations = [
            n.replace("video_", "gps_"),
            n.replace("uploaded_", "uploaded_gps_"),
            n.replace("failed_upload_", "failed_upload_gps_"),
            n.replace("temp_", "gps_"),
            n.replace("incomplete_", "incomplete_gps_"),
            n.replace("img_", "gps_"),
        ]

        for csv_base in csv_variations:
            csv_name = csv_base.replace(".mp4", ".csv").replace(".jpg", ".csv").replace(".h264", ".csv")
            csv_path = os.path.join(RECORD_FOLDER, csv_name)
            if os.path.exists(csv_path):
                os.remove(csv_path)
                break

        return "OK"
    return "ERROR"

@app.route('/api/delete_batch', methods=['POST'])
def delete_batch():
    """Delete all chunks in a batch"""
    try:
        data = request.json
        base = data.get('base')
        if not base:
            return jsonify({"success": False, "error": "No base"})

        ts = extract_timestamp(base)
        if not ts:
            return jsonify({"success": False, "error": "Cannot extract timestamp"})

        chunks = glob.glob(os.path.join(RECORD_FOLDER, f"*{ts}_chunk*.mp4"))
        chunks += glob.glob(os.path.join(RECORD_FOLDER, f"*{ts}_chunk*.h264"))

        csvs = glob.glob(os.path.join(RECORD_FOLDER, f"*gps_{ts}_chunk*.csv"))
        csvs += glob.glob(os.path.join(RECORD_FOLDER, f"*{ts}_chunk*.csv"))

        for f in chunks + csvs:
            if os.path.exists(f) and RECORD_FOLDER in os.path.abspath(f):
                os.remove(f)

        return jsonify({"success": True, "message": f"Deleted {len(chunks)} chunks"})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

@app.route('/data/<filename>')
def serve(filename):
    return send_from_directory(RECORD_FOLDER, filename)

if __name__ == '__main__':
    from werkzeug.serving import WSGIRequestHandler
    WSGIRequestHandler.protocol_version = "HTTP/1.1"

    print("=" * 70)
    print(f"  SMART HELMET {VERSION}")
    print("=" * 70)
    print(f"  Port: {PORT}")
    print(f"  Device ID: {DEVICE_ID}")
    print(f"  Recording: {RECORD_FOLDER}")
    print(f"  Resolution: {CAM_WIDTH}x{CAM_HEIGHT}")
    print(f"  Video Bitrate: {VIDEO_BITRATE/1000000} Mbps")
    print(f"  Audio: USB Mic ({USB_MIC_DEVICE}) @ {AUDIO_SAMPLE_RATE}Hz")
    if AUTO_CHUNK_ENABLED:
        print(f"  Auto-Chunk: At {CHUNK_SIZE_MB} MB (~6 min per chunk)")
    print(f"  GPS Frequency: {GPS_RECORD_INTERVAL}s (reduced from 1s)")
    print(f"  FIXED: Timer smooth + GPS CSV + Batch grouping!")
    print(f"  Upload URL: https://centrix.co.in/v_api/upload")
    print("=" * 70)

    recover_orphaned_files()

    ssl_available = generate_ssl_certificates()

    logging.info(f"[MAIN] Starting threads...")
    threading.Thread(target=discovery_service, daemon=True).start()
    threading.Thread(target=camera_worker, daemon=True).start()

    logging.info(f"[MAIN] Starting Flask on port {PORT}...")
    try:
        if ssl_available:
            app.run(host='0.0.0.0', port=PORT, ssl_context=('cert.pem', 'key.pem'), debug=False, threaded=True)
        else:
            app.run(host='0.0.0.0', port=PORT, debug=False, threaded=True)
    except KeyboardInterrupt:
        logging.info("[MAIN] Keyboard interrupt")
    finally:
        logging.info("[MAIN] Shutting down...")
        app_running = False
        stop_audio_recording()
        time.sleep(1)
        logging.info("[MAIN] ✓ Done")
