# server.py
from flask import Flask, Response, render_template, jsonify, request
import time
import os
import cv2
import uploader

app = Flask(__name__)

# These globals will be set in main.py
image_capturer = None
video_recorder = None
audio_only_recorder = None

def generate_frames():
    while True:
        with image_capturer.frame_lock:
            if image_capturer.latest_frame is None:
                time.sleep(0.05)
                continue
            frame_bgr, jpeg_bytes = image_capturer.latest_frame
        if video_recorder.recording:
            video_recorder.write_frame(frame_bgr)
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + jpeg_bytes + b'\r\n')
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
    if not hasattr(capture_image, "img_counter"):
        capture_image.img_counter = 0
    capture_image.img_counter += 1
    timestamp = time.strftime("%d%b%y_%H%M%S").lower()
    data = request.get_json() or {}
    image_type = data.get("type", "general").lower()
    filename = f"img_{image_capturer.session}_{capture_image.img_counter}__{timestamp}_{image_type}.jpg"
    filepath = os.path.join("media", filename)
    cv2.imwrite(filepath, frame_bgr)
    print("Captured image:", filepath)
    # For image capture, use the current time as both start and stop times.
    current_time = time.strftime("%H:%M:%S")
    upload_res = uploader.upload_file(filepath, current_time, current_time)
    if upload_res:
        status_message = f"Image captured and uploaded as {filename}"
    else:
        status_message = "Image captured but upload failed."
    return jsonify({'status': status_message})

# Endpoints for audio-only recording
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
