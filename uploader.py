#!/usr/bin/env python3
import os
import requests

# Configuration for the upload endpoint.
UPLOAD_URL = "https://centrix.co.in/v_api/upload"
API_KEY = "DDjgMfxLqhxbNmaBoTkfBJkhMxNxkPwMgGjPUwCOaJRCBrvtUX"
HEADERS = {"X-API-KEY": API_KEY}
DEVICE_ID = "helmet"  # Change if needed.

def upload_file(file_path, file_type, start_time="", end_time=""):
    """
    Uploads a file to the remote server.
    
    Parameters:
      file_path (str): Path to the file to upload.
      file_type (str): Type of the file ("video", "audio", or "image").
      start_time (str): (Optional) Start time metadata.
      end_time (str): (Optional) End time metadata.
      
    The file is always sent in the "video" field.
    
    Returns:
      bool: True if the upload is successful, False otherwise.
    """
    try:
        with open(file_path, "rb") as f:
            files = {"video": f}  # Sending file in "video" field.
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
                print(f"Upload successful for {file_path}")
                return True
            else:
                print(f"Upload failed for {file_path}: {result}")
        else:
            print(f"Upload error {resp.status_code} for {file_path}: {resp.text}")
    except Exception as e:
        print(f"Upload exception for {file_path}: {e}")
    return False

def retry_failed_uploads(failed_dir="failed_uploads"):
    """
    Scans the failed_uploads folder and attempts to re-upload each file.
    If an upload is successful, the file is removed.
    """
    if not os.path.exists(failed_dir):
        print("No failed uploads folder found.")
        return
    for file_name in os.listdir(failed_dir):
        file_path = os.path.join(failed_dir, file_name)
        if os.path.isfile(file_path):
            # Determine file type based on filename prefix.
            if file_name.startswith("vdo_"):
                file_type = "video"
            elif file_name.startswith("audio_"):
                file_type = "audio"
            elif file_name.startswith("img_"):
                file_type = "image"
            else:
                file_type = "unknown"
            # For simplicity, passing empty start_time and end_time.
            success = upload_file(file_path, file_type, "", "")
            if success:
                os.remove(file_path)
                print(f"Re-uploaded and removed {file_path}")
            else:
                print(f"Re-upload failed for {file_path}")
