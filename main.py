#!/usr/bin/env python3
import sys
import os
import datetime
import requests
from PyQt5.QtWidgets import QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel
from picamera2 import Picamera2
from picamera2.previews.qt import QGlPicamera2

# Server upload settings.
UPLOAD_URL = "https://centrix.co.in/v_api/upload"
API_KEY = "DDjgMfxLqhxbNmaBoTkfBJkhMxNxkPwMgGjPUwCOaJRCBrvtUX"
DEVICE_ID = "raspberry_pi_01"

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Full Sensor View Video Recorder")
        self.resize(1280, 720)

        self.picam2 = Picamera2()
        
        # Optionally, inspect available sensor modes:
        # sensor_modes = self.picam2.sensor_modes
        # print("Available sensor modes:", sensor_modes)
        # If you know which sensor mode libcamera-hello uses, you can select it here.
        # For example, to use the first available sensor mode:
        # chosen_mode = sensor_modes[0]['id'] if sensor_modes else None
        
        # Use the video configuration (which often matches libcamera-hello) and explicitly set the ROI to full sensor.
        config = self.picam2.create_video_configuration()
        # Set transform: no flips, no rotation, and full sensor ROI.
        config["transform"] = {
            "hflip": False,
            "vflip": False,
            "rotation": 0,
            "roi": (0.0, 0.0, 1.0, 1.0)  # (x, y, width, height) in normalized coordinates.
        }
        self.picam2.configure(config)
        
        # Create and start the preview widget.
        self.preview_widget = QGlPicamera2(self.picam2, keep_ar=True)
        self.picam2.start()

        self.recording = False
        self.video_file = None

        # Build a simple GUI.
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)
        layout.addWidget(self.preview_widget)

        button_layout = QHBoxLayout()
        self.record_button = QPushButton("Start Recording")
        self.record_button.clicked.connect(self.toggle_recording)
        button_layout.addWidget(self.record_button)

        self.upload_button = QPushButton("Upload Video")
        self.upload_button.clicked.connect(self.upload_video)
        button_layout.addWidget(self.upload_button)

        layout.addLayout(button_layout)
        self.status_label = QLabel("Status: Ready")
        layout.addWidget(self.status_label)

    def toggle_recording(self):
        if not self.recording:
            self.video_file = self.generate_filename()
            self.picam2.start_and_record_video(self.video_file)
            self.recording = True
            self.record_button.setText("Stop Recording")
            self.status_label.setText("Recording started...")
        else:
            self.picam2.stop_recording()
            self.recording = False
            self.record_button.setText("Start Recording")
            self.status_label.setText(f"Recording stopped. Saved to {self.video_file}")

    def generate_filename(self):
        now = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        return os.path.join(os.getcwd(), f"video_{now}.mp4")

    def upload_video(self):
        if not self.video_file or not os.path.exists(self.video_file):
            self.status_label.setText("No video file to upload.")
            return

        self.status_label.setText("Uploading video...")
        try:
            with open(self.video_file, "rb") as f:
                files = {"video": f}
                data = {
                    "device_id": DEVICE_ID,
                    "file_type": "video",
                    "start_time": "",  # Optionally, add timing details.
                    "end_time": ""
                }
                headers = {"X-API-KEY": API_KEY}
                response = requests.post(UPLOAD_URL, headers=headers, files=files, data=data)
            if response.status_code == 200:
                self.status_label.setText("Upload successful!")
            else:
                self.status_label.setText(f"Upload failed: {response.text}")
        except Exception as e:
            self.status_label.setText(f"Upload error: {e}")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())
