# video_recorder.py
import cv2
import time
import os
import threading
import subprocess
import pyaudio
import wave

CHUNK = 1024
FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 44100

class VideoRecorder:
    def __init__(self, frame_size, fps=20.0, codec='MJPG', output_dir='media'):
        self.recording = False
        self.video_writer = None
        self.frame_size = frame_size
        self.fps = fps
        self.codec = cv2.VideoWriter_fourcc(*codec)
        self.output_dir = output_dir
        if not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir)
        self.video_counter = 0
        self.session = 1
        self.lock = threading.Lock()
        # Audio-related attributes
        self.record_audio_flag = False
        self.audio_frames = []
        self.audio_thread = None
        self.audio_stream = None
        self.p = None
        self.temp_video_filename = None
        self.temp_audio_filename = None
        self.final_filename = None

    def _record_audio_thread(self):
        while self.record_audio_flag:
            try:
                data = self.audio_stream.read(CHUNK)
                self.audio_frames.append(data)
            except Exception as e:
                print("Audio recording error:", e)
                break

    def start_recording(self, video_type="general", record_audio=False):
        with self.lock:
            if not self.recording:
                self.video_counter += 1
                timestamp = time.strftime("%d%b%y_%H%M%S").lower()
                # Final output filename using your naming scheme
                self.final_filename = os.path.join(
                    self.output_dir,
                    f"vdo_{self.session}_{self.video_counter}__{timestamp}_{video_type}.avi"
                )
                # Temporary filenames for video and (if needed) audio
                self.temp_video_filename = os.path.join(
                    self.output_dir,
                    f"temp_video_{self.session}_{self.video_counter}.avi"
                )
                if record_audio:
                    self.temp_audio_filename = os.path.join(
                        self.output_dir,
                        f"temp_audio_{self.session}_{self.video_counter}.wav"
                    )
                else:
                    self.temp_audio_filename = None

                # Initialize VideoWriter to record video into the temporary file
                self.video_writer = cv2.VideoWriter(self.temp_video_filename, self.codec, self.fps, self.frame_size)
                self.recording = True

                # If audio is requested, start audio recording via PyAudio
                if record_audio:
                    self.record_audio_flag = True
                    self.audio_frames = []
                    self.p = pyaudio.PyAudio()
                    self.audio_stream = self.p.open(format=FORMAT, channels=CHANNELS, rate=RATE, input=True, frames_per_buffer=CHUNK)
                    self.audio_thread = threading.Thread(target=self._record_audio_thread, daemon=True)
                    self.audio_thread.start()
                    print("Audio recording started")
                print("Started recording:", self.final_filename)
                return self.final_filename
            return None

    def stop_recording(self):
        with self.lock:
            if self.recording:
                # Stop video recording
                self.video_writer.release()
                self.video_writer = None
                self.recording = False

                # If audio was recorded, stop the audio thread and write audio to file
                if self.record_audio_flag:
                    self.record_audio_flag = False
                    if self.audio_thread is not None:
                        self.audio_thread.join()
                    self.audio_stream.stop_stream()
                    self.audio_stream.close()
                    self.p.terminate()
                    # Write recorded audio frames to temporary WAV file
                    wf = wave.open(self.temp_audio_filename, 'wb')
                    wf.setnchannels(CHANNELS)
                    wf.setsampwidth(self.p.get_sample_size(FORMAT))
                    wf.setframerate(RATE)
                    wf.writeframes(b''.join(self.audio_frames))
                    wf.close()
                    # Merge video and audio using FFmpeg
                    merge_cmd = [
                        'ffmpeg', '-y', 
                        '-i', self.temp_video_filename, 
                        '-i', self.temp_audio_filename, 
                        '-c:v', 'copy', 
                        '-c:a', 'aac', 
                        self.final_filename
                    ]
                    subprocess.call(merge_cmd)
                    # Remove temporary files
                    os.remove(self.temp_video_filename)
                    os.remove(self.temp_audio_filename)
                    print("Merged video and audio into:", self.final_filename)
                else:
                    # If no audio, simply rename the temporary video file to the final filename
                    os.rename(self.temp_video_filename, self.final_filename)
                    print("Video saved as:", self.final_filename)

    def write_frame(self, frame_bgr):
        with self.lock:
            if self.recording and self.video_writer is not None:
                self.video_writer.write(frame_bgr)
