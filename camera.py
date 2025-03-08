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

    def apply_video_transform(self, hflip=False, vflip=False, rotation=0, width=None, height=None, zoom=1.0):
        # Create a fresh preview configuration.
        config = self.picam2.create_preview_configuration()
        transform = {"hflip": hflip, "vflip": vflip, "rotation": rotation}

        # If zoom is greater than 1, compute a centered crop.
        if zoom > 1.0 and width is not None and height is not None:
            crop_w = int(width / zoom)
            crop_h = int(height / zoom)
            # Calculate offsets to center the crop.
            x_offset = (width - crop_w) // 2
            y_offset = (height - crop_h) // 2
            # Assuming Picamera2 supports a crop key (check docs)
            transform["crop"] = (x_offset, y_offset, crop_w, crop_h)
        
        config["transform"] = transform

        # Optionally adjust output dimensions.
        if width is not None and height is not None:
            config["size"] = (width, height)

        self.picam2.configure(config)


    def start_preview(self):
        if self.preview_started:
            return self.preview_widget

        self.preview_widget = QGlPicamera2(self.picam2, keep_ar=True)
        config = self.picam2.create_preview_configuration()
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
