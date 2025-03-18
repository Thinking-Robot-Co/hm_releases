# audio_recorder.py
import time
import os
import threading
import pyaudio
import wave

CHUNK = 1024
FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 44100

class AudioRecorder:
    def __init__(self, output_dir='media'):
        self.recording = False
        self.output_dir = output_dir
        if not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir)
        self.audio_counter = 0
        self.session = 1
        self.audio_frames = []
        self.audio_thread = None
        self.record_audio_flag = False
        self.p = None
        self.audio_stream = None
        self.final_filename = None
        self.lock = threading.Lock()
        self.start_time = None
        self.end_time = None

    def _record_audio_thread(self):
        while self.record_audio_flag:
            try:
                data = self.audio_stream.read(CHUNK)
                self.audio_frames.append(data)
            except Exception as e:
                print("Audio-only recording error:", e)
                break

    def start_recording(self, audio_type="general"):
        with self.lock:
            if not self.recording:
                self.audio_counter += 1
                timestamp = time.strftime("%d%b%y_%H%M%S").lower()
                self.final_filename = os.path.join(
                    self.output_dir,
                    f"audio_{self.session}_{self.audio_counter}__{timestamp}_{audio_type}.wav"
                )
                self.audio_frames = []
                self.p = pyaudio.PyAudio()
                self.audio_stream = self.p.open(format=FORMAT, channels=CHANNELS, rate=RATE,
                                                input=True, frames_per_buffer=CHUNK)
                self.record_audio_flag = True
                self.audio_thread = threading.Thread(target=self._record_audio_thread, daemon=True)
                self.audio_thread.start()
                self.recording = True
                self.start_time = time.strftime("%H:%M:%S")
                print("Audio-only recording started:", self.final_filename)
                return self.final_filename
            return None

    def stop_recording(self):
        with self.lock:
            if self.recording:
                self.record_audio_flag = False
                if self.audio_thread is not None:
                    self.audio_thread.join()
                self.audio_stream.stop_stream()
                self.audio_stream.close()
                self.p.terminate()
                wf = wave.open(self.final_filename, 'wb')
                wf.setnchannels(CHANNELS)
                wf.setsampwidth(self.p.get_sample_size(FORMAT))
                wf.setframerate(RATE)
                wf.writeframes(b''.join(self.audio_frames))
                wf.close()
                self.recording = False
                self.end_time = time.strftime("%H:%M:%S")
                print("Audio-only recording stopped. Saved as:", self.final_filename)
                return self.final_filename, self.start_time, self.end_time
