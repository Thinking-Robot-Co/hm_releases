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

    def apply_video_transform(self, hflip=False, vflip=False, rotation=0, width=None, height=None, fps=None, zoom=None):                                        
        """
        Apply transformation settings for video (and preview).
        Optionally adjust output dimensions.
        """
        # Create a fresh preview configuration.
        config = self.picam2.create_preview_configuration()
        
        # Set transform settings. (Use booleans as-is.)
        config["transform"] = {
            "hflip": bool(hflip),
            "vflip": bool(vflip),
            "rotation": int(rotation)
        }
        
        # Set resolution if provided.
        if width is not None and height is not None:
            config["size"] = (int(width), int(height))
        
        # Set FPS if provided.
        if fps is not None:
            config["controls"] = {"FrameRate": float(fps)}
        
        # Set crop (for zoom) if provided.
        if zoom is not None:
            # Instead of a tuple, use a dict with explicit keys.
            # For full sensor view, use: {"x": 0.0, "y": 0.0, "width": 1.0, "height": 1.0}
            if isinstance(zoom, tuple) and len(zoom) == 4:
                config["crop"] = {
                    "x": float(zoom[0]),
                    "y": float(zoom[1]),
                    "width": float(zoom[2]),
                    "height": float(zoom[3])
                }
            else:
                config["crop"] = zoom

        # Apply the configuration.
        self.picam2.configure(config)



    def start_preview(self):
        if self.preview_started:
            return self.preview_widget

        self.preview_widget = QGlPicamera2(self.picam2, keep_ar=True)
        self.apply_video_transform(
            hflip=True,
            vflip=False,
            rotation=90,
            width=3840,       # 4K resolution width
            height=2160,      # 4K resolution height
            fps=30,           # Frames per second
            zoom=(0.0, 0.0, 1.0, 1.0)  # Full sensor view (no digital zoom)
        )
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
