import os
import time
import cv2
import threading
import datetime
import numpy as np
from flask import Flask, Response, render_template, jsonify, request
from picamera2 import Picamera2
from libcamera import Transform

# Import your custom modules (assumed to be in the same folder)
from recorder import AudioRecorder
from uploader import upload_image, upload_video, upload_audio
from merger import merge_audio_video

app = Flask(__name__)

# Global variables for preview and recording state
global_frame = None
frame_lock = threading.Lock()
recording_video = False
video_filename = None
video_with_audio = False
picam2_instance = None
audio_recorder = AudioRecorder()

def camera_preview_thread():
    """
    Starts the camera in preview mode using a configuration that gives a full
    (zoomed-out) view. This thread continuously captures frames for the MJPEG stream.
    """
    global global_frame, picam2_instance, recording_video
    # For preview, use rotation=180 (to orient correctly) with default sensor config.
    transform = Transform(rotation=180)
    picam2_instance = Picamera2()
    # Do not force a sensor output size here so that the full FOV is shown.
    preview_config = picam2_instance.create_preview_configuration(transform=transform)
    picam2_instance.configure(preview_config)
    picam2_instance.start()
    while True:
        # Only update preview if not recording video
        if not recording_video:
            frame = picam2_instance.capture_array()
            frame_bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
            ret, jpeg = cv2.imencode('.jpg', frame_bgr)
            if ret:
                with frame_lock:
                    global_frame = jpeg.tobytes()
        time.sleep(0.05)  # ~20 FPS

@app.route('/')
def index():
    return render_template("index.html")

def generate_frames():
    while True:
        with frame_lock:
            if global_frame is None:
                time.sleep(0.05)
                continue
            frame = global_frame
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')
        time.sleep(0.05)

@app.route('/video_feed')
def video_feed():
    return Response(generate_frames(),
                    mimetype="multipart/x-mixed-replace; boundary=frame")

@app.route('/capture_image', methods=['POST'])
def capture_image():
    """
    Capture an image using the current camera instance and upload it.
    """
    try:
        now = datetime.datetime.now()
        filename = os.path.join("Images", f"img_{now.strftime('%d%b%Y_%H%M%S')}.jpg")
        picam2_instance.capture_file(filename)
        success, resp = upload_image(filename)
        if success:
            os.remove(filename)
            return jsonify({"status": "success", "message": "Image captured and uploaded."})
        else:
            return jsonify({"status": "fail", "message": "Image captured but upload failed."})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/start_video', methods=['POST'])
def start_video():
    """
    Starts video recording. This stops the preview, reconfigures the camera for
    recording with a zoomed‐in view (rotation=90, sensor output size 1280×720),
    and starts audio recording if the checkbox is checked.
    """
    global recording_video, video_filename, video_with_audio
    if recording_video:
        return jsonify({"status": "fail", "message": "Video recording already in progress."})
    try:
        recording_video = True
        data = request.get_json() or {}
        # Checkbox is checked by default on the webpage.
        video_with_audio = bool(data.get("with_audio", True))
        now = datetime.datetime.now()
        video_filename = os.path.join("Videos", f"video_{now.strftime('%d%b%Y_%H%M%S')}.mp4")
        # Stop preview temporarily
        picam2_instance.stop()
        # Reconfigure for video recording (use settings from your recorder.py)
        # Here we mimic your original: rotation=90, sensor size set to (1280,720)
        rec_config = picam2_instance.create_preview_configuration(
            transform=Transform(rotation=90),
            sensor={'output_size': (1280, 720)}
        )
        picam2_instance.configure(rec_config)
        # Start video recording using the built-in API
        picam2_instance.start_and_record_video(video_filename)
        if video_with_audio:
            audio_recorder.start_recording()
        return jsonify({"status": "success", "message": "Video recording started."})
    except Exception as e:
        recording_video = False
        return jsonify({"status": "error", "message": str(e)})

@app.route('/stop_video', methods=['POST'])
def stop_video():
    """
    Stops video recording. Stops audio if active, merges video and audio (if applicable),
    then reconfigures the camera back to preview mode and restarts the preview.
    Finally, uploads the video.
    """
    global recording_video, video_filename, video_with_audio
    if not recording_video:
        return jsonify({"status": "fail", "message": "No video recording in progress."})
    try:
        picam2_instance.stop_recording()
        merged = False
        if video_with_audio:
            audio_file = audio_recorder.stop_recording()
            merged_filename = os.path.join("Videos", f"merged_{datetime.datetime.now().strftime('%d%b%Y_%H%M%S')}.mp4")
            merge_success = merge_audio_video(video_filename, audio_file, merged_filename)
            if merge_success:
                os.remove(video_filename)
                os.remove(audio_file)
                video_filename = merged_filename
                merged = True
        # Reconfigure camera back to preview mode (rotation=180, full view)
        preview_config = picam2_instance.create_preview_configuration(transform=Transform(rotation=180))
        picam2_instance.configure(preview_config)
        picam2_instance.start()
        recording_video = False
        msg = "Video recorded and uploaded."
        if merged:
            msg += " (Merged with audio)"
        success, resp = upload_video(video_filename, "", "")
        if success:
            os.remove(video_filename)
            return jsonify({"status": "success", "message": msg})
        else:
            return jsonify({"status": "fail", "message": "Video recorded but upload failed."})
    except Exception as e:
        recording_video = False
        return jsonify({"status": "error", "message": str(e)})

@app.route('/start_audio', methods=['POST'])
def start_audio():
    try:
        audio_recorder.start_recording()
        return jsonify({"status": "success", "message": "Audio recording started."})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/stop_audio', methods=['POST'])
def stop_audio():
    try:
        audio_file = audio_recorder.stop_recording()
        success, resp = upload_audio(audio_file, "", "")
        if success:
            os.remove(audio_file)
            return jsonify({"status": "success", "message": "Audio recorded and uploaded."})
        else:
            return jsonify({"status": "fail", "message": "Audio recorded but upload failed."})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

if __name__ == '__main__':
    os.makedirs("Images", exist_ok=True)
    os.makedirs("Videos", exist_ok=True)
    os.makedirs("Audios", exist_ok=True)
    t = threading.Thread(target=camera_preview_thread, daemon=True)
    t.start()
    # Disable reloader to prevent duplicate camera instances
    app.run(host='0.0.0.0', port=5000, debug=True, use_reloader=False)
