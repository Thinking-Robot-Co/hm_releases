document.addEventListener('DOMContentLoaded', function() {
    const recordBtn = document.getElementById('recordBtn');
    const captureImageBtn = document.getElementById('captureImageBtn');
    const recordAudioOnlyBtn = document.getElementById('recordAudioOnlyBtn');
    const statusBar = document.getElementById('statusBar');
    const audioCheckbox = document.getElementById('audioCheckbox');
    const videoTypeSelect = document.getElementById('videoType');

    let videoRecording = false;
    let audioOnlyRecording = false;

    function updateStatus(message) {
        statusBar.textContent = "Status: " + message;
    }

    // Video recording button
    recordBtn.addEventListener('click', function() {
        const recordAudio = audioCheckbox.checked;
        const videoType = videoTypeSelect.value;
        if (!videoRecording) {
            fetch('/start_recording', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    record_audio: recordAudio,
                    type: videoType
                })
            })
            .then(response => response.json())
            .then(data => {
                updateStatus(data.status);
                recordBtn.textContent = 'Stop Video Recording';
                videoRecording = true;
            })
            .catch(error => {
                console.error('Error starting video recording:', error);
                updateStatus('Error starting video recording');
            });
        } else {
            fetch('/stop_recording', { method: 'POST' })
            .then(response => response.json())
            .then(data => {
                updateStatus(data.status);
                recordBtn.textContent = 'Start Video Recording';
                videoRecording = false;
            })
            .catch(error => {
                console.error('Error stopping video recording:', error);
                updateStatus('Error stopping video recording');
            });
        }
    });

    // Image capture button
    captureImageBtn.addEventListener('click', function() {
        const imageType = videoTypeSelect.value;
        fetch('/capture_image', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ type: imageType })
        })
        .then(response => response.json())
        .then(data => {
            updateStatus(data.status);
        })
        .catch(error => {
            console.error('Error capturing image:', error);
            updateStatus('Error capturing image');
        });
    });

    // Audio-only recording button
    recordAudioOnlyBtn.addEventListener('click', function() {
        const audioType = videoTypeSelect.value;
        if (!audioOnlyRecording) {
            fetch('/start_audio_only', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ type: audioType })
            })
            .then(response => response.json())
            .then(data => {
                updateStatus(data.status);
                recordAudioOnlyBtn.textContent = 'Stop Audio-Only Recording';
                audioOnlyRecording = true;
            })
            .catch(error => {
                console.error('Error starting audio-only recording:', error);
                updateStatus('Error starting audio-only recording');
            });
        } else {
            fetch('/stop_audio_only', { method: 'POST' })
            .then(response => response.json())
            .then(data => {
                updateStatus(data.status);
                recordAudioOnlyBtn.textContent = 'Start Audio-Only Recording';
                audioOnlyRecording = false;
            })
            .catch(error => {
                console.error('Error stopping audio-only recording:', error);
                updateStatus('Error stopping audio-only recording');
            });
        }
    });
});
