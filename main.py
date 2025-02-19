### SVJ HERE HELLO - Hello, Doing 8th version now   ###

import RPi.GPIO as GPIO
import time
import requests
import os
import shutil
import threading
from picamera2 import Picamera2, Preview
from libcamera import Transform
import datetime

# GPIO Setup
BTN_PIN = 17
LED_PIN = 27

GPIO.setmode(GPIO.BCM)
GPIO.setup(BTN_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
GPIO.setup(LED_PIN, GPIO.OUT)

# Picamera Setup
picam2 = Picamera2()
picam2.start_preview(Preview.QTGL, transform=Transform(vflip=True))

# API Upload Info
UPLOAD_URL = "https://centrix.co.in/v_api/upload"
HEADERS = {"X-API-KEY": "DDjgMfxLqhxbNmaBoTkfBJkhMxNxkPwMgGjPUwCOaJRCBrvtUX"}
DEVICE_ID = "raspberry_pi_01"  # Change if needed

# Directories
VIDEOS_DIR = "Videos"
FAILED_DIR = "failed_uploads"

# Ensure folders exist
os.makedirs(VIDEOS_DIR, exist_ok=True)
os.makedirs(FAILED_DIR, exist_ok=True)

# Variables
recording = False
video_files = []
num = 1
prev_timestamp = None
stop_thread = False  # Used to control the splitting thread


def get_timestamp():
    """Get current timestamp formatted for filenames."""
    return datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

def format_timestamp():
    """Returns timestamp in '12feb25_120344' format."""
    return datetime.datetime.now().strftime("%d%b%y_%H%M%S").lower()

def get_video_filename(session_no, vdo_num):
    """Generate video filename with proper formatting."""
    global prev_timestamp
    current_timestamp = format_timestamp()

    if prev_timestamp:
        filename = f"vdo_{DEVICE_ID}_{session_no}_{vdo_num}_{prev_timestamp}_{current_timestamp}.mp4"
    else:
        filename = f"vdo_{DEVICE_ID}_{session_no}_{vdo_num}_{current_timestamp}.mp4"

    prev_timestamp = current_timestamp  # Update previous timestamp
    return os.path.join(VIDEOS_DIR, filename)


def upload_video(file_path):
    """Uploads video and returns True if successful, otherwise False."""
    try:
        with open(file_path, "rb") as video_file:
            files = {"video": video_file}
            data = {"device_id": DEVICE_ID}

            print(f"Uploading: {file_path} ...")
            response = requests.post(UPLOAD_URL, headers=HEADERS, files=files, data=data)

        if response.status_code == 200:
            result = response.json()
            if result.get("success"):
                print(f"Upload successful! Video URL: {result.get('video_link')}")
                os.remove(file_path)  # Delete video after successful upload
                print(f"Deleted: {file_path}")
                return True
            else:
                print("Upload failed:", result)
        else:
            print(f"Error {response.status_code}: {response.text}")

    except Exception as e:
        print("Upload Error:", str(e))

    return False

def retry_failed_uploads():
    """Attempts to upload all failed videos before uploading new ones."""
    failed_videos = [f for f in os.listdir(FAILED_DIR) if f.endswith(".mp4")]
    
    if failed_videos:
        print(f"Found {len(failed_videos)} failed uploads. Retrying...")

        for failed_vdo in failed_videos:
            failed_path = os.path.join(FAILED_DIR, failed_vdo)
            print(f"Retrying upload for {failed_path}")

            if upload_video(failed_path):
                if os.path.exists(failed_path):  # ✅ Check before deleting
                    os.remove(failed_path)
                    print(f"Successfully uploaded & deleted: {failed_path}")
            else:
                print(f"Still failed, keeping in folder: {failed_path}")
    else:
        print("✅No failed videos to retry.")



def upload_video(file_path):
    """Uploads video and returns True if successful, otherwise False."""
    try:
        with open(file_path, "rb") as video_file:
            files = {"video": video_file}
            data = {"device_id": DEVICE_ID}

            print(f"Uploading: {file_path} ...")
            response = requests.post(UPLOAD_URL, headers=HEADERS, files=files, data=data)

        if response.status_code == 200:
            result = response.json()
            if result.get("success"):
                print(f"Upload successful! Video URL: {result.get('video_link')}")
                os.remove(file_path)  # Delete video after successful upload
                print(f"Deleted: {file_path}")
                return True
            else:
                print("Upload failed:", result)
        else:
            print(f"Error {response.status_code}: {response.text}")

    except Exception as e:
        print(f"Upload Error: {e}")

    return False



def check_video_size():
    """Runs in a separate thread to check if the video has reached 10MB."""
    global recording, num, stop_thread
    while recording and not stop_thread:
        if os.path.exists(video_files[-1]) and os.path.getsize(video_files[-1]) >= 10 * 1024 * 1024:  # 10MB
            print(f"Video file {video_files[-1]} reached 10MB, stopping recording...")
            picam2.stop_recording()
            time.sleep(0.5)  # Small delay before restarting

            num += 1  # Increment video number
            new_video_file = get_video_filename()
            print(f"Starting new recording: {new_video_file}")
            video_files.append(new_video_file)
            picam2.start_and_record_video(new_video_file, duration=None)

        time.sleep(1)  # Check every second


try:
    print("Press the button to start recording...")
    while True:
        button_state = GPIO.input(BTN_PIN)
        if button_state == GPIO.LOW:
            time.sleep(0.2)  # Debounce delay

            if not recording:
                session_no = 1  # You can increment this per session if needed
                video_file = get_video_filename(session_no, num)  # Pass session & vdo number
                GPIO.output(LED_PIN, GPIO.HIGH)
                video_files.append(video_file)
                picam2.start_and_record_video(video_file, duration=None)
                recording = True
                num = 1  # Reset video numbering for a new session
                stop_thread = False  # Allow the thread to run

                # Start a new thread for file size checking
                split_thread = threading.Thread(target=check_video_size)
                split_thread.start()

            else:
                # Stop recording
                print("Stopping recording...")
                recording = False  # This will stop the split thread
                stop_thread = True
                picam2.stop_recording()
                picam2.stop_preview()
                GPIO.output(LED_PIN, GPIO.LOW)
                time.sleep(1)  # Prevent accidental double press

                # 🔄 First, try to upload previously failed videos
                retry_failed_uploads()

                # 📤 Now upload the latest recorded videos
                for vdo in video_files:
                    if not upload_video(vdo):
                        failed_path = os.path.join(FAILED_DIR, os.path.basename(vdo))
                        shutil.move(vdo, failed_path)
                        print(f"Moved to failed uploads: {failed_path}")

                # Clear the list after upload attempt
                video_files.clear()


            # Wait until button is released
            while GPIO.input(BTN_PIN) == GPIO.LOW:
                time.sleep(0.1)

except KeyboardInterrupt:
    print("Exiting...")
    GPIO.cleanup()
    picam2.close()
