"""
Cloud Upload Module for Smart Helmet v2
Handles video and GPS CSV uploads to Centrix API
Extracts start/end location from CSV and sends as separate fields
"""
import os
import logging
import requests
import datetime
import json
import csv as csv_module

UPLOAD_URL = "https://centrix.co.in/v_api/upload"
API_KEY = "DDjgMfxLqhxbNmaBoTkfBJkhMxNxkPwMgGjPUwCOaJRCBrvtUX"

def extract_timestamps_from_filename(filename):
    """Extract start/end time from filename like video_20251225_211046.mp4"""
    try:
        name = filename.replace('video_', '').replace('.mp4', '')
        dt = datetime.datetime.strptime(name, '%Y%m%d_%H%M%S')
        start_time = dt.strftime('%Y-%m-%d %H:%M:%S')
        return start_time, start_time
    except Exception as e:
        logging.error(f"[UPLOAD] Timestamp extraction failed: {e}")
        now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        return now, now

def extract_gps_from_csv(csv_path):
    """
    Extract start and end GPS coordinates from CSV
    Returns: (start_location, end_location) as "lat,lon" strings
    """
    try:
        if not os.path.exists(csv_path):
            return None, None

        with open(csv_path, 'r') as f:
            reader = csv_module.reader(f)
            rows = list(reader)

        # Skip header row
        if len(rows) < 2:
            return None, None

        # Get first data row (start location)
        first_row = rows[1]
        start_lat = first_row[1]  # Column 1: Lat
        start_lon = first_row[2]  # Column 2: Lon
        start_location = f"{start_lat},{start_lon}"

        # Get last data row (end location)
        last_row = rows[-1]
        end_lat = last_row[1]
        end_lon = last_row[2]
        end_location = f"{end_lat},{end_lon}"

        logging.info(f"[UPLOAD] 📍 Start Location: {start_location}")
        logging.info(f"[UPLOAD] 📍 End Location: {end_location}")

        return start_location, end_location

    except Exception as e:
        logging.error(f"[UPLOAD] GPS extraction failed: {e}")
        return None, None

def upload_to_cloud(video_path, csv_path, device_id):
    """
    Upload video and GPS data to cloud with detailed debug logging
    Returns: (success: bool, message: str)
    """
    try:
        logging.info("=" * 70)
        logging.info("[UPLOAD] 🚀 STARTING CLOUD UPLOAD")
        logging.info("=" * 70)

        # Check video file
        if not os.path.exists(video_path):
            logging.error(f"[UPLOAD] ✗ Video file not found: {video_path}")
            return False, "Video file not found"

        filename = os.path.basename(video_path)
        video_size_mb = round(os.path.getsize(video_path) / (1024*1024), 2)

        logging.info(f"[UPLOAD] 📹 Video File: {filename}")
        logging.info(f"[UPLOAD] 📦 Video Size: {video_size_mb} MB")
        logging.info(f"[UPLOAD] 📍 Video Path: {video_path}")

        # Extract timestamps
        start_time, end_time = extract_timestamps_from_filename(filename)
        logging.info(f"[UPLOAD] ⏰ Start Time: {start_time}")
        logging.info(f"[UPLOAD] ⏰ End Time: {end_time}")

        # Extract GPS locations from CSV
        start_location = None
        end_location = None
        csv_exists = csv_path and os.path.exists(csv_path)

        if csv_exists:
            csv_size_kb = round(os.path.getsize(csv_path) / 1024, 2)
            logging.info(f"[UPLOAD] 📊 CSV File: {os.path.basename(csv_path)}")
            logging.info(f"[UPLOAD] 📦 CSV Size: {csv_size_kb} KB")

            start_location, end_location = extract_gps_from_csv(csv_path)
        else:
            logging.warning(f"[UPLOAD] ⚠️ No CSV file found: {csv_path}")

        # Device ID
        logging.info(f"[UPLOAD] 🔑 Device ID: {device_id}")

        # Prepare data payload with GPS locations
        data = {
            "device_id": device_id,
            "file_type": "video",
            "start_time": start_time,
            "end_time": end_time
        }

        # Add GPS locations if available
        if start_location:
            data["start_location"] = start_location
        if end_location:
            data["end_location"] = end_location

        logging.info(f"[UPLOAD] 📤 POST Data:")
        for key, value in data.items():
            logging.info(f"[UPLOAD]    - {key}: {value}")

        # Prepare headers
        headers = {"X-API-KEY": API_KEY}
        logging.info(f"[UPLOAD] 🔐 Headers: X-API-KEY: {API_KEY[:20]}...")

        # Upload URL
        logging.info(f"[UPLOAD] 🌐 URL: {UPLOAD_URL}")
        logging.info("[UPLOAD] 📡 Uploading...")

        # Upload video file only (GPS data sent as POST parameters)
        with open(video_path, 'rb') as vf:
            files = {'video': (filename, vf, 'video/mp4')}
            resp = requests.post(UPLOAD_URL, headers=headers, files=files, data=data, timeout=120)

        # Log response
        logging.info("=" * 70)
        logging.info(f"[UPLOAD] 📥 RESPONSE RECEIVED")
        logging.info("=" * 70)
        logging.info(f"[UPLOAD] HTTP Status: {resp.status_code}")
        logging.info(f"[UPLOAD] Response Headers:")
        for key, value in resp.headers.items():
            logging.info(f"[UPLOAD]    {key}: {value}")

        # Try to parse JSON response
        try:
            result = resp.json()
            logging.info(f"[UPLOAD] Response JSON:")
            logging.info(f"[UPLOAD] {json.dumps(result, indent=2)}")

            if resp.status_code == 200:
                if result.get("success"):
                    logging.info("[UPLOAD] ✅ SUCCESS!")

                    # Delete local files after successful upload
                    try:
                        os.remove(video_path)
                        logging.info(f"[UPLOAD] 🗑️ Deleted local video: {filename}")
                        if csv_exists:
                            os.remove(csv_path)
                            logging.info(f"[UPLOAD] 🗑️ Deleted local CSV: {os.path.basename(csv_path)}")
                    except Exception as del_err:
                        logging.warning(f"[UPLOAD] ⚠️ Could not delete local files: {del_err}")

                    return True, "Upload successful"
                else:
                    error_msg = result.get("message", "Unknown error")
                    logging.error(f"[UPLOAD] ✗ Server returned success=false: {error_msg}")
                    return False, error_msg
            else:
                error_msg = result.get("message", f"HTTP {resp.status_code}")
                logging.error(f"[UPLOAD] ✗ HTTP {resp.status_code}: {error_msg}")
                return False, error_msg
        except Exception as json_err:
            logging.error(f"[UPLOAD] ✗ Failed to parse JSON response: {json_err}")
            logging.error(f"[UPLOAD] Raw Response Text: {resp.text[:500]}")
            return False, f"HTTP {resp.status_code}"

    except requests.exceptions.Timeout:
        logging.error("[UPLOAD] ✗ Request timeout (120s)")
        return False, "Timeout"
    except requests.exceptions.ConnectionError as e:
        logging.error(f"[UPLOAD] ✗ Connection error: {e}")
        return False, "Connection error"
    except Exception as e:
        logging.error(f"[UPLOAD] ✗ Exception: {e}")
        import traceback
        logging.error(traceback.format_exc())
        return False, str(e)
    finally:
        logging.info("=" * 70)
