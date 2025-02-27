#!/usr/bin/env python3
import sys
from PyQt5.QtWidgets import QApplication, QMainWindow, QLabel, QHBoxLayout, QVBoxLayout, QWidget, QPushButton
from camera import CameraController
from recorder import AudioRecorder, VideoRecorder
from merger import merge_audio_video
import uploader
import gpio_handler  # Import our GPIO module

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Construction Site Helmet Recorder")
        self.camera_controller = CameraController()
        self.audio_recorder = AudioRecorder()
        self.video_recorder = VideoRecorder(self.camera_controller)
        self.audio_recording = False
        self.video_recording = False
        self.init_ui()

        # Setup GPIO handler with callbacks.
        self.gpio_handler = gpio_handler.GPIOHandler(
            video_callback=self.handle_gpio_video,
            audio_callback=self.handle_gpio_audio,
            image_callback=self.handle_gpio_image
        )
        self.gpio_handler.start()

    def init_ui(self):
        # Main widget and layout.
        central_widget = QWidget()
        main_layout = QHBoxLayout()

        # Left: Camera preview widget.
        self.camera_preview = self.camera_controller.start_preview()
        if self.camera_preview:
            main_layout.addWidget(self.camera_preview, 3)
        else:
            error_label = QLabel("Camera preview not available.")
            main_layout.addWidget(error_label, 3)

        # Right: Controls and status messages.
        right_layout = QVBoxLayout()
        self.status_label = QLabel("Status: Ready")
        right_layout.addWidget(self.status_label)

        # Capture Image button.
        capture_button = QPushButton("Capture Image")
        capture_button.clicked.connect(self.handle_capture_image)
        right_layout.addWidget(capture_button)

        # Toggle Audio Recording button.
        self.audio_button = QPushButton("Start Audio Recording")
        self.audio_button.clicked.connect(self.handle_audio_recording)
        right_layout.addWidget(self.audio_button)

        # Toggle Video Recording button.
        self.video_button = QPushButton("Start Video Recording")
        self.video_button.clicked.connect(self.handle_video_recording)
        right_layout.addWidget(self.video_button)

        # Merge Last A/V button.
        merge_button = QPushButton("Merge Last A/V")
        merge_button.clicked.connect(self.handle_merge_av)
        right_layout.addWidget(merge_button)
        
        # Retry Failed Uploads button.
        retry_button = QPushButton("Retry Failed Uploads")
        retry_button.clicked.connect(self.handle_retry_uploads)
        right_layout.addWidget(retry_button)

        main_layout.addLayout(right_layout, 1)
        central_widget.setLayout(main_layout)
        self.setCentralWidget(central_widget)
        print("Main window UI initialized with camera preview, controls, and GPIO integration.")

    # GPIO callback wrappers.
    def handle_gpio_video(self):
        print("GPIO: Video button pressed")
        self.handle_video_recording()

    def handle_gpio_audio(self):
        print("GPIO: Audio button pressed")
        self.handle_audio_recording()

    def handle_gpio_image(self):
        print("GPIO: Image button pressed")
        self.handle_capture_image()

    def handle_capture_image(self):
        self.status_label.setText("Status: Capturing image...")
        filename = self.camera_controller.capture_image()
        if filename:
            self.status_label.setText(f"Status: Image saved as {filename}")
        else:
            self.status_label.setText("Status: Image capture failed.")

    def handle_audio_recording(self):
        if not self.audio_recording:
            self.audio_recorder.start_recording()
            self.audio_recording = True
            self.audio_button.setText("Stop Audio Recording")
            self.status_label.setText("Status: Audio recording started.")
        else:
            filename = self.audio_recorder.stop_recording()
            self.audio_recording = False
            self.audio_button.setText("Start Audio Recording")
            if filename:
                self.status_label.setText(f"Status: Audio saved as {filename}")
            else:
                self.status_label.setText("Status: Audio recording failed.")

    def handle_video_recording(self):
        if not self.video_recording:
            self.video_recorder.start_recording()
            self.video_recording = True
            self.video_button.setText("Stop Video Recording")
            self.status_label.setText("Status: Video recording started.")
        else:
            segments = self.video_recorder.stop_recording()
            self.video_recording = False
            self.video_button.setText("Start Video Recording")
            self.status_label.setText(f"Status: Video recording stopped. {len(segments)} segment(s) created.")

    def handle_merge_av(self):
        video_segments = self.video_recorder.segments
        audio_file = self.audio_recorder.audio_file
        if video_segments and audio_file:
            video_file = video_segments[0]["video"]
            output_file = video_file.replace(".mp4", "_merged.mp4")
            success = merge_audio_video(video_file, audio_file, output_file)
            if success:
                self.status_label.setText(f"Status: Merged file created: {output_file}")
            else:
                self.status_label.setText("Status: Merging failed.")
        else:
            self.status_label.setText("Status: Insufficient recordings for merging.")

    def handle_retry_uploads(self):
        uploader.retry_failed_uploads()
        self.status_label.setText("Status: Retried failed uploads.")

    def closeEvent(self, event):
        self.camera_controller.stop_preview()
        if self.audio_recording:
            self.audio_recorder.stop_recording()
        if self.video_recording:
            self.video_recorder.stop_recording()
        if hasattr(self, 'gpio_handler'):
            self.gpio_handler.stop()
        event.accept()

def main():
    print("Starting application...")
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    print("Application window is now visible.")
    sys.exit(app.exec_())

if __name__ == '__main__':
    main()
