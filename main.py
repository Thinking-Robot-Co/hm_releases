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
        self.setWindowTitle("Full Sensor Wide View Recorder")
        self.resize(1280, 720)

        self.picam2 = Picamera2()

        # Get sensor modes and use the first one (assumed to be full sensor resolution).
        sensor_modes = self.picam2.sensor_modes
        if sensor_modes:
            sensor_mode = sensor_modes[0]
            # Extract width and height from the sensor mode's "size"
            try:
                full_width, full_height = sensor_mode["size"]
            except Exception:
                # In case "size" is a Size object
                full_width = sensor_mode["size"].width
                full_height = sensor_mode["size"].height
        else:
            full_width, full_height = 640, 480  # fallback values

        # Create default preview configuration.
        config = self.picam2.create_preview_configuration()
        self.picam2.configure(config)
        # Force full sensor view by setting ScalerCrop to the sensor's full resolution.
        self.picam2.set_controls({"ScalerCrop": (0, 0, full_width, full_height)})

        # Create preview widget.
        self.preview_widget = QGlPicamera2(self.picam2, keep_ar=True)
        self.picam2.start()

        self.recording = False
        self.video_file = None

        # Build GUI layout.
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
                data = {"device_id": DEVICE_ID, "file_type": "video", "start_time": "", "end_time": ""}
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
