# SVJ here #
# General script for - Audio + video with failed to upload - with repeat upload#
# need to add 1.move to master folder   2.delet properly
import RPi.GPIO as GPIO
import time
import requests
import os
import shutil
import threading
import datetime
import subprocess

from picamera2 import Picamera2, Preview
from libcamera import Transform

import pyaudio
import wave

AUDIOS_DIR = "Audios"
os.makedirs(AUDIOS_DIR, exist_ok=True)

CHUNK = 1024
FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 44100

def get_audio_filename(session_no, seg_num):
    """Generate a unique audio filename using current timestamp."""
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    filename = f"audio_{DEVICE_ID}_{session_no}_{seg_num}_{timestamp}.wav"
    return os.path.join(AUDIOS_DIR, filename)

def record_audio(audio_filename, stop_event):
    """Record audio continuously until stop_event is set."""
    p = pyaudio.PyAudio()
    stream = p.open(format=FORMAT, channels=CHANNELS, rate=RATE, input=True, frames_per_buffer=CHUNK)
    frames = []
    while not stop_event.is_set():
        try:
            data = stream.read(CHUNK, exception_on_overflow=False)
        except Exception as e:
            print("Audio read error:", e)
            continue
        frames.append(data)
    stream.stop_stream()
    stream.close()
    p.terminate()
    
    wf = wave.open(audio_filename, 'wb')
    wf.setnchannels(CHANNELS)
    wf.setsampwidth(p.get_sample_size(FORMAT))
    wf.setframerate(RATE)
    wf.writeframes(b''.join(frames))
    wf.close()

def merge_audio_video(video_file, audio_file, output_file):
    """
    Use ffmpeg to merge video and audio.
    The command copies the video stream and encodes audio to AAC.
    """
    cmd = [
        "ffmpeg",
        "-y",  # Overwrite output if exists
        "-i", video_file,
        "-i", audio_file,
        "-c:v", "copy",
        "-c:a", "aac",
        output_file
    ]
    try:
        subprocess.run(cmd, check=True)
        print(f"Merged into {output_file}")
        return True
    except subprocess.CalledProcessError as e:
        print("ffmpeg merge error:", e)
        return False
# === END AUDIO SETUP ===

# GPIO Setup

VDO_BTN_PIN = 17      # Button to start/stop recording
VDO_LED_PIN = 23      # LED indicating recording state
STOP_BTN_PIN = 27     # Emergency stop button
IND_LED_PIN = 25      # Indicator LED

GPIO.setmode(GPIO.BCM)
GPIO.setup(VDO_BTN_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
GPIO.setup(VDO_LED_PIN, GPIO.OUT)

# Picamera Setup
picam2 = Picamera2()
picam2.start_preview(Preview.QTGL, transform=Transform(vflip=True))

# API Upload Info
UPLOAD_URL = "https://centrix.co.in/v_api/upload"
HEADERS = {"X-API-KEY": "DDjgMfxLqhxbNmaBoTkfBJkhMxNxkPwMgGjPUwCOaJRCBrvtUX"}
DEVICE_ID = "raspberry_pi_01"  # Change if needed

# Directories for videos and failed uploads
VIDEOS_DIR = "Videos"
FAILED_DIR = "failed_uploads"
os.makedirs(VIDEOS_DIR, exist_ok=True)
os.makedirs(FAILED_DIR, exist_ok=True)

# Global Variables
recording = False
segments = []  # List to store each segment's info: video, audio, start_time, end_time
session_no = 1
seg_num = 1  # Segment counter

# Global audio thread control
audio_thread = None
audio_stop_event = None
stop_thread = False  # For controlling the file size check thread

def format_timestamp():
    """Returns a timestamp string in '12feb25_120344' format."""
    return datetime.datetime.now().strftime("%d%b%y_%H%M%S").lower()

def get_video_filename(session_no, seg_num):
    """Generate a unique video filename using current timestamp."""
    current_timestamp = format_timestamp()
    filename = f"vdo_{DEVICE_ID}_{session_no}_{seg_num}_{current_timestamp}.mp4"
    return os.path.join(VIDEOS_DIR, filename)

def split_segment():
    """
    Called when the current video segment reaches 10MB.
    Stops current video and audio recordings, marks end time, and starts a new segment.
    """
    global seg_num, audio_thread, audio_stop_event
    # Stop current video recording
    picam2.stop_recording()
    # Stop current audio recording
    if audio_thread and audio_thread.is_alive():
        audio_stop_event.set()
        audio_thread.join()
    # Mark end time for the current segment
    segments[-1]["end_time"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"Segment {seg_num} ended at {segments[-1]['end_time']}")
    
    # Increment segment counter and create new filenames
    seg_num += 1
    new_video_file = get_video_filename(session_no, seg_num)
    new_audio_file = get_audio_filename(session_no, seg_num)
    new_segment = {
        "video": new_video_file,
        "audio": new_audio_file,
        "start_time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "end_time": None
    }
    segments.append(new_segment)
    
    # Restart recording for new segment
    picam2.start_and_record_video(new_video_file, duration=None)
    audio_stop_event = threading.Event()
    audio_thread = threading.Thread(target=record_audio, args=(new_audio_file, audio_stop_event))
    audio_thread.start()
    print(f"Started new segment {seg_num}: video={new_video_file}, audio={new_audio_file}, start_time={new_segment['start_time']}")

def check_video_size():
    """
    Continuously checks if the current video segment has reached 10MB.
    If so, calls split_segment() to end current segment and start a new one.
    """
    global recording, stop_thread
    while recording and not stop_thread:
        current_video = segments[-1]["video"]
        if os.path.exists(current_video) and os.path.getsize(current_video) >= 10 * 1024 * 1024:  # 10MB limit
            print(f"Video file {current_video} reached 10MB, splitting segment...")
            split_segment()
        time.sleep(1)

def upload_file(file_path, start_time, end_time):
    """
    Uploads the merged video file to the server.
    Includes start_time and end_time in the payload so that the backend
    correctly registers the recording time.
    """
    try:
        with open(file_path, "rb") as f:
            files = {"video": f}
            data = {
                "device_id": DEVICE_ID,
                "start_time": start_time,
                "end_time": end_time
            }
            print(f"Uploading: {file_path} with start_time={start_time} and end_time={end_time}")
            response = requests.post(UPLOAD_URL, headers=HEADERS, files=files, data=data)
        if response.status_code == 200:
            result = response.json()
            if result.get("success"):
                print(f"Upload successful! Video URL: {result.get('video_link')}")
                os.remove(file_path)  # Delete file after successful upload
                print(f"Deleted: {file_path}")
                return True
            else:
                print("Upload failed:", result)
        else:
            print(f"Error {response.status_code}: {response.text}")
    except Exception as e:
        print(f"Upload Error: {e}")
    return False

def retry_failed_uploads():
    """Attempts to re-upload any videos that previously failed to upload."""
    failed_files = [f for f in os.listdir(FAILED_DIR) if f.endswith(".mp4")]
    if failed_files:
        print(f"Found {len(failed_files)} failed uploads. Retrying...")
        for failed in failed_files:
            failed_path = os.path.join(FAILED_DIR, failed)
            print(f"Retrying upload for {failed_path}")
            # For retry, start and end times might not be available; adjust if needed.
            if upload_file(failed_path, "", ""):
                if os.path.exists(failed_path):
                    os.remove(failed_path)
                    print(f"Successfully uploaded & deleted: {failed_path}")
            else:
                print(f"Still failed, keeping in folder: {failed_path}")
    else:
        print("No failed videos to retry.")

try:
    GPIO.output(IND_LED_PIN, GPIO.HIGH)

    print("Press the button to start recording...")
    while True:
        button_state = GPIO.input(VDO_BTN_PIN)
        if button_state == GPIO.LOW:
            time.sleep(0.2)  # Debounce delay
            if not recording:
                # Start a new recording session
                session_no = 1
                seg_num = 1
                start_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                video_file = get_video_filename(session_no, seg_num)
                audio_file = get_audio_filename(session_no, seg_num)
                GPIO.output(VDO_LED_PIN, GPIO.HIGH)
                segments = []
                segment = {
                    "video": video_file,
                    "audio": audio_file,
                    "start_time": start_time,
                    "end_time": None
                }
                segments.append(segment)
                picam2.start_and_record_video(video_file, duration=None)
                audio_stop_event = threading.Event()
                audio_thread = threading.Thread(target=record_audio, args=(audio_file, audio_stop_event))
                audio_thread.start()
                recording = True
                stop_thread = False
                size_thread = threading.Thread(target=check_video_size)
                size_thread.start()
                print(f"Recording started: video={video_file}, audio={audio_file}, start_time={start_time}")
            else:
                # Stop the recording session
                print("Stopping recording...")
                recording = False
                stop_thread = True
                picam2.stop_recording()
                if audio_thread and audio_thread.is_alive():
                    audio_stop_event.set()
                    audio_thread.join()
                # Mark end time for the final segment
                segments[-1]["end_time"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                print(f"Final segment ended at {segments[-1]['end_time']}")
                picam2.stop_preview()
                GPIO.output(VDO_LED_PIN, GPIO.LOW)
                time.sleep(1)
                
                # Retry any failed uploads first
                retry_failed_uploads()
                
                # Merge each segment's video and audio, then upload the merged file with proper timestamps
                for seg in segments:
                    merged_filename = seg["video"].replace(".mp4", "_merged.mp4")
                    print(f"Merging {seg['video']} and {seg['audio']} into {merged_filename} ...")
                    if merge_audio_video(seg["video"], seg["audio"], merged_filename):
                        if not upload_file(merged_filename, seg["start_time"], seg["end_time"]):
                            failed_path = os.path.join(FAILED_DIR, os.path.basename(merged_filename))
                            shutil.move(merged_filename, failed_path)
                            print(f"Moved to failed uploads: {failed_path}")
                    else:
                        print("Merge failed for segment:", seg)
                segments.clear()
            
            # Wait until the button is released
            while GPIO.input(VDO_BTN_PIN) == GPIO.LOW:
                time.sleep(0.1)

except KeyboardInterrupt:
    GPIO.output(VDO_LED_PIN, GPIO.LOW)
    GPIO.output(IND_LED_PIN, GPIO.LOW)

    print("Exiting...")
    GPIO.cleanup()
    picam2.close()
