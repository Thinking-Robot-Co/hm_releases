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
        """
        Configures the preview transformation and optionally sets resolution, FPS, and digital zoom.
        
        Parameters:
        hflip (bool): Horizontal flip.
        vflip (bool): Vertical flip.
        rotation (int): Rotation angle in degrees (must be 0, 90, 180, or 270).
        width (int): Desired output width.
        height (int): Desired output height.
        fps (int): Desired frames per second (if supported by the sensor).
        digital_zoom (tuple): Normalized zoom region (x, y, width, height). (0, 0, 1, 1) is full sensor view.
        """
        # Create a fresh preview configuration.
        config = self.picam2.create_preview_configuration()
        
        # IMPORTANT: Use 'rotate' instead of 'rotation'
        config["transform"] = {"hflip": hflip, "vflip": vflip, "rotate": rotation}
        
        # Set resolution if provided.
        if width is not None and height is not None:
            config["size"] = (width, height)
        
        # Apply the new configuration.
        self.picam2.configure(config)
        
        # Set digital zoom (full sensor view when using (0,0,1,1)).
        self.picam2.set_controls({"DigitalZoom": digital_zoom})
        
        # Optionally, set the frame rate if provided.
        if fps is not None:
            self.picam2.set_controls({"FrameRate": fps})


    def start_preview(self):
        if self.preview_started:
            return self.preview_widget

        # Optionally adjust the preview settings here:
        self.apply_video_transform(
            hflip=False,
            vflip=False,
            rotation=0,
            width=1920,
            height=1080,
            fps=30,
            digital_zoom=(0.0, 0.0, 1.0, 1.0)
        )
        
        self.preview_widget = QGlPicamera2(self.picam2, keep_ar=True)
        config = self.picam2.create_preview_configuration()
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
