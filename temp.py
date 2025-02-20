import RPi.GPIO as GPIO
import time
import os
import threading
from picamera2 import Picamera2, Preview
from libcamera import Transform

AUDIO_FILE = "audio.wav"
VIDEO_FILE = "video.h264"
OUTPUT_FILE = "output.mp4"

# GPIO Setup
time.sleep(3)  # Wait for system to stabilize

IND_LED_PIN = 25
VDO_BTN_PIN = 17
VDO_LED_PIN = 23

GPIO.setmode(GPIO.BCM)
GPIO.setup(VDO_BTN_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
GPIO.setup(VDO_LED_PIN, GPIO.OUT)
GPIO.setup(IND_LED_PIN, GPIO.OUT)

# Picamera Setup
picam2 = Picamera2()
picam2.start_preview(Preview.NULL, transform=Transform(vflip=True))

recording = False
stop_thread = False  # Used to control the splitting thread


def check_shutdown():
    """Monitors if the button is held for 5 seconds to exit the script."""
    while True:
        button_state = GPIO.input(VDO_BTN_PIN)
        if button_state == GPIO.LOW:  # Button pressed
            start_time = time.time()
            while GPIO.input(VDO_BTN_PIN) == GPIO.LOW:
                if time.time() - start_time >= 5:  # Held for 5 seconds
                    print("Button held for 5 seconds! Exiting program...")
                    GPIO.output(IND_LED_PIN, GPIO.LOW)
                    GPIO.output(VDO_LED_PIN, GPIO.LOW)
                    GPIO.cleanup()
                    os._exit(0)  # Exit program immediately

                time.sleep(0.1)
        time.sleep(0.1)


# Start button monitoring thread
shutdown_thread = threading.Thread(target=check_shutdown, daemon=True)
shutdown_thread.start()


try:
    GPIO.output(IND_LED_PIN, GPIO.HIGH)
    time.sleep(1)
    GPIO.output(IND_LED_PIN, GPIO.LOW)

    print("Press the button to start recording...")
    while True:
        button_state = GPIO.input(VDO_BTN_PIN)
        if button_state == GPIO.LOW:
            time.sleep(0.2)  # Debounce delay

            if not recording:
                GPIO.output(VDO_LED_PIN, GPIO.HIGH)
                print("Recording started...")
                recording = True
            else:
                print("Stopping recording...")
                recording = False
                GPIO.output(VDO_LED_PIN, GPIO.LOW)

            while GPIO.input(VDO_BTN_PIN) == GPIO.LOW:
                time.sleep(0.1)

except KeyboardInterrupt:
    GPIO.cleanup()
    picam2.close()
