#!/usr/bin/env python3
import os
import requests

DEVICE_ID = "raspberry_pi_01"
UPLOAD_URL = "https://centrix.co.in/v_api/upload"
HEADERS = {"X-API-KEY": "DDjgMfxLqhxbNmaBoTkfBJkhMxNxkPwMgGjPUwCOaJRCBrvtUX"}

def upload_file(file_path, file_type, start_time="", end_time=""):
    try:
        with open(file_path, "rb") as f:
            files = {"video": f}  # Using "video" field for all files.
            data = {
                "device_id": DEVICE_ID,
                "file_type": file_type,
                "start_time": start_time,
                "end_time": end_time
            }
            resp = requests.post(UPLOAD_URL, headers=HEADERS, files=files, data=data)
        if resp.status_code == 200:
            result = resp.json()
            if result.get("success"):
                return True, result
            else:
                return False, result
        else:
            return False, {"error": resp.text}
    except Exception as e:
        return False, {"exception": str(e)}

def upload_image(file_path):
    return upload_file(file_path, "image")

def upload_video(file_path, start_time="", end_time=""):
    return upload_file(file_path, "video", start_time, end_time)

def upload_audio(file_path, start_time="", end_time=""):
    return upload_file(file_path, "audio", start_time, end_time)
