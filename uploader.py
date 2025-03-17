# uploader.py
import requests
import os
import shutil

API_UPLOAD_URL = "https://centrix.co.in/v_api/upload"
API_KEY = "DDjgMfxLqhxbNmaBoTkfBJkhMxNxkPwMgGjPUwCOaJRCBrvtUX"
DEVICE_ID = "raspberry_pi_01"

def upload_file(file_path, start_time, end_time):
    """
    Uploads the given file to the remote API along with start_time and end_time.
    If the upload is successful, the file is deleted.
    If the upload fails, the file is moved to the failed_to_upload folder.
    """
    if not os.path.exists(file_path):
        print("File does not exist:", file_path)
        return None

    # Determine the form-data field name based on file extension.
    # (The API sample shows the key "video" even for videos.
    # You may adjust this logic if the API requires different keys.)
    ext = os.path.splitext(file_path)[1].lower()
    if ext in [".avi", ".wav", ".jpg", ".jpeg", ".png"]:
        file_field = "video"
    else:
        file_field = "video"

    files = {file_field: open(file_path, "rb")}
    data = {
        "device_id": DEVICE_ID,
        "start_time": start_time,
        "end_time": end_time
    }
    headers = {
        "X-API-KEY": API_KEY
    }

    try:
        response = requests.post(API_UPLOAD_URL, files=files, data=data, headers=headers)
        if response.status_code == 200:
            res_json = response.json()
            if res_json.get("success"):
                os.remove(file_path)
                print("Uploaded and deleted file:", file_path)
                return res_json
            else:
                move_to_failed(file_path)
                print("Upload failed, API response:", response.text)
                return None
        else:
            move_to_failed(file_path)
            print("Upload failed, status code:", response.status_code, response.text)
            return None
    except Exception as e:
        move_to_failed(file_path)
        print("Exception during file upload:", e)
        return None
    finally:
        files[file_field].close()

def move_to_failed(file_path):
    failed_dir = os.path.join(os.path.dirname(file_path), "failed_to_upload")
    if not os.path.exists(failed_dir):
        os.makedirs(failed_dir)
    base_name = os.path.basename(file_path)
    dest = os.path.join(failed_dir, base_name)
    shutil.move(file_path, dest)
    print("Moved file to failed_to_upload:", dest)
