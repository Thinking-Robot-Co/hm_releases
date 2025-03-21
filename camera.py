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
        config = self.picam2.create_preview_configuration()
        config["transform"] = {"hflip": hflip, "vflip": vflip, "rotation": rotation}
        if width is not None and height is not None:
            config["size"] = (width, height)
        self.picam2.configure(config)

    def start_preview(self):
        if self.preview_started:
            return self.preview_widget

        self.preview_widget = QGlPicamera2(self.picam2, keep_ar=True)
        config = self.picam2.create_preview_configuration(sensor={'output_size': (1296, 972)})
        self.picam2.configure(config)
        self.picam2.start()
        self.preview_started = True
        return self.preview_widget
		
    def stop_preview(self):
        if self.preview_started:
            self.picam2.stop()
            self.preview_started = False

    def capture_image(self, media_category):
        """
        Captures an image and saves it with the naming convention:
        image_<num>_<date>_<time>_<media category>.jpg
        where for images, start and end times are the same.
        """
        now = datetime.datetime.now()
        date_str = now.strftime("%d%b%Y").lower()
        time_str = now.strftime("%H%M%S")
        filename = os.path.join("Images", f"image_{self.image_counter}_{date_str}_{time_str}_{media_category}.jpg")
        self.picam2.capture_file(filename)
        self.image_counter += 1
        return filename
