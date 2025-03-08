#!/usr/bin/env python3
import pyaudio
import wave
import threading
import datetime
import os
import time
import subprocess

# Audio settings
CHUNK = 1024
FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 44100

class AudioRecorder:
    def __init__(self):
        os.makedirs("Audios", exist_ok=True)
        self.audio_thread = None
        self.stop_event = None
        self.temp_audio_file = os.path.join("Audios", "temp_audio.wav")
        self.recording_start_time = None
        self.audio_counter = 1
        # For segmented recording:
        self.segment_audio_thread = None
        self.segment_stop_event = None
        self.segment_temp_file = None
        self.segment_start_time = None

    def start_recording(self):
        if self.audio_thread is not None and self.audio_thread.is_alive():
            return
        self.stop_event = threading.Event()
        self.recording_start_time = datetime.datetime.now()
        self.audio_thread = threading.Thread(target=self.record_audio, daemon=True)
        self.audio_thread.start()

    def record_audio(self):
        p = pyaudio.PyAudio()
        stream = p.open(format=FORMAT, channels=CHANNELS, rate=RATE,
                        input=True, frames_per_buffer=CHUNK)
        frames = []
        while not self.stop_event.is_set():
            try:
                data = stream.read(CHUNK, exception_on_overflow=False)
            except Exception as e:
                print("Audio error:", e)
                continue
            frames.append(data)
        stream.stop_stream()
        stream.close()
        p.terminate()
        wf = wave.open(self.temp_audio_file, 'wb')
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(p.get_sample_size(FORMAT))
        wf.setframerate(RATE)
        wf.writeframes(b''.join(frames))
        wf.close()

    def stop_recording(self):
        if self.stop_event:
            self.stop_event.set()
        if self.audio_thread:
            self.audio_thread.join()
        start = self.recording_start_time.strftime("%d%b%Y_%H%M%S").lower()
        end_time = datetime.datetime.now()
        end = end_time.strftime("%d%b%Y_%H%M%S").lower()
        final_filename = os.path.join("Audios", f"audio_{self.audio_counter}_{start}_to_{end}.wav")
        try:
            os.rename(self.temp_audio_file, final_filename)
        except Exception as e:
            print("Error renaming audio file:", e)
            final_filename = self.temp_audio_file
        self.audio_counter += 1
        return final_filename

    # Methods for segmented audio recording:
    def start_segmented_recording(self):
        self.segment_stop_event = threading.Event()
        self.segment_start_time = datetime.datetime.now()
        self.segment_temp_file = os.path.join("Audios", "temp_seg_audio.wav")
        self.segment_audio_thread = threading.Thread(target=self.record_segment_audio, daemon=True)
        self.segment_audio_thread.start()

    def record_segment_audio(self):
        p = pyaudio.PyAudio()
        stream = p.open(format=FORMAT, channels=CHANNELS, rate=RATE,
                        input=True, frames_per_buffer=CHUNK)
        frames = []
        while not self.segment_stop_event.is_set():
            try:
                data = stream.read(CHUNK, exception_on_overflow=False)
            except Exception as e:
                print("Segmented audio error:", e)
                continue
            frames.append(data)
        stream.stop_stream()
        stream.close()
        p.terminate()
        wf = wave.open(self.segment_temp_file, 'wb')
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(p.get_sample_size(FORMAT))
        wf.setframerate(RATE)
        wf.writeframes(b''.join(frames))
        wf.close()

    def stop_segmented_recording(self):
        if self.segment_stop_event:
            self.segment_stop_event.set()
        if self.segment_audio_thread:
            self.segment_audio_thread.join()
        start = self.segment_start_time.strftime("%d%b%Y_%H%M%S").lower()
        end_time = datetime.datetime.now()
        end = end_time.strftime("%d%b%Y_%H%M%S").lower()
        final_filename = os.path.join("Audios", f"audio_seg_{start}_to_{end}.wav")
        try:
            os.rename(self.segment_temp_file, final_filename)
        except Exception as e:
            print("Error renaming segmented audio file:", e)
            final_filename = self.segment_temp_file
        return final_filename

class VideoRecorder:
    def __init__(self, camera, audio_recorder=None):
        """
        camera: an instance of Camera from camera.py.
        audio_recorder: an instance of AudioRecorder for merged recording.
        """
        self.camera = camera
        self.audio_recorder = audio_recorder
        self.recording = False
        self.segment_threshold = 10 * 1024 * 1024  # 10 MB
        self.current_video_file = None
        self.segments = []
        self.monitor_thread = None
        self.stop_monitor = False
        self.with_audio = False
        self.session_counter = 1  # Increases per session.
        self.chunk_num = 1        # For now, always 1 (to be increased later).
        self.video_start_time = None
        self.segmentation_thread = None

    def generate_video_filename(self):
        now = datetime.datetime.now()
        date_str = now.strftime("%d%b%Y").lower()
        time_str = now.strftime("%H%M%S")
        return os.path.join("Videos", f"temp_vdo_{date_str}_{time_str}.mp4")

    def start_recording(self, with_audio=False):
        if self.recording:
            return
        self.recording = True
        self.with_audio = with_audio
        self.segments = []
        os.makedirs("Videos", exist_ok=True)
        if self.with_audio and self.audio_recorder is not None:
            # Start the segmentation loop for merged video+audio.
            self.segmentation_thread = threading.Thread(target=self._record_with_segmentation, daemon=True)
            self.segmentation_thread.start()
        else:
            # Non-audio mode: use the standard segmentation monitoring.
            self.video_start_time = datetime.datetime.now()
            self.current_video_file = self.generate_video_filename()
            # self.camera.apply_video_transform(hflip=True, vflip=False, rotation=90, width=1280, height=720)
            self.camera.picam2.start_and_record_video(self.current_video_file)
            self.segments.append(self.current_video_file)
            self.stop_monitor = False
            self.monitor_thread = threading.Thread(target=self.monitor_video_size, daemon=True)
            self.monitor_thread.start()

    def monitor_video_size(self):
        while self.recording and not self.stop_monitor:
            if os.path.exists(self.current_video_file):
                size = os.path.getsize(self.current_video_file)
                if size >= self.segment_threshold:
                    try:
                        self.camera.picam2.stop_recording()
                    except Exception as e:
                        print("Error stopping recording for segmentation:", e)
                    self.current_video_file = self.generate_video_filename()
                    self.camera.picam2.start_and_record_video(self.current_video_file)
                    self.segments.append(self.current_video_file)
            time.sleep(1)

    def _record_with_segmentation(self):
        while self.recording:
            self.video_start_time = datetime.datetime.now()
            video_file = self.generate_video_filename()
            
            # Start video segment.
            self.camera.picam2.start_and_record_video(video_file)
            
            # Start corresponding audio segment.
            self.audio_recorder.start_segmented_recording()
            
            # Monitor video file size.
            while self.recording:
                if os.path.exists(video_file) and os.path.getsize(video_file) >= self.segment_threshold:
                    break
                time.sleep(1)

            # Stop the current segment
            self.camera.picam2.stop_recording()
            audio_file = self.audio_recorder.stop_segmented_recording()
            
            # Merge video and audio
            merged_file = self.merge_video_audio(video_file, audio_file)
            if merged_file:
                self.segments.append(merged_file)
            else:
                self.segments.append(video_file)
            
            # Increment the chunk number correctly
            self.chunk_num += 1

    def stop_recording(self):
        if not self.recording:
            return self.segments
        self.recording = False
        if self.with_audio and self.segmentation_thread is not None:
            self.segmentation_thread.join()
        else:
            self.stop_monitor = True
            try:
                self.camera.picam2.stop_recording()
            except Exception as e:
                print("Error stopping video recording:", e)
            if self.monitor_thread:
                self.monitor_thread.join()
        # Resume preview so image capture remains available.
        self.camera.picam2.start()
        video_end_time = datetime.datetime.now()
        start_str = self.video_start_time.strftime("%d%b%Y_%H%M%S").lower()
        end_str = video_end_time.strftime("%d%b%Y_%H%M%S").lower()
        final_segments = []
        # Use index-based naming for each segment
        for idx, seg in enumerate(self.segments, start=1):
            prefix = "merged" if self.with_audio else "vdo"
            final_name = os.path.join("Videos", 
                f"{prefix}_{self.session_counter}_{idx}_{start_str}_to_{end_str}.mp4")
            try:
                os.rename(seg, final_name)
            except Exception as e:
                print("Error renaming video file:", e)
                final_name = seg
            final_segments.append(final_name)
        self.session_counter += 1
        self.chunk_num = 1  # Reset chunk number for new session if needed.
        return final_segments


    def merge_video_audio(self, video_file, audio_file):
        video_start_str = self.video_start_time.strftime("%d%b%Y_%H%M%S").lower()
        video_end_str = datetime.datetime.now().strftime("%d%b%Y_%H%M%S").lower()
        merged_file = os.path.join("Videos",
            f"merged_{self.session_counter}_{self.chunk_num}_{video_start_str}_to_{video_end_str}.mp4")
        cmd = [
            "ffmpeg",
            "-y",
            "-i", video_file,
            "-i", audio_file,
            "-c:v", "copy",
            "-c:a", "aac",
            merged_file
        ]
        try:
            subprocess.run(cmd, check=True)
            os.remove(video_file)
            os.remove(audio_file)
            return merged_file
        except subprocess.CalledProcessError as e:
            print("Error during merging:", e)
            return None

