#!/usr/bin/env python3
import threading
import os
import datetime
import time
import utils

class AudioRecorder:
    def __init__(self, device_id="helmet", channels=1, rate=44100, chunk=1024, format=None):
        import pyaudio
        if format is None:
            format = pyaudio.paInt16
        self.device_id = device_id
        self.channels = channels
        self.rate = rate
        self.chunk = chunk
        self.format = format
        self.audio_file = None
        self._stop_event = threading.Event()
        self._thread = None

    def _record(self, filename):
        import pyaudio
        import wave
        p = pyaudio.PyAudio()
        stream = p.open(format=self.format, channels=self.channels, rate=self.rate,
                        input=True, frames_per_buffer=self.chunk)
        frames = []
        while not self._stop_event.is_set():
            try:
                data = stream.read(self.chunk, exception_on_overflow=False)
                frames.append(data)
            except Exception as e:
                print("Audio read error:", e)
                continue
        stream.stop_stream()
        stream.close()
        p.terminate()

        wf = wave.open(filename, 'wb')
        wf.setnchannels(self.channels)
        wf.setsampwidth(p.get_sample_size(self.format))
        wf.setframerate(self.rate)
        wf.writeframes(b''.join(frames))
        wf.close()
        print(f"Audio recording saved as {filename}")

    def start_recording(self):
        self._stop_event.clear()
        ts = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        self.audio_file = os.path.join(utils.AUDIOS_DIR, f"audio_{self.device_id}_{ts}.wav")
        self._thread = threading.Thread(target=self._record, args=(self.audio_file,))
        self._thread.start()
        print("Audio recording started.")

    def stop_recording(self):
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join()
            print("Audio recording stopped.")
            return self.audio_file
        return None

class VideoRecorder:
    def __init__(self, camera_controller, device_id="helmet", segment_threshold=10 * 1024 * 1024):
        """
        camera_controller: Instance of CameraController (from camera.py)
        segment_threshold: Maximum file size (in bytes) before splitting (default 10MB)
        """
        self.camera_controller = camera_controller  # expects camera_controller.picam2 available
        self.device_id = device_id
        self.segment_threshold = segment_threshold
        self.session_no = 1
        self.seg_num = 1
        self.segments = []
        self.recording = False
        self._stop_check_thread = False
        self._check_thread = None

    def start_recording(self):
        if self.recording:
            return
        self.session_no = 1  # Can be incremented for each new recording session
        self.seg_num = 1
        self.segments = []
        start_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        video_file = utils.get_video_filename(device_id=self.device_id, session_no=self.session_no, seg_num=self.seg_num)
        self.current_video_file = video_file
        try:
            self.camera_controller.picam2.start_and_record_video(video_file, duration=None)
        except Exception as e:
            print("Error starting video recording:", e)
            return
        self.recording = True
        self._stop_check_thread = False
        self._check_thread = threading.Thread(target=self._check_video_size)
        self._check_thread.start()
        self.segments.append({
            "video": video_file,
            "start_time": start_time,
            "end_time": None
        })
        print(f"Video recording started, segment {self.seg_num} -> {video_file}")

    def _check_video_size(self):
        while self.recording and not self._stop_check_thread:
            if os.path.exists(self.current_video_file):
                try:
                    size = os.path.getsize(self.current_video_file)
                    if size >= self.segment_threshold:
                        print(f"Segment {self.seg_num} reached threshold: {size} bytes, splitting segment.")
                        self.split_segment()
                except Exception as e:
                    print("Error checking video file size:", e)
            time.sleep(1)

    def split_segment(self):
        try:
            self.camera_controller.picam2.stop_recording()
        except Exception as e:
            print("Error stopping recording for segment split:", e)
        self.segments[-1]["end_time"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"Segment {self.seg_num} ended.")
        self.seg_num += 1
        new_video_file = utils.get_video_filename(device_id=self.device_id, session_no=self.session_no, seg_num=self.seg_num)
        self.current_video_file = new_video_file
        new_segment = {
            "video": new_video_file,
            "start_time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "end_time": None
        }
        self.segments.append(new_segment)
        try:
            self.camera_controller.picam2.start_and_record_video(new_video_file, duration=None)
            print(f"Started new segment {self.seg_num} -> {new_video_file}")
        except Exception as e:
            print("Error starting new segment:", e)

    def stop_recording(self):
        if not self.recording:
            return
        self.recording = False
        self._stop_check_thread = True
        try:
            self.camera_controller.picam2.stop_recording()
        except Exception as e:
            print("Error stopping recording:", e)
        if self._check_thread is not None:
            self._check_thread.join()
        if self.segments:
            self.segments[-1]["end_time"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print("Video recording stopped.")
        return self.segments
