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

    def apply_video_transform(self, hflip=False, vflip=False, rotation=0, width=None, height=None):
        """
        Apply transformation settings for video (and preview).
        Optionally adjust output dimensions.
        """
        # Create a fresh preview configuration.
        config = self.picam2.create_preview_configuration()
        
        # Add transform settings.
        config["transform"] = {"hflip": hflip, "vflip": vflip, "rotation": rotation}
        
        # Optionally set new dimensions (if provided).
        if width is not None and height is not None:
            # Here, 'size' should be a tuple (width, height)
            config["size"] = (width, height)
        
        # Reconfigure the camera with the new settings.
        self.picam2.configure(config)

    def start_preview(self):
        if self.preview_started:
            return self.preview_widget

        self.preview_widget = QGlPicamera2(self.picam2, keep_ar=True)
        # config = self.picam2.create_preview_configuration()
        config = self.picam2.create_preview_configuration(sensor={'output_size': (1296, 972)})

        # (Optional: if you want the preview to always use a specific transform,
        # you can call apply_video_transform here with your default settings.)
        # For example:
        # self.apply_video_transform(hflip=True, vflip=False, rotation=90, width=1280, height=720)
        self.picam2.configure(config)
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
