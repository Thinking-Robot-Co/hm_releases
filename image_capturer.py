# image_capturer.py
import time
import cv2
import threading
from picamera2 import Picamera2
from libcamera import Transform

class ImageCapturer:
    def __init__(self):
        self.latest_frame = None  # tuple: (frame_bgr, jpeg_bytes)
        self.frame_lock = threading.Lock()
        self.picam2 = None
        self.session = 1  # Used for naming images

    def start(self):
        transform = Transform(rotation=180)
        self.picam2 = Picamera2()
        config = self.picam2.create_preview_configuration(transform=transform)
        self.picam2.configure(config)
        self.picam2.start()

    def capture_loop(self):
        try:
            while True:
                frame = self.picam2.capture_array()
                frame_bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
                ret, jpeg = cv2.imencode('.jpg', frame_bgr)
                if ret:
                    with self.frame_lock:
                        self.latest_frame = (frame_bgr, jpeg.tobytes())
                time.sleep(0.05)  # ~20 FPS
        except Exception as e:
            print("Exception in capture_loop:", e)
        finally:
            self.picam2.stop()
