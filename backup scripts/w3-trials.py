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

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QComboBox, QSlider, QLabel, QSpinBox
)
from PyQt5.QtCore import QTimer, Qt

# For the embedded preview widget:
from picamera2.previews.qt import QGlPicamera2  # or QPicamera2 if preferred

# ---------------- Directories and Setup ----------------
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
VDO_BTN_PIN = 17
VDO_LED_PIN = 23
STOP_BTN_PIN = 27
IND_LED_PIN = 25

GPIO.setmode(GPIO.BCM)
GPIO.setup(VDO_BTN_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
GPIO.setup(VDO_LED_PIN, GPIO.OUT)
GPIO.setup(IND_LED_PIN, GPIO.OUT)
GPIO.output(IND_LED_PIN, GPIO.HIGH)

# Common resolutions for the dropdown
RESOLUTIONS = [
    ("640x480", 640, 480),
    ("1280x720", 1280, 720),
    ("1920x1080", 1920, 1080),
    ("2592x1944", 2592, 1944),  # 5MP for some cameras
]


def record_audio(audio_filename, stop_event):
    """
    Record audio continuously until stop_event is set.
    Saves the audio as a .wav file.
    """
    CHUNK = 1024
    FORMAT = pyaudio.paInt16
    CHANNELS = 1
    RATE = 44100

    p = pyaudio.PyAudio()
    stream = p.open(format=FORMAT, channels=CHANNELS, rate=RATE,
                    input=True, frames_per_buffer=CHUNK)
    frames = []
    while not stop_event.is_set():
        try:
            data = stream.read(CHUNK, exception_on_overflow=False)
        except Exception as e:
            print("Audio read error:", e)
            continue
        frames.append(data)
    stream.stop_stream()
    stream.close()
    p.terminate()

    wf = wave.open(audio_filename, 'wb')
    wf.setnchannels(CHANNELS)
    wf.setsampwidth(p.get_sample_size(FORMAT))
    wf.setframerate(RATE)
    wf.writeframes(b''.join(frames))
    wf.close()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Raspberry Pi Recording - Extra Controls")

        # Instead of going full-screen, pick a size that fits everything
        self.resize(1024, 600)

        # -------------- Recording State --------------
        # Video+Audio recording
        self.recording = False
        self.segments = []
        self.session_no = 1
        self.seg_num = 1
        self.audio_thread = None
        self.audio_stop_event = None
        self.stop_thread = False

        # Audio-only recording
        self.audio_only_recording = False
        self.audio_only_thread = None
        self.audio_only_stop_event = None
        self.audio_only_start_time = None
        self.audio_only_filename = None

        # For GPIO polling debounce
        self.gpio_pressed = False

        # Default camera settings
        self.current_width = 1280
        self.current_height = 720
        self.current_framerate = 30
        self.current_focus = 0.0  # If camera supports manual focus
        self.current_zoom = 1.0   # Digital zoom factor

        # Initialize Picamera2
        self.picam2 = Picamera2()

        # Build the GUI
        self.initUI()

        # Poll the physical GPIO button periodically
        self.gpio_timer = QTimer()
        self.gpio_timer.timeout.connect(self.check_gpio)
        self.gpio_timer.start(100)

        # Start camera preview after GUI is set up
        QTimer.singleShot(0, self.start_camera_preview)

    def initUI(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_vbox = QVBoxLayout(central_widget)

        # ---- Camera preview widget (fixed size so there's space for controls) ----
        self.camera_widget = QGlPicamera2(self.picam2, keep_ar=True)
        self.camera_widget.setFixedSize(640, 360)
        main_vbox.addWidget(self.camera_widget, stretch=0)

        # ---- Row of controls: resolution, fps, focus, zoom ----
        controls_hbox = QHBoxLayout()

        # Resolution Combo
        controls_hbox.addWidget(QLabel("Resolution:"))
        self.res_combo = QComboBox()
        for label, w, h in RESOLUTIONS:
            self.res_combo.addItem(label, (w, h))
        # Match default (1280x720) if it’s in the list
        default_index = 0
        for i in range(self.res_combo.count()):
            data = self.res_combo.itemData(i)
            if data[0] == self.current_width and data[1] == self.current_height:
                default_index = i
                break
        self.res_combo.setCurrentIndex(default_index)
        self.res_combo.currentIndexChanged.connect(self.on_resolution_changed)
        controls_hbox.addWidget(self.res_combo)

        # Frame Rate SpinBox
        controls_hbox.addWidget(QLabel("FPS:"))
        self.fps_spin = QSpinBox()
        self.fps_spin.setRange(1, 90)
        self.fps_spin.setValue(self.current_framerate)
        self.fps_spin.valueChanged.connect(self.on_framerate_changed)
        controls_hbox.addWidget(self.fps_spin)

        # Focus Slider
        controls_hbox.addWidget(QLabel("Focus:"))
        self.focus_slider = QSlider(Qt.Horizontal)
        self.focus_slider.setRange(0, 100)  # Maps to e.g. 0..10 lens pos
        self.focus_slider.setValue(int(self.current_focus))
        self.focus_slider.valueChanged.connect(self.on_focus_slider_changed)
        controls_hbox.addWidget(self.focus_slider)

        # Zoom Slider
        controls_hbox.addWidget(QLabel("Zoom:"))
        self.zoom_slider = QSlider(Qt.Horizontal)
        self.zoom_slider.setRange(10, 40)  # 10->1.0, 40->4.0
        self.zoom_slider.setValue(int(self.current_zoom * 10))
        self.zoom_slider.valueChanged.connect(self.on_zoom_slider_changed)
        controls_hbox.addWidget(self.zoom_slider)

        main_vbox.addLayout(controls_hbox)

        # ---- Row of buttons: Video Record, Audio-Only, Capture Photo ----
        buttons_hbox = QHBoxLayout()

        # Start/Stop Video+Audio
        self.start_stop_btn = QPushButton("Start Recording")
        self.start_stop_btn.setFixedHeight(40)
        self.start_stop_btn.clicked.connect(self.toggle_recording)
        buttons_hbox.addWidget(self.start_stop_btn)

        # Audio-Only toggle
        self.audio_only_btn = QPushButton("Record Audio Only")
        self.audio_only_btn.setFixedHeight(40)
        self.audio_only_btn.clicked.connect(self.toggle_audio_only)
        buttons_hbox.addWidget(self.audio_only_btn)

        # Capture Photo
        self.capture_photo_btn = QPushButton("Capture Photo")
        self.capture_photo_btn.setFixedHeight(40)
        self.capture_photo_btn.clicked.connect(self.capture_photo)
        buttons_hbox.addWidget(self.capture_photo_btn)

        main_vbox.addLayout(buttons_hbox)

        # Finally, update the UI states
        self.update_ui()

    # ---------------- UI and Camera Setup ----------------
    def update_ui(self):
        """
        Enable/disable widgets depending on recording states.
        """
        # If we are recording video+audio, we cannot change resolution/fps
        can_change_res = (not self.recording) and (not self.audio_only_recording)
        self.res_combo.setEnabled(can_change_res)
        self.fps_spin.setEnabled(can_change_res)

        # Also, if we are recording video, disable the audio-only button, and vice versa
        self.audio_only_btn.setEnabled(not self.recording)
        self.start_stop_btn.setEnabled(not self.audio_only_recording)

    def start_camera_preview(self):
        """
        Configure and start the camera preview.
        """
        self.apply_camera_settings()
        self.picam2.start()
        print("Camera preview started.")

    def apply_camera_settings(self):
        """
        Stop the camera if needed, configure it with current resolution/framerate, and restart.
        """
        if self.picam2.camera_configuration is not None:
            self.picam2.stop()

        config = self.picam2.create_preview_configuration(
            main={"size": (self.current_width, self.current_height)},
            transform=Transform(vflip=True),
            display_resolution=(self.current_width, self.current_height),
        )
        # Force a certain framerate
        config["controls"]["FrameDurationLimits"] = (
            int(1e6 // self.current_framerate),
            int(1e6 // self.current_framerate)
        )
        self.picam2.configure(config)
        self.picam2.start()

        # Apply digital zoom (ScalerCrop)
        self.apply_digital_zoom()

    # ---------------- Handlers for Controls ----------------
    def on_resolution_changed(self, index):
        if self.recording or self.audio_only_recording:
            return
        w, h = self.res_combo.itemData(index)
        self.current_width = w
        self.current_height = h
        print(f"Resolution changed to {w}x{h}")
        self.apply_camera_settings()

    def on_framerate_changed(self, value):
        if self.recording or self.audio_only_recording:
            return
        self.current_framerate = value
        print(f"Framerate changed to {value}")
        self.apply_camera_settings()

    def on_focus_slider_changed(self, value):
        # Attempt to set LensPosition if supported
        lens_pos = value / 10.0  # map 0..100 => 0..10
        self.current_focus = lens_pos
        print(f"Focus changed to {lens_pos:.1f}")
        try:
            self.picam2.set_controls({"LensPosition": lens_pos})
        except Exception as e:
            print("Focus control not supported:", e)

    def on_zoom_slider_changed(self, value):
        factor = value / 10.0
        self.current_zoom = factor
        self.apply_digital_zoom()

    def apply_digital_zoom(self):
        # For digital zoom, we set "ScalerCrop" to a centered sub-region
        sensor_w = self.current_width
        sensor_h = self.current_height
        new_w = int(sensor_w / self.current_zoom)
        new_h = int(sensor_h / self.current_zoom)
        x = (sensor_w - new_w) // 2
        y = (sensor_h - new_h) // 2
        try:
            self.picam2.set_controls({"ScalerCrop": (x, y, new_w, new_h)})
        except Exception as e:
            print("ScalerCrop not supported:", e)

    # ---------------- Video+Audio Recording ----------------
    def toggle_recording(self):
        if not self.recording:
            self.start_recording()
        else:
            self.stop_recording()

    def start_recording(self):
        if self.recording or self.audio_only_recording:
            return
        print("Starting video+audio recording session...")
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
        self.audio_thread = threading.Thread(target=record_audio, args=(audio_file, self.audio_stop_event))
        self.audio_thread.start()

        self.recording = True
        self.stop_thread = False
        self.size_thread = threading.Thread(target=self.check_video_size)
        self.size_thread.start()

        seg = {
            "video": video_file,
            "audio": audio_file,
            "start_time": start_time,
            "end_time": None
        }
        self.segments.append(seg)

        self.start_stop_btn.setText("Stop Recording")
        self.update_ui()
        print(f"Recording started: {video_file}, {audio_file}, start_time={start_time}")

    def stop_recording(self):
        if not self.recording:
            return
        print("Stopping video+audio recording session...")
        self.recording = False
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
        print(f"Final segment ended at {self.segments[-1]['end_time']}")

        GPIO.output(VDO_LED_PIN, GPIO.LOW)
        self.start_stop_btn.setText("Start Recording")
        self.update_ui()

        # Retry any failed uploads first
        self.retry_failed_uploads()

        # Merge and upload each segment
        for seg in self.segments:
            merged_filename = seg["video"].replace(".mp4", "_merged.mp4")
            print(f"Merging {seg['video']} and {seg['audio']} -> {merged_filename}")
            if self.merge_audio_video(seg["video"], seg["audio"], merged_filename):
                # Upload the merged video
                if not self.upload_file(merged_filename, seg["start_time"], seg["end_time"], media_type="video"):
                    failed_path = os.path.join(FAILED_DIR, os.path.basename(merged_filename))
                    shutil.move(merged_filename, failed_path)
                    print(f"Moved to failed uploads: {failed_path}")
            else:
                print("Merge failed for segment:", seg)
        self.segments.clear()

    def check_video_size(self):
        # Split segments if video grows beyond 10MB
        while self.recording and not self.stop_thread:
            current_video = self.segments[-1]["video"]
            if os.path.exists(current_video) and os.path.getsize(current_video) >= 10 * 1024 * 1024:
                print(f"Video file {current_video} reached 10MB, splitting segment...")
                self.split_segment()
            time.sleep(1)

    def split_segment(self):
        # End current segment, start new one
        try:
            self.picam2.stop_recording()
        except:
            pass

        if self.audio_thread and self.audio_thread.is_alive():
            self.audio_stop_event.set()
            self.audio_thread.join()

        self.segments[-1]["end_time"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"Segment {self.seg_num} ended at {self.segments[-1]['end_time']}")

        self.seg_num += 1
        new_video_file = self.get_video_filename(self.session_no, self.seg_num)
        new_audio_file = self.get_audio_filename(self.session_no, self.seg_num)
        new_seg = {
            "video": new_video_file,
            "audio": new_audio_file,
            "start_time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "end_time": None
        }
        self.segments.append(new_seg)

        # Restart video
        self.picam2.start_and_record_video(new_video_file, duration=None)

        # Restart audio
        self.audio_stop_event = threading.Event()
        self.audio_thread = threading.Thread(target=record_audio, args=(new_audio_file, self.audio_stop_event))
        self.audio_thread.start()

        print(f"Started new segment {self.seg_num}: {new_video_file}, {new_audio_file}")

    # ---------------- Audio-Only Recording ----------------
    def toggle_audio_only(self):
        if not self.audio_only_recording:
            self.start_audio_only()
        else:
            self.stop_audio_only()

    def start_audio_only(self):
        if self.recording or self.audio_only_recording:
            return
        print("Starting audio-only recording...")
        self.audio_only_recording = True
        self.audio_only_start_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.audio_only_filename = self.get_audio_filename(999, 1)  # 999 session for audio-only, arbitrary

        self.audio_only_stop_event = threading.Event()
        self.audio_only_thread = threading.Thread(
            target=record_audio, args=(self.audio_only_filename, self.audio_only_stop_event)
        )
        self.audio_only_thread.start()

        self.audio_only_btn.setText("Stop Audio Only")
        self.update_ui()

    def stop_audio_only(self):
        if not self.audio_only_recording:
            return
        print("Stopping audio-only recording...")
        self.audio_only_recording = False

        if self.audio_only_thread and self.audio_only_thread.is_alive():
            self.audio_only_stop_event.set()
            self.audio_only_thread.join()

        end_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"Audio-only recording ended. File: {self.audio_only_filename}")

        self.audio_only_btn.setText("Record Audio Only")
        self.update_ui()

        # Upload the audio file
        if not self.upload_file(self.audio_only_filename, self.audio_only_start_time, end_time, media_type="audio"):
            failed_path = os.path.join(FAILED_DIR, os.path.basename(self.audio_only_filename))
            shutil.move(self.audio_only_filename, failed_path)
            print(f"Moved audio to failed uploads: {failed_path}")

    # ---------------- Capture Photo ----------------
    def capture_photo(self):
        """
        Capture a single .jpg image, upload it, move to failed_uploads if necessary.
        """
        photo_filename = self.get_image_filename()
        print(f"Capturing photo to {photo_filename}")
        # If the camera is running, we can do:
        self.picam2.capture_file(photo_filename)

        # Attempt upload
        start_time = end_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        success = self.upload_file(photo_filename, start_time, end_time, media_type="image")
        if not success:
            failed_path = os.path.join(FAILED_DIR, os.path.basename(photo_filename))
            shutil.move(photo_filename, failed_path)
            print(f"Moved photo to failed uploads: {failed_path}")
        else:
            print("Photo captured and uploaded successfully!")

    # ---------------- Filename Generators ----------------
    def get_video_filename(self, session_no, seg_num):
        ts = self.format_timestamp()
        return os.path.join(VIDEOS_DIR, f"vdo_{DEVICE_ID}_{session_no}_{seg_num}_{ts}.mp4")

    def get_audio_filename(self, session_no, seg_num):
        ts = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        return os.path.join(AUDIOS_DIR, f"audio_{DEVICE_ID}_{session_no}_{seg_num}_{ts}.wav")

    def get_image_filename(self):
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        return os.path.join(IMAGES_DIR, f"img_{DEVICE_ID}_{ts}.jpg")

    def format_timestamp(self):
        return datetime.datetime.now().strftime("%d%b%y_%H%M%S").lower()

    # ---------------- Merging & Uploading ----------------
    def merge_audio_video(self, video_file, audio_file, output_file):
        """
        Use ffmpeg to merge video and audio into a single mp4.
        """
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
            print(f"Merged into {output_file}")
            return True
        except subprocess.CalledProcessError as e:
            print("ffmpeg merge error:", e)
            return False

    def upload_file(self, file_path, start_time="", end_time="", media_type="video"):
        """
        Upload any file (video, audio, image) to the server.
        Uses different form field names depending on media_type.
          - media_type="video" -> files={"video": f}
          - media_type="audio" -> files={"audio": f}
          - media_type="image" -> files={"image": f}
        """
        field_name = media_type  # "video", "audio", or "image"
        try:
            with open(file_path, "rb") as f:
                files = {field_name: f}
                data = {
                    "device_id": DEVICE_ID,
                    "start_time": start_time,
                    "end_time": end_time
                }
                print(f"Uploading {media_type}: {file_path}")
                response = requests.post(UPLOAD_URL, headers=HEADERS, files=files, data=data)

            if response.status_code == 200:
                result = response.json()
                if result.get("success"):
                    print(f"Upload successful! URL: {result.get('video_link') or result}")
                    os.remove(file_path)
                    print(f"Deleted local file: {file_path}")
                    return True
                else:
                    print("Upload failed:", result)
            else:
                print(f"Error {response.status_code}: {response.text}")
        except Exception as e:
            print(f"Upload Error: {e}")
        return False

    def retry_failed_uploads(self):
        """
        Tries to re-upload any files in failed_uploads. We guess file type by extension:
          .mp4 -> video
          .wav -> audio
          .jpg -> image
        We do not know the original start_time/end_time, so pass empty strings.
        """
        failed_files = os.listdir(FAILED_DIR)
        if not failed_files:
            print("No failed uploads to retry.")
            return

        print(f"Found {len(failed_files)} failed uploads. Retrying...")
        for fname in failed_files:
            ext = os.path.splitext(fname)[1].lower()
            path = os.path.join(FAILED_DIR, fname)
            if ext == ".mp4":
                mtype = "video"
            elif ext == ".wav":
                mtype = "audio"
            elif ext in [".jpg", ".jpeg", ".png"]:
                mtype = "image"
            else:
                print(f"Skipping unrecognized file type: {path}")
                continue

            print(f"Retrying upload for {path} as {mtype}...")
            if self.upload_file(path, "", "", media_type=mtype):
                # Successfully uploaded and deleted
                pass
            else:
                print(f"Still failed, keeping in folder: {path}")

    # ---------------- GPIO Polling ----------------
    def check_gpio(self):
        # Poll the physical start/stop button
        if GPIO.input(VDO_BTN_PIN) == GPIO.LOW:
            if not self.gpio_pressed:
                self.gpio_pressed = True
                # If we are not recording video, start it; otherwise stop
                if not self.recording:
                    self.start_recording()
                else:
                    self.stop_recording()
        else:
            self.gpio_pressed = False

    # ---------------- Cleanup ----------------
    def closeEvent(self, event):
        try:
            # If video is recording, stop it
            if self.recording:
                self.stop_recording()
            # If audio-only is recording, stop it
            if self.audio_only_recording:
                self.stop_audio_only()
            self.picam2.stop()
            self.picam2.close()
            GPIO.cleanup()
        except Exception as e:
            print("Error during cleanup:", e)
        event.accept()


# ---------------- Main ----------------
if __name__ == "__main__":
    try:
        app = QApplication(sys.argv)
        window = MainWindow()
        window.show()
        sys.exit(app.exec_())
    except KeyboardInterrupt:
        print("Exiting...")
        GPIO.cleanup()
