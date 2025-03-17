# video_uploaded.py
import subprocess
import os
import time

def merge_video_audio(video_file, audio_file, video_type, session, video_counter):
    """
    Merges the given video_file and audio_file into a single output file.
    The final file will have the naming pattern:
      vdo_<session>_<video_counter>__<timestamp>_<type>.avi
    """
    # Create a new timestamp for the final filename
    timestamp = time.strftime("%d%b%y_%H%M%S").lower()  # e.g., 17mar25_130702
    output_filename = os.path.join(
        os.path.dirname(video_file),
        f"vdo_{session}_{video_counter}__{timestamp}_{video_type}.avi"
    )
    
    # Build the ffmpeg command.
    # -y : overwrite output file if exists
    # -i video_file : input video file
    # -i audio_file : input audio file
    # -c:v copy : copy the video stream without re-encoding
    # -c:a aac : encode audio to AAC (or use copy if compatible)
    cmd = [
        "ffmpeg", "-y",
        "-i", video_file,
        "-i", audio_file,
        "-c:v", "copy",
        "-c:a", "aac",
        output_filename
    ]
    
    print("Merging video and audio with command:", " ".join(cmd))
    
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        print("Merged file created:", output_filename)
        return output_filename
    except subprocess.CalledProcessError as e:
        print("Error merging audio and video:", e.stderr.decode())
        return None
