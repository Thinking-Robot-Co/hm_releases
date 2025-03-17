# server.py
from flask import Flask, Response, render_template, jsonify, request
import time
import os
import cv2
import numpy as np
import uploader

app = Flask(__name__)

# Global objects – set in main.py
image_capturer = None
video_recorder = None
audio_only_recorder = None

# Global advanced parameters (applied on the captured frame)
advanced_params = {
    "rotation": 180,  # default rotation in degrees
    "zoom": 1.0       # default zoom (1.0 means no zoom)
}

def apply_advanced_transformations(frame, params):
    # Make a copy of the frame
    transformed = frame.copy()
    # Apply rotation if needed
    angle = params.get("rotation", 0)
    if angle != 0:
        (h, w) = transformed.shape[:2]
        center = (w // 2, h // 2)
        M = cv2.getRotationMatrix2D(center, angle, 1.0)
        transformed = cv2.warpAffine(transformed, M, (w, h))
    # Apply zoom if needed (zoom>1 means zoom in, crop center)
    zoom = params.get("zoom", 1.0)
    if zoom != 1.0:
        (h, w) = transformed.shape[:2]
        if zoom > 1.0:
            new_w, new_h = int(w / zoom), int(h / zoom)
            start_x = (w - new_w) // 2
            start_y = (h - new_h) // 2
            cropped = transformed[start_y:start_y+new_h, start_x:start_x+new_w]
            transformed = cv2.resize(cropped, (w, h))
        else:
            # For zoom < 1, we can simply resize and pad if desired.
            new_w, new_h = int(w * zoom), int(h * zoom)
            resized = cv2.resize(transformed, (new_w, new_h))
            top = (h - new_h) // 2
            bottom = h - new_h - top
            left = (w - new_w) // 2
            right = w - new_w - left
            transformed = cv2.copyMakeBorder(resized, top, bottom, left, right,
                                             cv2.BORDER_CONSTANT, value=[0,0,0])
    return transformed

@app.route('/set_advanced', methods=['POST'])
def set_advanced():
    data = request.get_json() or {}
    if "rotation" in data:
        try:
            advanced_params["rotation"] = float(data["rotation"])
        except:
            pass
    if "zoom" in data:
        try:
            advanced_params["zoom"] = float(data["zoom"])
        except:
            pass
    return jsonify({"status": "Advanced settings updated", "advanced_params": advanced_params})

def generate_frames():
    while True:
        with image_capturer.frame_lock:
            if image_capturer.latest_frame is None:
                time.sleep(0.05)
                continue
            frame_bgr, _ = image_capturer.latest_frame
        # Apply advanced transformations (rotation, zoom, etc)
        transformed_frame = apply_advanced_transformations(frame_bgr, advanced_params)
        # If video is recording, write the transformed frame
        if video_recorder.recording:
            video_recorder.write_frame(transformed_frame)
        ret, jpeg = cv2.imencode('.jpg', transformed_frame)
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + jpeg.tobytes() + b'\r\n')
        time.sleep(0.05)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/video_feed')
def video_feed():
    return Response(generate_frames(),
                    mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/start_recording', methods=['POST'])
def start_recording():
    data = request.get_json() or {}
    record_audio = data.get("record_audio", False)
    video_type = data.get("type", "general").lower()
    filename = video_recorder.start_recording(video_type, record_audio)
    status_message = f"Video recording started. Saving as {filename}"
    return jsonify({'status': status_message})

@app.route('/stop_recording', methods=['POST'])
def stop_recording():
    result = video_recorder.stop_recording()  # returns (final_filename, start_time, end_time)
    if result:
        final_filename, start_time, end_time = result
        upload_res = uploader.upload_file(final_filename, start_time, end_time)
        if upload_res:
            status_message = "Video recording stopped and uploaded."
        else:
            status_message = "Video recording stopped but upload failed."
    else:
        status_message = "Video recording stopped."
    return jsonify({'status': status_message})

@app.route('/capture_image', methods=['POST'])
def capture_image():
    with image_capturer.frame_lock:
        if image_capturer.latest_frame is None:
            return jsonify({'status': 'No image available'}), 500
        frame_bgr, _ = image_capturer.latest_frame
    transformed = apply_advanced_transformations(frame_bgr, advanced_params)
    if not hasattr(capture_image, "img_counter"):
        capture_image.img_counter = 0
    capture_image.img_counter += 1
    timestamp = time.strftime("%d%b%y_%H%M%S").lower()
    data = request.get_json() or {}
    image_type = data.get("type", "general").lower()
    filename = f"img_{image_capturer.session}_{capture_image.img_counter}__{timestamp}_{image_type}.jpg"
    filepath = os.path.join("media", filename)
    cv2.imwrite(filepath, transformed)
    print("Captured image:", filepath)
    current_time = time.strftime("%H:%M:%S")
    upload_res = uploader.upload_file(filepath, current_time, current_time)
    if upload_res:
        status_message = f"Image captured and uploaded as {filename}"
    else:
        status_message = "Image captured but upload failed."
    return jsonify({'status': status_message})

@app.route('/start_audio_only', methods=['POST'])
def start_audio_only():
    data = request.get_json() or {}
    audio_type = data.get("type", "general").lower()
    filename = audio_only_recorder.start_recording(audio_type)
    status_message = f"Audio-only recording started. Saving as {filename}"
    return jsonify({'status': status_message})

@app.route('/stop_audio_only', methods=['POST'])
def stop_audio_only():
    result = audio_only_recorder.stop_recording()  # returns (final_filename, start_time, end_time)
    if result:
        final_filename, start_time, end_time = result
        upload_res = uploader.upload_file(final_filename, start_time, end_time)
        if upload_res:
            status_message = "Audio-only recording stopped and uploaded."
        else:
            status_message = "Audio-only recording stopped but upload failed."
    else:
        status_message = "Audio-only recording stopped."
    return jsonify({'status': status_message})
