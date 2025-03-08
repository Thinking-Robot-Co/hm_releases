#!/usr/bin/env python3
import sys
import os
import datetime
import requests
from PyQt5.QtWidgets import QApplication, QWidget, QVBoxLayout, QPushButton, QLabel
from picamera2 import Picamera2
from picamera2.previews.qt import QGlPicamera2

# Configuration for upload (change these to your server settings)
UPLOAD_URL = "https://example.com/upload"  # Your server URL
DEVICE_ID = "raspberry_pi_01"
API_KEY = "your_api_key_here"

class VideoUploader(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Video Uploader")
        self.recording = False
        self.video_file = None

        # Initialize camera without applying any transform to get full view.
        self.picam2 = Picamera2()
        config = self.picam2.create_preview_configuration()
        self.picam2.configure(config)
        self.picam2.start()

        # Set up GUI layout
        layout = QVBoxLayout(self)
        self.preview_widget = QGlPicamera2(self.picam2, keep_ar=True)
        layout.addWidget(self.preview_widget)

        self.record_button = QPushButton("Start Recording")
        self.record_button.clicked.connect(self.toggle_recording)
        layout.addWidget(self.record_button)

        self.status_label = QLabel("Ready")
        layout.addWidget(self.status_label)

    def toggle_recording(self):
        if not self.recording:
            # Start recording with full view (no transformation applied)
            self.video_file = self.generate_video_filename()
            self.status_label.setText("Recording...")
            self.record_button.setText("Stop Recording")
            self.recording = True
            # Use the camera's default recording function; this method is similar to what libcamera-hello uses.
            self.picam2.start_and_record_video(self.video_file)
        else:
            # Stop recording
            self.picam2.stop_recording()
            self.recording = False
            self.record_button.setText("Start Recording")
            self.status_label.setText("Recording stopped. Uploading...")
            if self.upload_video(self.video_file):
                self.status_label.setText("Upload successful!")
                os.remove(self.video_file)
            else:
                self.status_label.setText("Upload failed.")

    def generate_video_filename(self):
        now = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        return os.path.join(os.getcwd(), f"video_{now}.mp4")

    def upload_video(self, file_path):
        try:
            with open(file_path, "rb") as f:
                files = {"video": f}
                data = {"device_id": DEVICE_ID}
                headers = {"X-API-KEY": API_KEY}
                response = requests.post(UPLOAD_URL, headers=headers, files=files, data=data)
            if response.status_code == 200:
                return True
            else:
                print("Upload failed:", response.text)
                return False
        except Exception as e:
            print("Upload exception:", e)
            return False

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = VideoUploader()
    window.show()
    sys.exit(app.exec_())
