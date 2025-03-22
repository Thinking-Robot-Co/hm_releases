document.addEventListener('DOMContentLoaded', function() {
    const recordBtn = document.getElementById('recordBtn');
    const captureImageBtn = document.getElementById('captureImageBtn');
    const recordAudioOnlyBtn = document.getElementById('recordAudioOnlyBtn');
    const statusBar = document.getElementById('statusBar');
    const audioCheckbox = document.getElementById('audioCheckbox');
    const videoTypeSelect = document.getElementById('videoType');
    
    // Advanced control buttons
    const zoomInBtn = document.getElementById('zoomInBtn');
    const zoomOutBtn = document.getElementById('zoomOutBtn');
    const rotate90Btn = document.getElementById('rotate90Btn');
    const rotateNeg90Btn = document.getElementById('rotateNeg90Btn');
    const resetAdvancedBtn = document.getElementById('resetAdvancedBtn');
    
    let videoRecording = false;
    let audioOnlyRecording = false;
    
    // Local copy of advanced parameters (should match server defaults)
    let advancedParams = {
        rotation: 180,
        zoom: 1.0
    };
    
    function updateStatus(message) {
        statusBar.textContent = "Status: " + message;
    }
    
    function sendAdvancedParams() {
        fetch('/set_advanced', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(advancedParams)
        })
        .then(response => response.json())
        .then(data => {
            updateStatus("Advanced settings updated.");
        })
        .catch(error => {
            console.error("Error updating advanced settings:", error);
            updateStatus("Error updating advanced settings.");
        });
    }
    
    // Video recording button
    recordBtn.addEventListener('click', function() {
        const recordAudio = audioCheckbox.checked;
        const videoType = videoTypeSelect.value;
        if (!videoRecording) {
            fetch('/start_recording', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ record_audio: recordAudio, type: videoType })
            })
            .then(response => response.json())
            .then(data => {
                updateStatus(data.status);
                recordBtn.textContent = 'Stop Video Recording';
                recordBtn.classList.add('recording');
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
                recordBtn.classList.remove('recording');
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
            headers: { 'Content-Type': 'application/json' },
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
                headers: { 'Content-Type': 'application/json' },
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
    
    // Advanced controls
    zoomInBtn.addEventListener('click', function() {
        advancedParams.zoom *= 1.1;
        sendAdvancedParams();
    });
    
    zoomOutBtn.addEventListener('click', function() {
        advancedParams.zoom /= 1.1;
        sendAdvancedParams();
    });
    
    rotate90Btn.addEventListener('click', function() {
        advancedParams.rotation = (advancedParams.rotation + 90) % 360;
        sendAdvancedParams();
    });
    
    rotateNeg90Btn.addEventListener('click', function() {
        advancedParams.rotation = (advancedParams.rotation - 90) % 360;
        sendAdvancedParams();
    });
    
    resetAdvancedBtn.addEventListener('click', function() {
        advancedParams = { rotation: 180, zoom: 1.0 };
        sendAdvancedParams();
    });
});
