"""
Cloud Upload Module for Smart Helmet v3
Renames uploaded files instead of deleting them
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

def extract_gps_and_time_from_csv(csv_path):
    """
    Extract start/end GPS coordinates and timestamps from CSV
    Returns: (start_location, end_location, start_time, end_time)
    """
    try:
        if not os.path.exists(csv_path):
            return None, None, None, None

        with open(csv_path, 'r') as f:
            reader = csv_module.reader(f)
            rows = list(reader)

        # Skip header row
        if len(rows) < 2:
            return None, None, None, None

        # Get first data row (start)
        first_row = rows[1]
        # CSV Format: Timestamp, Lat, Lon, Acc, Speed
        # Timestamp is usually column 0
        start_ts = first_row[0]
        start_lat = first_row[1]
        start_lon = first_row[2]
        start_location = f"{start_lat},{start_lon}"
        
        # Try to parse timestamp (format: 2025-12-28 11:22:33.123456)
        try:
             # Remove microseconds for upload format if needed, or keep as is
             start_time = start_ts.split('.')[0] 
        except:
             start_time = start_ts

        # Get last data row (end)
        last_row = rows[-1]
        end_ts = last_row[0]
        end_lat = last_row[1]
        end_lon = last_row[2]
        end_location = f"{end_lat},{end_lon}"
        
        try:
             end_time = end_ts.split('.')[0]
        except:
             end_time = end_ts

        logging.info(f"[UPLOAD] 📍 Start: {start_location} ({start_time})")
        logging.info(f"[UPLOAD] 📍 End: {end_location} ({end_time})")

        return start_location, end_location, start_time, end_time

    except Exception as e:
        logging.error(f"[UPLOAD] GPS/Time extraction failed: {e}")
        return None, None, None, None

def upload_to_cloud(video_path, csv_path, device_id):
    """
    Upload video and GPS data to cloud with detailed debug logging
    Renames files after successful upload instead of deleting
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

        # Default timestamps from filename
        start_time, end_time = extract_timestamps_from_filename(filename)
        
        # Extract GPS locations and accurate times from CSV
        start_location = None
        end_location = None
        csv_exists = csv_path and os.path.exists(csv_path)

        if csv_exists:
            csv_size_kb = round(os.path.getsize(csv_path) / 1024, 2)
            logging.info(f"[UPLOAD] 📊 CSV File: {os.path.basename(csv_path)}")
            logging.info(f"[UPLOAD] 📦 CSV Size: {csv_size_kb} KB")

            gps_start_loc, gps_end_loc, gps_start_time, gps_end_time = extract_gps_and_time_from_csv(csv_path)
            
            if gps_start_loc: start_location = gps_start_loc
            if gps_end_loc: end_location = gps_end_loc
            if gps_start_time: start_time = gps_start_time
            if gps_end_time: end_time = gps_end_time
        else:
            logging.warning(f"[UPLOAD] ⚠️ No CSV file found: {csv_path}")

        logging.info(f"[UPLOAD] ⏰ Final Start Time: {start_time}")
        logging.info(f"[UPLOAD] ⏰ Final End Time: {end_time}")

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

        # Upload video file AND CSV file
        files = {}
        # Open files safely
        opened_files = []
        try:
            vf = open(video_path, 'rb')
            opened_files.append(vf)
            files['video'] = (filename, vf, 'video/mp4')
            
            if csv_exists:
                cf = open(csv_path, 'rb')
                opened_files.append(cf)
                files['gps_csv'] = (os.path.basename(csv_path), cf, 'text/csv')
                logging.info(f"[UPLOAD] 📎 Attaching CSV: {os.path.basename(csv_path)}")

            resp = requests.post(UPLOAD_URL, headers=headers, files=files, data=data, timeout=120)
            
        finally:
            for f in opened_files:
                f.close()

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

                    # Rename files instead of deleting
                    try:
                        # Rename video
                        new_video_name = filename.replace('video_', 'uploaded_')
                        new_video_path = os.path.join(os.path.dirname(video_path), new_video_name)
                        os.rename(video_path, new_video_path)
                        logging.info(f"[UPLOAD] ✓ Renamed video: {new_video_name}")

                        # Rename CSV
                        if csv_exists:
                            csv_filename = os.path.basename(csv_path)
                            new_csv_name = csv_filename.replace('gps_', 'uploaded_gps_')
                            new_csv_path = os.path.join(os.path.dirname(csv_path), new_csv_name)
                            os.rename(csv_path, new_csv_path)
                            logging.info(f"[UPLOAD] ✓ Renamed CSV: {new_csv_name}")
                    except Exception as rename_err:
                        logging.warning(f"[UPLOAD] ⚠️ Could not rename files: {rename_err}")

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
