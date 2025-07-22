document.addEventListener('DOMContentLoaded', () => {
    // Elementi UI
    const audioFileInput = document.getElementById('audio-file');
    const uploadButton = document.getElementById('upload-button');
    const fileNameDisplay = document.getElementById('file-name-display');
    const uploadSection = document.getElementById('upload-section');
    const loadingSpinner = document.getElementById('loading-spinner');
    const mixerSection = document.getElementById('mixer-section');
    const mixerContainer = document.getElementById('mixer-container');
    const exportButton = document.getElementById('export-button');
    const playPauseButton = document.getElementById('play-pause-button');
    const stopButton = document.getElementById('stop-button');
    const seekBar = document.getElementById('seek-bar');
    const currentTimeDisplay = document.getElementById('current-time');
    const totalDurationDisplay = document.getElementById('total-duration');

    // Stato dell'applicazione
    let trackStates = {};
    let sessionPath = '';
    let soloTrack = null;
    let isPlaying = false;
    let masterAudio = null;
    let animationFrameId = null;

    // Event Listeners
    audioFileInput.addEventListener('change', () => {
        const file = audioFileInput.files[0];
        fileNameDisplay.textContent = file ? file.name : 'Nessun file selezionato';
    });

    uploadButton.addEventListener('click', () => {
        const file = audioFileInput.files[0];
        if (file) handleFileUpload(file);
        else alert('Per favore, scegli un file prima di caricarlo.');
    });

    playPauseButton.addEventListener('click', togglePlayback);
    stopButton.addEventListener('click', stopAllTracks);
    seekBar.addEventListener('input', seekAllTracks);

    function handleFileUpload(file) {
        uploadSection.style.display = 'none';
        loadingSpinner.style.display = 'block';
        mixerSection.style.display = 'none';

        const formData = new FormData();
        formData.append('audio', file);

        fetch('http://localhost:5001/upload', { method: 'POST', body: formData })
            .then(response => response.ok ? response.json() : response.json().then(err => { throw new Error(err.error || 'Errore di rete'); }))
            .then(data => {
                loadingSpinner.style.display = 'none';
                if (data.error) {
                    showError(data.error);
                    return;
                }
                sessionPath = data.path;
                data.tracks.forEach(track => {
                    createMixerTrack(track.name, track.url);
                });
                mixerSection.style.display = 'block';
            })
            .catch(error => {
                console.error("Errore durante il caricamento:", error);
                showError(`Si è verificato un errore grave: ${error.message}`);
            });
    }

    function showError(message) {
        alert(`Errore: ${message}`);
        uploadSection.style.display = 'flex';
        loadingSpinner.style.display = 'none';
    }

    function createMixer(tracks) {
        mixerContainer.innerHTML = '';
        trackStates = {};
        soloTrack = null;
        masterAudio = null;

        const loadPromises = tracks.map(trackInfo => new Promise(resolve => {
            const trackName = trackInfo.name;
            const trackUrl = trackInfo.url; // Use the direct URL from Replicate API

            const trackElement = document.createElement('div');
            trackElement.className = 'track';

            // Qui andrà la forma d'onda
            const waveformContainer = document.createElement('div');
            waveformContainer.id = `waveform-${trackName}`;
            waveformContainer.style.height = '128px'; // Placeholder
            waveformContainer.style.backgroundColor = '#2a2a2a'; // Placeholder

            const audio = new Audio(trackUrl);
            audio.preload = 'auto';
            audio.addEventListener('loadedmetadata', () => resolve(audio));

            trackStates[trackName] = { audio, volume: 1, muted: false };
            if (!masterAudio) masterAudio = audio; // Il primo audio è il master per la durata

            const trackHeader = document.createElement('div');
            trackHeader.className = 'track-header';

            const nameElement = document.createElement('h3');
            nameElement.textContent = trackName;

            const trackControls = document.createElement('div');
            trackControls.className = 'track-controls';

            const volumeSlider = document.createElement('input');
            volumeSlider.type = 'range';
            volumeSlider.min = 0; volumeSlider.max = 1; volumeSlider.step = 0.01; volumeSlider.value = 1;
            volumeSlider.className = 'volume-slider';
            volumeSlider.addEventListener('input', () => {
                trackStates[trackName].volume = parseFloat(volumeSlider.value);
                updateAudioState();
            });

            const muteBtn = createButton('M', 'mute-btn', () => {
                trackStates[trackName].muted = !trackStates[trackName].muted;
                muteBtn.classList.toggle('active', trackStates[trackName].muted);
                updateAudioState();
            });

            const soloBtn = createButton('S', 'solo-btn', () => {
                const isCurrentlySolo = soloBtn.classList.contains('active');
                document.querySelectorAll('.solo-btn.active').forEach(btn => btn.classList.remove('active'));
                if (!isCurrentlySolo) {
                    soloBtn.classList.add('active');
                    soloTrack = trackName;
                } else {
                    soloTrack = null;
                }
                updateAudioState();
            });

            trackHeader.appendChild(nameElement);
            trackControls.appendChild(volumeSlider);
            trackControls.appendChild(muteBtn);
            trackControls.appendChild(soloBtn);
            trackHeader.appendChild(trackControls);
            trackElement.appendChild(trackHeader);
            trackElement.appendChild(waveformContainer);
            mixerContainer.appendChild(trackElement);
        }));

        Promise.all(loadPromises).then(setupGlobalControls);
    }

    function createButton(text, className, onClick) {
        const btn = document.createElement('button');
        btn.textContent = text;
        btn.className = className;
        btn.addEventListener('click', onClick);
        return btn;
    }

    function setupGlobalControls() {
        if (!masterAudio) return;
        totalDurationDisplay.textContent = formatTime(masterAudio.duration);
        seekBar.max = masterAudio.duration;
        masterAudio.addEventListener('ended', stopAllTracks);
    }

    function updateAudioState() {
        Object.keys(trackStates).forEach(name => {
            const state = trackStates[name];
            const isMutedByMute = state.muted;
            const isMutedBySolo = soloTrack && soloTrack !== name;
            state.audio.volume = (isMutedByMute || isMutedBySolo) ? 0 : state.volume;
        });
    }

    function togglePlayback() {
        isPlaying = !isPlaying;
        const action = isPlaying ? 'play' : 'pause';
        Object.values(trackStates).forEach(state => state.audio[action]());
        playPauseButton.textContent = isPlaying ? '⏸️' : '▶️';

        if (isPlaying) startSyncLoop();
        else stopSyncLoop();
    }

    function stopAllTracks() {
        Object.values(trackStates).forEach(state => {
            state.audio.pause();
            state.audio.currentTime = 0;
        });
        isPlaying = false;
        playPauseButton.textContent = '▶️';
        stopSyncLoop();
    }

    function seekAllTracks() {
        const seekTime = parseFloat(seekBar.value);
        Object.values(trackStates).forEach(state => state.audio.currentTime = seekTime);
        currentTimeDisplay.textContent = formatTime(seekTime);
    }

    function startSyncLoop() {
        if (animationFrameId) cancelAnimationFrame(animationFrameId);

        function loop() {
            if (isPlaying && masterAudio) {
                const masterTime = masterAudio.currentTime;
                seekBar.value = masterTime;
                currentTimeDisplay.textContent = formatTime(masterTime);
                
                // Sincronizzazione forzata per mantenere il sync perfetto
                Object.values(trackStates).forEach(state => {
                    if (state.audio !== masterAudio && Math.abs(masterTime - state.audio.currentTime) > 0.05) { // Tolleranza minima
                        state.audio.currentTime = masterTime;
                    }
                });
            }
            animationFrameId = requestAnimationFrame(loop);
        }
        loop();
    }

    function stopSyncLoop() {
        if (animationFrameId) cancelAnimationFrame(animationFrameId);
        animationFrameId = null;
    }

    function formatTime(seconds) {
        const min = Math.floor(seconds / 60);
        const sec = Math.floor(seconds % 60).toString().padStart(2, '0');
        return `${min}:${sec}`;
    }

    exportButton.addEventListener('click', () => {
        exportButton.disabled = true;
        exportButton.textContent = 'Esportazione...';

        const payload = {
            session_path: sessionPath,
            tracks: Object.keys(trackStates).map(name => ({
                name: name,
                volume: trackStates[name].volume,
                mute: trackStates[name].muted
            })),
            solo_track: soloTrack
        };

        fetch('http://localhost:5001/export', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        })
        .then(response => {
            if (!response.ok) {
                return response.json().then(err => { throw new Error(err.error || 'Esportazione fallita') });
            }
            return response.blob();
        })
        .then(blob => {
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.style.display = 'none';
            a.href = url;
            a.download = 'mio_mix.wav';
            document.body.appendChild(a);
            a.click();
            window.URL.revokeObjectURL(url);
            document.body.removeChild(a);
        })
        .catch(error => {
            console.error('Errore esportazione:', error);
            alert(`Errore: ${error.message}`);
        })
        .finally(() => {
            exportButton.disabled = false;
            exportButton.textContent = 'Esporta Mix';
        });
    });
});
