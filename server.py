#!/usr/bin/env python3
from flask import Flask, Response, render_template, jsonify, request
import time
import os
import cv2
import numpy as np
import uploader

app = Flask(__name__)

# These globals will be set in your main entry (or before starting the server)
image_capturer = None    # Instance of your V2 ImageCapturer (or camera if you prefer)
video_recorder = None    # Instance of your V2 VideoRecorder
audio_only_recorder = None  # Instance of your V2 AudioRecorder

# Global advanced parameters (applied on the captured frame)
advanced_params = {
    "rotation": 180,  # default rotation
    "zoom": 1.0       # default zoom (1.0 means no zoom)
}

def apply_advanced_transformations(frame, params):
    transformed = frame.copy()
    angle = params.get("rotation", 0)
    if angle != 0:
        (h, w) = transformed.shape[:2]
        center = (w // 2, h // 2)
        M = cv2.getRotationMatrix2D(center, angle, 1.0)
        transformed = cv2.warpAffine(transformed, M, (w, h))
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
            new_w, new_h = int(w * zoom), int(h * zoom)
            resized = cv2.resize(transformed, (new_w, new_h))
            top = (h - new_h) // 2
            bottom = h - new_h - top
            left = (w - new_w) // 2
            right = w - new_w - left
            transformed = cv2.copyMakeBorder(resized, top, bottom, left, right,
                                             cv2.BORDER_CONSTANT, value=[0, 0, 0])
    return transformed

def generate_frames():
    while True:
        with image_capturer.frame_lock:
            if image_capturer.latest_frame is None:
                time.sleep(0.05)
                continue
            frame_bgr, _ = image_capturer.latest_frame
        # Apply advanced transformations
        transformed = apply_advanced_transformations(frame_bgr, advanced_params)
        # If video recording is active, write the frame to the recorder
        if video_recorder.recording:
            video_recorder.write_frame(transformed)
        ret, jpeg = cv2.imencode('.jpg', transformed)
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

@app.route('/start_recording', methods=['POST'])
def start_recording():
    data = request.get_json() or {}
    record_audio = data.get("record_audio", False)
    video_type = data.get("type", "general").lower()
    # In V2, start_recording accepts a with_audio flag.
    filename = video_recorder.start_recording(with_audio=record_audio)
    status_message = f"Video recording started. Saving as {filename}"
    return jsonify({'status': status_message})

@app.route('/stop_recording', methods=['POST'])
def stop_recording():
    data = request.get_json() or {}
    video_type = data.get("type", "general").lower()
    # In V2, stop_recording returns a list of segments
    segments = video_recorder.stop_recording(video_type)
    msg_list = []
    if segments:
        for seg in segments:
            seg_file = seg["file"]
            start_time = seg["start"]
            end_time = seg["end"]
            success, resp = uploader.upload_video(seg_file, start_time, end_time)
            if success:
                os.remove(seg_file)
                msg_list.append(seg_file)
            else:
                msg_list.append(f"{seg_file} (upload failed)")
        status_message = "Video segments recorded: " + ", ".join(msg_list)
    else:
        status_message = "No video segments recorded."
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
    filepath = os.path.join("Images", filename)
    cv2.imwrite(filepath, transformed)
    current_time = time.strftime("%H:%M:%S")
    success, resp = uploader.upload_image(filepath, current_time, current_time)
    if success:
        os.remove(filepath)
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
    result = audio_only_recorder.stop_recording()  # returns (filename, start_time, end_time)
    if result:
        final_filename, start_time, end_time = result
        success, resp = uploader.upload_audio(final_filename, start_time, end_time)
        if success:
            os.remove(final_filename)
            status_message = "Audio-only recording stopped and uploaded."
        else:
            status_message = "Audio-only recording stopped but upload failed."
    else:
        status_message = "Audio-only recording stopped."
    return jsonify({'status': status_message})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
