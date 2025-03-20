#!/usr/bin/env python3
import sys
import os
import time
import threading
import datetime
import subprocess
import shutil
import requests

import RPi.GPIO as GPIO
from picamera2 import Picamera2, Preview
from libcamera import Transform

import pyaudio
import wave

from PIL import Image  # for converting the array to a JPEG

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout,
    QHBoxLayout, QPushButton, QComboBox, QSlider, QLabel,
    QSpinBox
)
from PyQt5.QtCore import QTimer, Qt

# For the embedded preview widget:
from picamera2.previews.qt import QGlPicamera2

# ------------------- Global Setup -------------------
CHUNK = 1024
FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 44100

AUDIOS_DIR = "Audios"
VIDEOS_DIR = "Videos"
IMAGES_DIR = "Images"
FAILED_DIR = "failed_uploads"

for d in [AUDIOS_DIR, VIDEOS_DIR, IMAGES_DIR, FAILED_DIR]:
    os.makedirs(d, exist_ok=True)

DEVICE_ID = "raspberry_pi_01"  # Change if needed

UPLOAD_URL = "https://centrix.co.in/v_api/upload"
HEADERS = {"X-API-KEY": "DDjgMfxLqhxbNmaBoTkfBJkhMxNxkPwMgGjPUwCOaJRCBrvtUX"}

# GPIO pins
VIDEO_BTN_PIN = 17  # Toggles video recording
AUDIO_BTN_PIN = 22  # Toggles audio-only recording
IMAGE_BTN_PIN = 27  # Single push to capture image

VDO_LED_PIN = 23
IND_LED_PIN = 25

GPIO.setmode(GPIO.BCM)
GPIO.setup(VIDEO_BTN_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
GPIO.setup(AUDIO_BTN_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
GPIO.setup(IMAGE_BTN_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)

GPIO.setup(VDO_LED_PIN, GPIO.OUT)
GPIO.setup(IND_LED_PIN, GPIO.OUT)
GPIO.output(IND_LED_PIN, GPIO.HIGH)

RESOLUTIONS = [
    ("640x480", 640, 480),
    ("1280x720", 1280, 720),
    ("1920x1080", 1920, 1080),
    ("2592x1944", 2592, 1944),  # 5MP for some sensors
]


def record_audio(audio_filename, stop_event):
    """Continuously record audio until stop_event is set."""
    import pyaudio, wave
    p = pyaudio.PyAudio()
    stream = p.open(format=pyaudio.paInt16, channels=1, rate=44100,
                    input=True, frames_per_buffer=1024)
    frames = []
    while not stop_event.is_set():
        try:
            data = stream.read(1024, exception_on_overflow=False)
        except Exception as e:
            print("Audio read error:", e)
            continue
        frames.append(data)
    stream.stop_stream()
    stream.close()
    p.terminate()

    wf = wave.open(audio_filename, 'wb')
    wf.setnchannels(1)
    wf.setsampwidth(p.get_sample_size(pyaudio.paInt16))
    wf.setframerate(44100)
    wf.writeframes(b''.join(frames))
    wf.close()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("All-in-One Camera - Force 'video' field for images/audio")
        self.showFullScreen()  # Fill entire display

        # State
        self.video_recording = False
        self.audio_recording = False
        self.segments = []
        self.session_no = 1
        self.seg_num = 1
        self.audio_thread = None
        self.audio_stop_event = None
        self.stop_thread = False  # for video splitting

        # Debounce flags
        self.video_btn_pressed = False
        self.audio_btn_pressed = False
        self.image_btn_pressed = False

        # Camera controls
        self.current_width = 1280
        self.current_height = 720
        self.current_framerate = 30
        self.current_focus = 0.0
        self.current_zoom = 1.0

        # Initialize PiCamera2
        self.picam2 = Picamera2()

        # Build GUI
        self.init_ui()

        # Poll GPIO pins
        self.gpio_timer = QTimer()
        self.gpio_timer.timeout.connect(self.check_gpio)
        self.gpio_timer.start(100)

        # Start preview after GUI is ready
        QTimer.singleShot(0, self.start_camera_preview)

    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        main_hbox = QHBoxLayout(central_widget)

        # Left: camera preview
        self.camera_widget = QGlPicamera2(self.picam2, keep_ar=True)
        main_hbox.addWidget(self.camera_widget, stretch=3)

        # Right: controls + status
        right_vbox = QVBoxLayout()

        # row of resolution/fps/focus/zoom
        controls_hbox = QHBoxLayout()

        controls_hbox.addWidget(QLabel("Resolution:"))
        self.res_combo = QComboBox()
        for label, w, h in RESOLUTIONS:
            self.res_combo.addItem(label, (w, h))
        default_idx = 0
        for i in range(self.res_combo.count()):
            data = self.res_combo.itemData(i)
            if data[0] == self.current_width and data[1] == self.current_height:
                default_idx = i
                break
        self.res_combo.setCurrentIndex(default_idx)
        self.res_combo.currentIndexChanged.connect(self.on_resolution_changed)
        controls_hbox.addWidget(self.res_combo)

        controls_hbox.addWidget(QLabel("FPS:"))
        self.fps_spin = QSpinBox()
        self.fps_spin.setRange(1, 90)
        self.fps_spin.setValue(self.current_framerate)
        self.fps_spin.valueChanged.connect(self.on_framerate_changed)
        controls_hbox.addWidget(self.fps_spin)

        controls_hbox.addWidget(QLabel("Focus:"))
        self.focus_slider = QSlider(Qt.Horizontal)
        self.focus_slider.setRange(0, 100)
        self.focus_slider.setValue(0)
        self.focus_slider.valueChanged.connect(self.on_focus_changed)
        controls_hbox.addWidget(self.focus_slider)

        controls_hbox.addWidget(QLabel("Zoom:"))
        self.zoom_slider = QSlider(Qt.Horizontal)
        self.zoom_slider.setRange(10, 40)  # => 1.0..4.0
        self.zoom_slider.setValue(10)
        self.zoom_slider.valueChanged.connect(self.on_zoom_changed)
        controls_hbox.addWidget(self.zoom_slider)

        right_vbox.addLayout(controls_hbox)

        # row of buttons: video, audio, image
        btns_hbox = QHBoxLayout()

        self.video_btn = QPushButton("Start Video")
        self.video_btn.clicked.connect(self.toggle_video_recording)
        btns_hbox.addWidget(self.video_btn)

        self.audio_btn = QPushButton("Start Audio")
        self.audio_btn.clicked.connect(self.toggle_audio_recording)
        btns_hbox.addWidget(self.audio_btn)

        self.image_btn = QPushButton("Capture Image")
        self.image_btn.setCheckable(False)  # normal push
        self.image_btn.clicked.connect(self.capture_image_button_clicked)
        btns_hbox.addWidget(self.image_btn)

        right_vbox.addLayout(btns_hbox)

        # status label
        self.status_label = QLabel("Status: Ready.")
        self.status_label.setStyleSheet("QLabel { background-color: #EFEFEF; padding: 5px; }")
        right_vbox.addWidget(self.status_label, stretch=1)

        main_hbox.addLayout(right_vbox, stretch=2)

    def update_status(self, msg):
        print(msg)
        self.status_label.setText(msg)

    # --------------- Start/Stop Preview ---------------
    def start_camera_preview(self):
        self.update_status("Starting camera preview...")
        self.apply_camera_settings()
        self.picam2.start()
        self.update_status("Camera preview started.")

    def apply_camera_settings(self):
        was_running = (self.picam2.camera_configuration is not None)
        if was_running:
            self.picam2.stop()

        config = self.picam2.create_preview_configuration(
            main={"size": (self.current_width, self.current_height)},
            transform=Transform(vflip=True),
        )
        config["controls"]["FrameDurationLimits"] = (
            int(1e6 // self.current_framerate),
            int(1e6 // self.current_framerate),
        )
        self.picam2.configure(config)
        self.picam2.start()
        self.apply_digital_zoom()

    def apply_digital_zoom(self):
        sensor_w = self.current_width
        sensor_h = self.current_height
        new_w = int(sensor_w / self.current_zoom)
        new_h = int(sensor_h / self.current_zoom)
        x = (sensor_w - new_w) // 2
        y = (sensor_h - new_h) // 2
        try:
            self.picam2.set_controls({"ScalerCrop": (x, y, new_w, new_h)})
        except Exception as e:
            self.update_status(f"ScalerCrop not supported: {e}")

    def on_resolution_changed(self, idx):
        if self.video_recording:
            return
        w, h = self.res_combo.itemData(idx)
        self.current_width = w
        self.current_height = h
        self.update_status(f"Resolution changed to {w}x{h}, reconfiguring...")
        self.apply_camera_settings()

    def on_framerate_changed(self, val):
        if self.video_recording:
            return
        self.current_framerate = val
        self.update_status(f"Framerate changed to {val}, reconfiguring...")
        self.apply_camera_settings()

    def on_focus_changed(self, val):
        lens_pos = val / 10.0
        self.current_focus = lens_pos
        try:
            self.picam2.set_controls({"LensPosition": lens_pos})
            self.update_status(f"Focus changed to {lens_pos:.1f}")
        except Exception as e:
            self.update_status(f"Focus not supported or error: {e}")

    def on_zoom_changed(self, val):
        self.current_zoom = val / 10.0
        self.update_status(f"Zoom changed to {self.current_zoom:.1f}x")
        self.apply_digital_zoom()

    # --------------- Video Recording ---------------
    def toggle_video_recording(self):
        if not self.video_recording:
            self.start_video_recording()
        else:
            self.stop_video_recording()

    def start_video_recording(self):
        if self.video_recording:
            return
        self.update_status("Starting VIDEO recording session...")
        self.session_no = 1
        self.seg_num = 1
        self.segments = []
        start_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        video_file = self.get_video_filename(self.session_no, self.seg_num)
        audio_file = self.get_audio_filename(self.session_no, self.seg_num)

        GPIO.output(VDO_LED_PIN, GPIO.HIGH)

        # Start video
        self.picam2.start_and_record_video(video_file, duration=None)

        # Start audio
        self.audio_stop_event = threading.Event()
        self.audio_thread = threading.Thread(target=record_audio,
                                             args=(audio_file, self.audio_stop_event))
        self.audio_thread.start()

        self.video_recording = True
        self.stop_thread = False

        # Check file size
        self.size_thread = threading.Thread(target=self.check_video_size)
        self.size_thread.start()

        seg = {
            "video": video_file,
            "audio": audio_file,
            "start_time": start_time,
            "end_time": None
        }
        self.segments.append(seg)

        self.video_btn.setText("Stop Video")
        self.update_status(f"Video rec started => {os.path.basename(video_file)}, {os.path.basename(audio_file)}")

    def stop_video_recording(self):
        if not self.video_recording:
            return
        self.update_status("Stopping VIDEO recording...")
        self.video_recording = False
        self.stop_thread = True

        # Stop video
        try:
            self.picam2.stop_recording()
        except:
            pass

        # Stop audio
        if self.audio_thread and self.audio_thread.is_alive():
            self.audio_stop_event.set()
            self.audio_thread.join()

        self.segments[-1]["end_time"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        GPIO.output(VDO_LED_PIN, GPIO.LOW)
        self.video_btn.setText("Start Video")

        # Merge & upload
        self.update_status("Merging & uploading video segments...")
        self.retry_failed_uploads()  # retry older
        for seg in self.segments:
            merged_file = seg["video"].replace(".mp4", "_merged.mp4")
            self.update_status(f"Merging => {os.path.basename(seg['video'])} + {os.path.basename(seg['audio'])}")
            if self.merge_audio_video(seg["video"], seg["audio"], merged_file):
                self.update_status(f"Merged => {os.path.basename(merged_file)}, uploading...")
                if not self.upload_video(merged_file, seg["start_time"], seg["end_time"]):
                    failed_path = os.path.join(FAILED_DIR, os.path.basename(merged_file))
                    shutil.move(merged_file, failed_path)
                    self.update_status(f"Upload failed, moved => {failed_path}")
                else:
                    self.update_status(f"Upload success, removed => {merged_file}")
            else:
                self.update_status(f"Merge failed => {seg['video']} / {seg['audio']}")
        self.segments.clear()

        # Re-apply preview
        self.update_status("Reconfiguring preview after video stop...")
        self.apply_camera_settings()
        self.update_status("Video recording stopped. Preview resumed.")

    def check_video_size(self):
        while self.video_recording and not self.stop_thread:
            current_video = self.segments[-1]["video"]
            if os.path.exists(current_video) and os.path.getsize(current_video) >= 10 * 1024 * 1024:
                self.update_status("Video reached 10MB => splitting segment...")
                self.split_segment()
            time.sleep(1)

    def split_segment(self):
        try:
            self.picam2.stop_recording()
        except:
            pass

        if self.audio_thread and self.audio_thread.is_alive():
            self.audio_stop_event.set()
            self.audio_thread.join()

        self.segments[-1]["end_time"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.update_status(f"Segment {self.seg_num} ended, creating next...")

        self.seg_num += 1
        video_file = self.get_video_filename(self.session_no, self.seg_num)
        audio_file = self.get_audio_filename(self.session_no, self.seg_num)
        new_seg = {
            "video": video_file,
            "audio": audio_file,
            "start_time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "end_time": None
        }
        self.segments.append(new_seg)

        self.picam2.start_and_record_video(video_file, duration=None)
        self.audio_stop_event = threading.Event()
        self.audio_thread = threading.Thread(target=record_audio,
                                             args=(audio_file, self.audio_stop_event))
        self.audio_thread.start()
        self.update_status(f"Started new seg => {os.path.basename(video_file)}, {os.path.basename(audio_file)}")

    # --------------- Audio-Only Recording ---------------
    def toggle_audio_recording(self):
        if not self.audio_recording:
            self.start_audio_recording()
        else:
            self.stop_audio_recording()

    def start_audio_recording(self):
        if self.audio_recording:
            return
        self.update_status("Starting AUDIO-ONLY recording...")
        self.audio_recording = True

        self.audio_start_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.audio_file = self.get_audio_filename(999, 1)
        self.audio_stop_event = threading.Event()
        self.audio_thread = threading.Thread(target=record_audio,
                                             args=(self.audio_file, self.audio_stop_event))
        self.audio_thread.start()

        self.audio_btn.setText("Stop Audio")
        self.update_status(f"Audio rec => {os.path.basename(self.audio_file)}")

    def stop_audio_recording(self):
        if not self.audio_recording:
            return
        self.update_status("Stopping AUDIO-ONLY recording...")
        self.audio_recording = False

        if self.audio_thread and self.audio_thread.is_alive():
            self.audio_stop_event.set()
            self.audio_thread.join()

        audio_end_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.audio_btn.setText("Start Audio")

        # Upload
        self.update_status(f"Uploading audio => {os.path.basename(self.audio_file)}")
        if not self.upload_audio(self.audio_file, self.audio_start_time, audio_end_time):
            failed_path = os.path.join(FAILED_DIR, os.path.basename(self.audio_file))
            shutil.move(self.audio_file, failed_path)
            self.update_status(f"Audio upload failed => {failed_path}")
        else:
            if os.path.exists(self.audio_file):
                os.remove(self.audio_file)
                self.update_status("Audio upload success, local file removed")

    # --------------- Image Capture in a Separate Thread ---------------
    def capture_image_button_clicked(self):
        """One push => capture + upload => done. No toggling."""
        self.image_btn.setEnabled(False)  # disable to avoid spam
        t = threading.Thread(target=self.capture_image_thread)
        t.start()

    def capture_image_thread(self):
        self.update_status("Capturing single image...")

        # If video is recording, forcibly stop
        if self.video_recording:
            self.update_status("Stopping video to capture image...")
            self.stop_video_recording()

        # Software snapshot from the current preview
        try:
            arr = self.picam2.capture_array("main")
        except Exception as e:
            self.update_status(f"Error capturing array: {e}")
            QTimer.singleShot(0, lambda: self.image_btn.setEnabled(True))
            return

        # Convert to PIL Image, ensure no alpha channel
        img = Image.fromarray(arr).convert("RGB")
        filename = self.get_image_filename()
        self.update_status(f"Saving image => {os.path.basename(filename)}")
        img.save(filename, format="JPEG")

        # Upload
        self.update_status("Image captured, uploading...")
        success = self.upload_image(filename)
        if not success:
            failed_path = os.path.join(FAILED_DIR, os.path.basename(filename))
            shutil.move(filename, failed_path)
            self.update_status(f"Image upload failed => {failed_path}")
        else:
            if os.path.exists(filename):
                os.remove(filename)
                self.update_status("Image upload success, local file removed")

        # re-enable
        QTimer.singleShot(0, lambda: self.image_btn.setEnabled(True))
        self.update_status("Capture done. Preview is still running.")

    # --------------- Filename Helpers ---------------
    def format_timestamp(self):
        return datetime.datetime.now().strftime("%d%b%y_%H%M%S").lower()

    def get_video_filename(self, session_no, seg_num):
        ts = self.format_timestamp()
        return os.path.join(VIDEOS_DIR, f"vdo_{DEVICE_ID}_{session_no}_{seg_num}_{ts}.mp4")

    def get_audio_filename(self, session_no, seg_num):
        ts = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        return os.path.join(AUDIOS_DIR, f"audio_{DEVICE_ID}_{session_no}_{seg_num}_{ts}.wav")

    def get_image_filename(self):
        ts = self.format_timestamp()
        return os.path.join(IMAGES_DIR, f"img_{DEVICE_ID}_{ts}.jpg")

    # --------------- Merging & Uploading ---------------
    def merge_audio_video(self, video_file, audio_file, output_file):
        cmd = [
            "ffmpeg",
            "-y",
            "-i", video_file,
            "-i", audio_file,
            "-c:v", "copy",
            "-c:a", "aac",
            output_file
        ]
        try:
            subprocess.run(cmd, check=True)
            return True
        except subprocess.CalledProcessError as e:
            self.update_status(f"ffmpeg merge error: {e}")
            return False

    def upload_video(self, file_path, start_time, end_time):
        """
        For actual video merges. Uses field "video".
        """
        try:
            with open(file_path, "rb") as f:
                files = {"video": f}  # video field
                data = {
                    "device_id": DEVICE_ID,
                    "start_time": start_time,
                    "end_time": end_time,
                    "file_type": "video"
                }
                resp = requests.post(UPLOAD_URL, headers=HEADERS, files=files, data=data)
            if resp.status_code == 200:
                result = resp.json()
                if result.get("success"):
                    return True
                else:
                    self.update_status(f"Video upload failed: {result}")
            else:
                self.update_status(f"Video upload error {resp.status_code}: {resp.text}")
        except Exception as e:
            self.update_status(f"Video upload exception: {e}")
        return False

    def upload_audio(self, file_path, start_time, end_time):
        """
        Force "video" as the field, so the server doesn't complain.
        We pass "file_type":"audio" so the backend can differentiate.
        """
        try:
            with open(file_path, "rb") as f:
                files = {"video": f}  # rename "audio" to "video"
                data = {
                    "device_id": DEVICE_ID,
                    "start_time": start_time,
                    "end_time": end_time,
                    "file_type": "audio"  # let server see it's audio
                }
                resp = requests.post(UPLOAD_URL, headers=HEADERS, files=files, data=data)
            if resp.status_code == 200:
                result = resp.json()
                if result.get("success"):
                    return True
                else:
                    self.update_status(f"Audio upload failed: {result}")
            else:
                self.update_status(f"Audio upload error {resp.status_code}: {resp.text}")
        except Exception as e:
            self.update_status(f"Audio upload exception: {e}")
        return False

    def upload_image(self, file_path):
        """
        Force "video" as the field for images too.
        Pass "file_type":"image" so the server can handle it.
        """
        try:
            with open(file_path, "rb") as f:
                files = {"video": f}  # rename "image" to "video"
                data = {
                    "device_id": DEVICE_ID,
                    "file_type": "image"
                }
                resp = requests.post(UPLOAD_URL, headers=HEADERS, files=files, data=data)
            if resp.status_code == 200:
                result = resp.json()
                if result.get("success"):
                    return True
                else:
                    self.update_status(f"Image upload failed: {result}")
            else:
                self.update_status(f"Image upload error {resp.status_code}: {resp.text}")
        except Exception as e:
            self.update_status(f"Image upload exception: {e}")
        return False

    def retry_failed_uploads(self):
        failed_files = [f for f in os.listdir(FAILED_DIR) if f.endswith("_merged.mp4")]
        if failed_files:
            self.update_status(f"Found {len(failed_files)} failed video merges. Retrying...")
            for failed in failed_files:
                failed_path = os.path.join(FAILED_DIR, failed)
                self.update_status(f"Retrying video => {failed}")
                # We don't have start_time/end_time, so pass empty
                if self.upload_video(failed_path, "", ""):
                    if os.path.exists(failed_path):
                        os.remove(failed_path)
                        self.update_status(f"Uploaded & removed => {failed}")
                else:
                    self.update_status(f"Still failed => {failed_path}")
        else:
            self.update_status("No failed video merges to retry.")

    # --------------- GPIO Polling ---------------
    def check_gpio(self):
        # VIDEO
        if GPIO.input(VIDEO_BTN_PIN) == GPIO.LOW:
            if not self.video_btn_pressed:
                self.video_btn_pressed = True
                self.toggle_video_recording()
        else:
            self.video_btn_pressed = False

        # AUDIO
        if GPIO.input(AUDIO_BTN_PIN) == GPIO.LOW:
            if not self.audio_btn_pressed:
                self.audio_btn_pressed = True
                self.toggle_audio_recording()
        else:
            self.audio_btn_pressed = False

        # IMAGE
        if GPIO.input(IMAGE_BTN_PIN) == GPIO.LOW:
            if not self.image_btn_pressed:
                self.image_btn_pressed = True
                self.capture_image_button_clicked()
        else:
            self.image_btn_pressed = False

    def closeEvent(self, event):
        try:
            if self.video_recording:
                self.stop_video_recording()
            if self.audio_recording:
                self.stop_audio_recording()
            self.picam2.stop()
            self.picam2.close()
            GPIO.cleanup()
        except Exception as e:
            print("Error during cleanup:", e)
        event.accept()


if __name__ == "__main__":
    try:
        app = QApplication(sys.argv)
        window = MainWindow()
        window.show()  # already full screen
        sys.exit(app.exec_())
    except KeyboardInterrupt:
        print("Exiting...")
        GPIO.cleanup()
