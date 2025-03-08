#!/usr/bin/env python3
import os
import datetime
from picamera2 import Picamera2
from picamera2.previews.qt import QGlPicamera2

class Camera:
    def __init__(self):
        self.picam2 = Picamera2()
        self.preview_widget = None
        self.preview_started = False
        self.image_counter = 1
        os.makedirs("Images", exist_ok=True)

    def apply_video_transform(self, hflip=False, vflip=False, rotation=0, width=None, height=None, fps=None, digital_zoom=(0.0, 0.0, 1.0, 1.0)):
        # Create a fresh preview configuration.
        config = self.picam2.create_preview_configuration()
        
        # Use 'rotate' as the key (Picamera2 expects "rotate").
        config["transform"] = {"hflip": hflip, "vflip": vflip, "rotate": rotation}
        
        if width is not None and height is not None:
            config["size"] = (width, height)
        
        # Apply the configuration.
        self.picam2.configure(config)
        
        # Set additional controls.
        self.picam2.set_controls({"DigitalZoom": digital_zoom})
        if fps is not None:
            self.picam2.set_controls({"FrameRate": fps})



    def start_preview(self):
        if self.preview_started:
            return self.preview_widget

        # Create the preview widget.
        self.preview_widget = QGlPicamera2(self.picam2, keep_ar=True)
        
        # Apply your desired transform settings.
        self.apply_video_transform(
            hflip=True,
            vflip=False,
            rotation=90,           # Allowed values: 0, 90, 180, or 270.
            width=1280,
            height=720
        )
        
        # Start the camera with the applied configuration.
        self.picam2.start()
        self.preview_started = True
        return self.preview_widget


		
    def stop_preview(self):
        if self.preview_started:
            self.picam2.stop()
            self.preview_started = False

    def capture_image(self):
        """
        Captures an image and saves it with the naming convention:
        img_(num)_<date>_<time>.jpg  
        where <date> is day, abbreviated month (lowercase), year and <time> is HHMMSS.
        """
        now = datetime.datetime.now()
        date_str = now.strftime("%d%b%Y").lower()  # e.g. 12feb2021
        time_str = now.strftime("%H%M%S")
        filename = os.path.join("Images", f"img_{self.image_counter}_{date_str}_{time_str}.jpg")
        self.picam2.capture_file(filename)
        self.image_counter += 1
        return filename
