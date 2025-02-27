#!/usr/bin/env python3
import RPi.GPIO as GPIO
import time
import threading

class GPIOHandler:
    def __init__(self, video_callback=None, audio_callback=None, image_callback=None):
        self.video_callback = video_callback
        self.audio_callback = audio_callback
        self.image_callback = image_callback

        # Define pin numbers.
        self.VIDEO_BTN_PIN = 17   # Toggles video recording
        self.AUDIO_BTN_PIN = 22   # Toggles audio recording
        self.IMAGE_BTN_PIN = 27   # Captures an image
        self.VDO_LED_PIN = 23     # LED for video status
        self.IND_LED_PIN = 25     # Indicator LED

        # Set up GPIO.
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(self.VIDEO_BTN_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        GPIO.setup(self.AUDIO_BTN_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        GPIO.setup(self.IMAGE_BTN_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        GPIO.setup(self.VDO_LED_PIN, GPIO.OUT)
        GPIO.setup(self.IND_LED_PIN, GPIO.OUT)
        GPIO.output(self.IND_LED_PIN, GPIO.HIGH)

        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._poll_buttons)

        # Flags to debounce button presses.
        self._video_pressed = False
        self._audio_pressed = False
        self._image_pressed = False

    def start(self):
        self._stop_event.clear()
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        self._thread.join()
        GPIO.cleanup()

    def _poll_buttons(self):
        while not self._stop_event.is_set():
            # Check video button.
            if GPIO.input(self.VIDEO_BTN_PIN) == GPIO.LOW:
                if not self._video_pressed:
                    self._video_pressed = True
                    if self.video_callback is not None:
                        self.video_callback()
            else:
                self._video_pressed = False

            # Check audio button.
            if GPIO.input(self.AUDIO_BTN_PIN) == GPIO.LOW:
                if not self._audio_pressed:
                    self._audio_pressed = True
                    if self.audio_callback is not None:
                        self.audio_callback()
            else:
                self._audio_pressed = False

            # Check image capture button.
            if GPIO.input(self.IMAGE_BTN_PIN) == GPIO.LOW:
                if not self._image_pressed:
                    self._image_pressed = True
                    if self.image_callback is not None:
                        self.image_callback()
            else:
                self._image_pressed = False

            time.sleep(0.1)
