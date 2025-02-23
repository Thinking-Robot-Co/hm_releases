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
from picamera2 import Picamera2, Preview, MappedArray
from libcamera import Transform

import pyaudio
import wave

from PyQt5.QtWidgets import QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton
from PyQt5.QtCore import QTimer, Qt

# For the embedded preview widget:
from picamera2.previews.qt import QGlPicamera2  # or QPicamera2 if you prefer CPU-based

# ---------------- Global Constants and Setup ----------------
CHUNK = 1024
FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 44100

AUDIOS_DIR = "Audios"
VIDEOS_DIR = "Videos"
FAILED_DIR = "failed_uploads"
for d in [AUDIOS_DIR, VIDEOS_DIR, FAILED_DIR]:
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

def record_audio(audio_filename, stop_event):
    """
    Record audio continuously until stop_event is set.
    Saves the audio as a .wav file.
    """
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
        self.setWindowTitle("Raspberry Pi Recording")
        self.showFullScreen()  # Show complete full screen GUI

        # Recording state variables
        self.recording = False
        self.segments = []
        self.session_no = 1
        self.seg_num = 1
        self.audio_thread = None
        self.audio_stop_event = None
        self.stop_thread = False

        # For GPIO polling debounce
        self.gpio_pressed = False

        self.DEVICE_ID = DEVICE_ID
        self.VIDEOS_DIR = VIDEOS_DIR
        self.AUDIOS_DIR = AUDIOS_DIR
        self.FAILED_DIR = FAILED_DIR

        self.UPLOAD_URL = UPLOAD_URL
        self.HEADERS = HEADERS

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
        vbox = QVBoxLayout()
        central_widget.setLayout(vbox)

        # ---- Embed camera preview via QGlPicamera2 ----
        # The QGlPicamera2 widget automatically shows the camera feed
        # once the camera is configured and started.
        self.camera_widget = QGlPicamera2(self.picam2, width=800, height=480, keep_ar=True)
        vbox.addWidget(self.camera_widget, stretch=8)

        # Control panel
        hbox = QHBoxLayout()
        self.start_stop_btn = QPushButton("Start Recording")
        self.start_stop_btn.setFixedHeight(50)
        self.start_stop_btn.clicked.connect(self.toggle_recording)
        hbox.addWidget(self.start_stop_btn)
        vbox.addLayout(hbox, stretch=1)

    def start_camera_preview(self):
        # Configure the camera for preview (vflip if needed)
        preview_config = self.picam2.create_preview_configuration(transform=Transform(vflip=True))
        self.picam2.configure(preview_config)
        # Start the camera (the QGlPicamera2 widget will display automatically)
        self.picam2.start()
        print("Camera preview started.")

    def toggle_recording(self):
        if not self.recording:
            self.start_recording()
        else:
            self.stop_recording()

    def start_recording(self):
        if self.recording:
            return
        print("Starting recording session...")
        self.session_no = 1
        self.seg_num = 1
        self.segments = []
        start_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        video_file = self.get_video_filename(self.session_no, self.seg_num)
        audio_file = self.get_audio_filename(self.session_no, self.seg_num)

        GPIO.output(VDO_LED_PIN, GPIO.HIGH)

        # Start video recording
        # If your picamera2 version supports:
        #    self.picam2.start_and_record_video(video_file, duration=None)
        # then you can use that. Otherwise you might need to do:
        #    self.picam2.start_video_recording(video_file)
        # depending on your exact picamera2 version.
        self.picam2.start_and_record_video(video_file, duration=None)

        # Start audio recording
        self.audio_stop_event = threading.Event()
        self.audio_thread = threading.Thread(target=record_audio, args=(audio_file, self.audio_stop_event))
        self.audio_thread.start()

        self.recording = True
        self.stop_thread = False
        self.size_thread = threading.Thread(target=self.check_video_size)
        self.size_thread.start()

        segment = {
            "video": video_file,
            "audio": audio_file,
            "start_time": start_time,
            "end_time": None
        }
        self.segments.append(segment)

        self.start_stop_btn.setText("Stop Recording")
        print(f"Recording started: video={video_file}, audio={audio_file}, start_time={start_time}")

    def stop_recording(self):
        if not self.recording:
            return
        print("Stopping recording session...")
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

        # Mark end time
        self.segments[-1]["end_time"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"Final segment ended at {self.segments[-1]['end_time']}")

        GPIO.output(VDO_LED_PIN, GPIO.LOW)
        self.start_stop_btn.setText("Start Recording")

        # Retry any failed uploads first
        self.retry_failed_uploads()

        # Merge and upload each segment
        for seg in self.segments:
            merged_filename = seg["video"].replace(".mp4", "_merged.mp4")
            print(f"Merging {seg['video']} and {seg['audio']} into {merged_filename} ...")
            if self.merge_audio_video(seg["video"], seg["audio"], merged_filename):
                if not self.upload_file(merged_filename, seg["start_time"], seg["end_time"]):
                    failed_path = os.path.join(self.FAILED_DIR, os.path.basename(merged_filename))
                    shutil.move(merged_filename, failed_path)
                    print(f"Moved to failed uploads: {failed_path}")
            else:
                print("Merge failed for segment:", seg)
        self.segments.clear()

    def get_video_filename(self, session_no, seg_num):
        current_timestamp = self.format_timestamp()
        filename = f"vdo_{self.DEVICE_ID}_{session_no}_{seg_num}_{current_timestamp}.mp4"
        return os.path.join(self.VIDEOS_DIR, filename)

    def get_audio_filename(self, session_no, seg_num):
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        filename = f"audio_{self.DEVICE_ID}_{session_no}_{seg_num}_{timestamp}.wav"
        return os.path.join(self.AUDIOS_DIR, filename)

    def format_timestamp(self):
        return datetime.datetime.now().strftime("%d%b%y_%H%M%S").lower()

    def split_segment(self):
        """
        Called when the current video segment reaches 10MB.
        Stops current video and audio recordings, marks end time,
        and starts a new segment.
        """
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
        new_segment = {
            "video": new_video_file,
            "audio": new_audio_file,
            "start_time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "end_time": None
        }
        self.segments.append(new_segment)

        # Start new video
        self.picam2.start_and_record_video(new_video_file, duration=None)

        # Start new audio
        self.audio_stop_event = threading.Event()
        self.audio_thread = threading.Thread(target=record_audio, args=(new_audio_file, self.audio_stop_event))
        self.audio_thread.start()

        print(f"Started new segment {self.seg_num}: video={new_video_file}, audio={new_audio_file}")

    def check_video_size(self):
        while self.recording and not self.stop_thread:
            current_video = self.segments[-1]["video"]
            if os.path.exists(current_video) and os.path.getsize(current_video) >= 10 * 1024 * 1024:
                print(f"Video file {current_video} reached 10MB, splitting segment...")
                self.split_segment()
            time.sleep(1)

    def merge_audio_video(self, video_file, audio_file, output_file):
        """
        Use ffmpeg to merge video and audio.
        The command copies the video stream and encodes audio to AAC.
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

    def upload_file(self, file_path, start_time, end_time):
        try:
            with open(file_path, "rb") as f:
                files = {"video": f}
                data = {
                    "device_id": self.DEVICE_ID,
                    "start_time": start_time,
                    "end_time": end_time
                }
                print(f"Uploading: {file_path} with start_time={start_time} and end_time={end_time}")
                response = requests.post(self.UPLOAD_URL, headers=self.HEADERS, files=files, data=data)
            if response.status_code == 200:
                result = response.json()
                if result.get("success"):
                    print(f"Upload successful! Video URL: {result.get('video_link')}")
                    os.remove(file_path)
                    print(f"Deleted: {file_path}")
                    return True
                else:
                    print("Upload failed:", result)
            else:
                print(f"Error {response.status_code}: {response.text}")
        except Exception as e:
            print(f"Upload Error: {e}")
        return False

    def retry_failed_uploads(self):
        failed_files = [f for f in os.listdir(self.FAILED_DIR) if f.endswith(".mp4")]
        if failed_files:
            print(f"Found {len(failed_files)} failed uploads. Retrying...")
            for failed in failed_files:
                failed_path = os.path.join(self.FAILED_DIR, failed)
                print(f"Retrying upload for {failed_path}")
                if self.upload_file(failed_path, "", ""):
                    if os.path.exists(failed_path):
                        os.remove(failed_path)
                        print(f"Successfully uploaded & deleted: {failed_path}")
                else:
                    print(f"Still failed, keeping in folder: {failed_path}")
        else:
            print("No failed videos to retry.")

    def check_gpio(self):
        # Poll the GPIO button
        if GPIO.input(VDO_BTN_PIN) == GPIO.LOW:
            if not self.gpio_pressed:
                self.gpio_pressed = True
                if not self.recording:
                    self.start_recording()
                else:
                    self.stop_recording()
        else:
            self.gpio_pressed = False

    def closeEvent(self, event):
        # Cleanup on window close
        try:
            if self.recording:
                self.stop_recording()
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
        window.show()
        sys.exit(app.exec_())
    except KeyboardInterrupt:
        print("Exiting...")
        GPIO.cleanup()
