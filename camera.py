#!/usr/bin/env python3
import os
import datetime
from picamera2 import Picamera2
from picamera2.previews.qt import QGlPicamera2
from libcamera import Transform


class Camera:
    def __init__(self):
        self.picam2 = Picamera2()
        self.preview_widget = None
        self.preview_started = False
        self.image_counter = 1
        os.makedirs("Images", exist_ok=True)

        # Apply transform ONCE at initialization
        self.transform = Transform(hflip=True, vflip=True)

    def start_preview(self):
        """
        Starts the preview with a 180-degree rotated image.
        """
        if self.preview_started:
            return self.preview_widget

        # Create preview configuration with transform
        config = self.picam2.create_preview_configuration(
            transform=self.transform,
            sensor={'output_size': (1296, 972)}
        )
        self.picam2.configure(config)

        # Start preview widget
        self.preview_widget = QGlPicamera2(self.picam2, keep_ar=True)
        self.picam2.start()
        self.preview_started = True
        return self.preview_widget

    def stop_preview(self):
        """
        Stops live preview.
        """
        if self.preview_started:
            self.picam2.stop()
            self.preview_started = False

    def capture_image(self, media_category="general"):
        """
        Captures a rotated still image.
        Saves as: img_<count>_<date>_<time>_<category>.jpg
        """
        # Apply rotated still config
        still_config = self.picam2.create_still_configuration(transform=self.transform)
        self.picam2.configure(still_config)

        sanitized_category = media_category.replace(" ", "_").lower()
        now = datetime.datetime.now()
        date_str = now.strftime("%d%b%Y").lower()
        time_str = now.strftime("%H%M%S")
        filename = os.path.join(
            "Images",
            f"img_{self.image_counter}_{date_str}_{time_str}_{sanitized_category}.jpg"
        )

        try:
            self.picam2.start()
            self.picam2.capture_file(filename)
        except Exception as e:
            raise Exception("Capture failed: " + str(e))

        self.image_counter += 1
        return filename

    def update_controls(self, controls):
        """
        Update camera controls in real-time.
        Maps slider values (0–100) → (0.0–1.0).
        """
        normalized_controls = {key: value / 100.0 for key, value in controls.items()}
        try:
            self.picam2.set_controls(normalized_controls)
        except Exception as e:
            print("Error updating camera controls:", e)
