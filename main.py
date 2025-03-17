# main.py
import threading
import time
from image_capturer import ImageCapturer
from video_recorder import VideoRecorder
from audio_recorder import AudioRecorder
import server

def main():
    # Initialize camera capture
    capturer = ImageCapturer()
    capturer.start()
    capture_thread = threading.Thread(target=capturer.capture_loop, daemon=True)
    capture_thread.start()

    # Wait briefly to get a frame for determining frame size
    time.sleep(1)
    with capturer.frame_lock:
        if capturer.latest_frame is not None:
            frame_bgr, _ = capturer.latest_frame
            frame_size = (frame_bgr.shape[1], frame_bgr.shape[0])
        else:
            frame_size = (640, 480)

    recorder = VideoRecorder(frame_size)
    audio_only_recorder = AudioRecorder()

    # Set globals for the Flask server
    server.image_capturer = capturer
    server.video_recorder = recorder
    server.audio_only_recorder = audio_only_recorder

    # Start the Flask app
    server.app.run(host='0.0.0.0', port=5000, debug=True, use_reloader=False)

if __name__ == '__main__':
    main()
