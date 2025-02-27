#!/usr/bin/env python3
import os
import datetime

# Ensure required directories exist.
IMAGES_DIR = "Images"
os.makedirs(IMAGES_DIR, exist_ok=True)

VIDEOS_DIR = "Videos"
os.makedirs(VIDEOS_DIR, exist_ok=True)

AUDIOS_DIR = "Audios"
os.makedirs(AUDIOS_DIR, exist_ok=True)

def format_timestamp():
    return datetime.datetime.now().strftime("%d%b%y_%H%M%S").lower()

def get_image_filename(device_id="helmet", prefix="img"):
    ts = format_timestamp()
    filename = os.path.join(IMAGES_DIR, f"{prefix}_{device_id}_{ts}.jpg")
    return filename

def get_video_filename(device_id="helmet", session_no=1, seg_num=1, prefix="vdo"):
    ts = datetime.datetime.now().strftime("%d%b%y_%H%M%S").lower()
    filename = os.path.join(VIDEOS_DIR, f"{prefix}_{device_id}_{session_no}_{seg_num}_{ts}.mp4")
    return filename
