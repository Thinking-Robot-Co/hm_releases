#!/usr/bin/env python3
from picamera2 import Picamera2
from picamera2.previews.qt import QGlPicamera2
from PIL import Image
import utils

class CameraController:
    def __init__(self, width=1280, height=720, framerate=30):
        self.width = width
        self.height = height
        self.framerate = framerate
        self.picam2 = None
        self.preview_widget = None
        self.initialized = False

    def initialize(self):
        try:
            self.picam2 = Picamera2()
            config = self.picam2.create_preview_configuration(
                main={"size": (self.width, self.height)}
            )
            self.picam2.configure(config)
            self.initialized = True
            print(f"Camera initialized with resolution {self.width}x{self.height}")
        except Exception as e:
            print("Error initializing camera:", e)
            self.initialized = False

    def start_preview(self):
        if not self.initialized:
            self.initialize()
        if self.initialized:
            self.picam2.start()
            self.preview_widget = QGlPicamera2(self.picam2)
            print("Camera preview started.")
            return self.preview_widget
        else:
            print("Camera initialization failed; preview not started.")
            return None

    def stop_preview(self):
        if self.initialized and self.picam2 is not None:
            self.picam2.stop()
            print("Camera preview stopped.")

    def capture_image(self, device_id="helmet"):
        """
        Capture a single image from the current preview.
        Returns the filename of the saved image or None if it fails.
        """
        if not self.initialized:
            print("Camera not initialized, cannot capture image.")
            return None

        try:
            # Capture image from the current preview
            arr = self.picam2.capture_array("main")
            # Convert the array to a PIL Image (ensure it's in RGB format)
            image = Image.fromarray(arr).convert("RGB")
            # Generate a unique filename using utils
            filename = utils.get_image_filename(device_id=device_id)
            # Save the image as a JPEG
            image.save(filename, format="JPEG")
            print(f"Image captured and saved as {filename}")
            return filename
        except Exception as e:
            print("Error capturing image:", e)
            return None
