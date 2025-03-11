#!/usr/bin/env python3

### THIS IS SOMETHING NEW ###
import sys
import threading
import os
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget,
    QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QCheckBox
)
from PyQt5.QtCore import Qt, pyqtSignal, pyqtSlot
from camera import Camera
from recorder import AudioRecorder, VideoRecorder
from uploader import upload_image, upload_audio, upload_video
from gpio_handler import GPIOHandler
# Import the failed-to-upload directory constants from utils.py
from utils import FAILED_IMAGES_DIR, FAILED_VIDEOS_DIR, FAILED_AUDIOS_DIR

class MainWindow(QMainWindow):
    imageCaptured = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Construction Site Helmet - Preview")
        self.showFullScreen()

        self.imageCaptured.connect(self.finish_capture)

        # Initialize camera.
        self.camera = Camera()
        self.preview_widget = self.camera.start_preview()

        # Initialize recorders.
        self.audio_recorder = AudioRecorder()
        # Pass audio_recorder into VideoRecorder for segmented merged recording.
        self.video_recorder = VideoRecorder(self.camera, self.audio_recorder)
        self.audio_recording = False
        self.video_recording = False

        # Set up layout.
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        main_layout.addWidget(self.preview_widget, stretch=1)

        # Bottom controls.
        bottom_layout = QHBoxLayout()
        bottom_layout.setSpacing(10)

        # Video toggle button.
        self.video_btn = QPushButton("Start Video")
        self.video_btn.setFixedSize(150, 40)
        self.video_btn.clicked.connect(self.toggle_video_recording)
        bottom_layout.addWidget(self.video_btn)

        # Checkbox for recording audio with video.
        self.record_audio_checkbox = QCheckBox("Record Audio with Video")
        self.record_audio_checkbox.setChecked(True)
        bottom_layout.addWidget(self.record_audio_checkbox)

        # Capture Image button.
        self.capture_btn = QPushButton("Capture Image")
        self.capture_btn.setFixedSize(150, 40)
        self.capture_btn.clicked.connect(self.handle_capture_image)
        bottom_layout.addWidget(self.capture_btn)

        # Audio toggle button.
        self.audio_btn = QPushButton("Start Audio")
        self.audio_btn.setFixedSize(150, 40)
        self.audio_btn.clicked.connect(self.toggle_audio_recording)
        bottom_layout.addWidget(self.audio_btn)

        bottom_layout.addStretch()

        # Close Session button.
        self.close_btn = QPushButton("Close Session")
        self.close_btn.setFixedSize(150, 40)
        self.close_btn.clicked.connect(self.close_session)
        bottom_layout.addWidget(self.close_btn)

        main_layout.addLayout(bottom_layout)

        self.status_label = QLabel("Ready")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setStyleSheet("background-color: #EFEFEF; padding: 5px;")
        main_layout.addWidget(self.status_label)

        # Initialize GPIO handler.
        self.gpio_handler = GPIOHandler(self)

        # Attempt to re-upload any previously failed files on startup.
        self.attempt_reupload_failed_files()

    def attempt_reupload_failed_files(self):
        # Define directories to scan for failed uploads.
        failed_dirs = {
            "image": FAILED_IMAGES_DIR,
            "audio": FAILED_AUDIOS_DIR,
            "video": FAILED_VIDEOS_DIR,
        }

        # Iterate over file types and directories.
        for file_type, failed_dir in failed_dirs.items():
            if not os.path.exists(failed_dir):
                continue

            for file_name in os.listdir(failed_dir):
                file_path = os.path.join(failed_dir, file_name)
                print(f"Attempting re-upload of {file_path}")

                if file_type == "image":
                    success, resp = upload_image(file_path)
                elif file_type == "audio":
                    success, resp = upload_audio(file_path)
                elif file_type == "video":
                    success, resp = upload_video(file_path)

                if success:
                    os.remove(file_path)
                    print(f"Successfully re-uploaded and deleted {file_path}")
                else:
                    print(f"Failed again to upload {file_path}: {resp}")

    def handle_capture_image(self):
        self.capture_btn.setEnabled(False)
        threading.Thread(target=self.capture_image_worker, daemon=True).start()

    def capture_image_worker(self):
        msg = ""
        try:
            image_path = self.camera.capture_image()
            success, resp = upload_image(image_path)
            if success:
                os.remove(image_path)
                msg = f"Image captured & uploaded: {image_path}"
            else:
                msg = f"Image captured but upload failed: {resp}"
        except Exception as e:
            msg = f"Image capture error: {e}"
        finally:
            self.imageCaptured.emit(msg)

    @pyqtSlot(str)
    def finish_capture(self, msg):
        self.status_label.setText(msg)
        self.capture_btn.setEnabled(True)

    def toggle_audio_recording(self):
        if not self.audio_recording:
            self.audio_recorder.start_recording()
            self.audio_recording = True
            self.audio_btn.setText("Stop Audio")
            self.status_label.setText("Audio recording started...")
        else:
            audio_file = self.audio_recorder.stop_recording()
            self.audio_recording = False
            self.audio_btn.setText("Start Audio")
            success, resp = upload_audio(audio_file, "", "")
            if success:
                os.remove(audio_file)
                self.status_label.setText(f"Audio recorded & uploaded: {audio_file}")
            else:
                self.status_label.setText(f"Audio recorded but upload failed: {resp}")

    def toggle_video_recording(self):
        record_audio_with_video = self.record_audio_checkbox.isChecked()
        # Re-attempt to upload any failed files before starting a new session.
        self.attempt_reupload_failed_files()

        if not self.video_recording:
            self.video_recorder.start_recording(with_audio=record_audio_with_video)
            self.video_recording = True
            self.video_btn.setText("Stop Video")
            self.status_label.setText("Video recording started...")
        else:
            segments = self.video_recorder.stop_recording()
            self.video_recording = False
            self.video_btn.setText("Start Video")
            if record_audio_with_video:
                if segments:
                    msg = "Video segments merged & recorded: " + ", ".join(segments)
                    for mf in segments:
                        success, resp = upload_video(mf, "", "")
                        if success:
                            os.remove(mf)
                    self.status_label.setText(msg)
                else:
                    self.status_label.setText("No video segments recorded.")
            else:
                seg_info = ", ".join(segments)
                self.status_label.setText(f"Video recorded. Segments: {seg_info}")

    def close_session(self):
        self.camera.stop_preview()
        if self.audio_recording:
            self.audio_recorder.stop_recording()
        if self.video_recording:
            self.video_recorder.stop_recording()
        self.gpio_handler.cleanup()
        QApplication.quit()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())