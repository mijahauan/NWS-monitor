let map;
let markers = {}; // ssrc -> Leaflet Marker
let repeatersData = [];
let wsControl;
let wsAudio;

// DOM Elements
const hostInput = document.getElementById('hostInput');
const locationInput = document.getElementById('locationInput');
const searchBtn = document.getElementById('searchBtn');
const squelchSlider = document.getElementById('squelchSlider');
const squelchValue = document.getElementById('squelchValue');
const radiusSlider = document.getElementById('radiusSlider');
const radiusValue = document.getElementById('radiusValue');
const gainSlider = document.getElementById('gainSlider');
const gainValue = document.getElementById('gainValue');
const wsStatus = document.getElementById('ws-status');
const wsText = document.getElementById('ws-text');
const repeaterList = document.getElementById('repeaterList');
const repeaterCount = document.getElementById('repeaterCount');

const audioPanel = document.getElementById('audio-panel');
const stopAudioBtn = document.getElementById('stopAudioBtn');
const audioRepeaterCallsign = document.getElementById('audio-repeater-callsign');
const audioRepeaterFreq = document.getElementById('audio-repeater-freq');
const resumeAudioBtn = document.getElementById('resumeAudioBtn');

// Custom Icons
const defaultIcon = L.divIcon({
    className: 'custom-icon',
    html: `<div style="width:16px;height:16px;background:#3b82f6;border-radius:50%;border:2px solid #fff;box-shadow:0 0 5px rgba(0,0,0,0.5);"></div>`,
    iconSize: [16, 16]
});

const activeIcon = L.divIcon({
    className: 'custom-icon',
    html: `<div style="width:20px;height:20px;background:#10b981;border-radius:50%;border:2px solid #fff;box-shadow:0 0 15px #10b981;"></div>`,
    iconSize: [20, 20]
});

// Init Map
function initMap() {
    map = L.map('map').setView([38.5, -91.0], 5); // Default US center

    // Use CartoDB Dark Matter tiles for modern look
    L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png', {
        attribution: '&copy; OpenStreetMap &copy; CARTO',
        subdomains: 'abcd',
        maxZoom: 19
    }).addTo(map);
}

function connectWebSocket() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    wsControl = new WebSocket(`${protocol}//${window.location.host}/ws/control`);

    wsControl.onopen = () => {
        wsStatus.className = 'status-dot connected';
        wsText.textContent = `Connected to ${hostInput.value}`;
        // Auto search on load
        triggerSearch();
    };

    wsControl.onclose = () => {
        wsStatus.className = 'status-dot disconnected';
        wsText.textContent = 'Disconnected - Retrying...';
        setTimeout(connectWebSocket, 3000);
    };

    wsControl.onmessage = (event) => {
        const data = JSON.parse(event.data);

        if (data.type === 'results') {
            handleSearchResults(data);
        } else if (data.type === 'activity') {
            handleActivityUpdate(data);
        } else if (data.type === 'error') {
            alert(data.message);
        }
    };
}

function triggerSearch() {
    if (wsControl.readyState !== WebSocket.OPEN) return;

    // Clear Existing
    for (let id in markers) {
        map.removeLayer(markers[id]);
    }
    markers = {};
    repeaterList.innerHTML = '';

    wsControl.send(JSON.stringify({
        type: 'search',
        radiod_host: hostInput.value,
        location: locationInput.value,
        squelch: parseFloat(squelchSlider.value),
        radius: parseFloat(radiusSlider.value),
        gain: parseFloat(gainSlider.value)
    }));
}

function handleSearchResults(data) {
    wsText.textContent = `Connected to ${hostInput.value}`;
    repeatersData = data.repeaters;
    repeaterCount.textContent = repeatersData.length;

    if (data.lat && data.lon) {
        map.setView([data.lat, data.lon], 9);
        L.marker([data.lat, data.lon], {
            icon: L.divIcon({
                className: 'custom-icon',
                html: `<div style="width:12px;height:12px;background:#ef4444;border-radius:50%;border:2px solid #fff;"></div>`
            })
        }).addTo(map).bindPopup('Your Location');
    }

    repeatersData.forEach(rep => {
        const lat = parseFloat(rep.Lat || rep.lat);
        const lon = parseFloat(rep.Long || rep.lng || rep.lon);
        const freqHz = parseFloat(rep.Downlink || rep.freq) * 1e6;

        // Add Marker
        const marker = L.marker([lat, lon], { icon: defaultIcon }).addTo(map);
        marker.bindPopup(`
            <div class="dark-popup">
                <h4>${rep.Callsign || 'NWS'}</h4>
                <p><strong>Channel:</strong> ${rep.Channel || 'Unknown'}</p>
                <p><strong>Freq:</strong> ${rep.Downlink || rep.freq} MHz</p>
                <p>${rep.Note || ''}</p>
                <button onclick="listenToRepeater(${freqHz}, '${rep.Callsign}', '${rep.Downlink}')" style="margin-top:10px; padding: 5px; font-size: 0.8rem;">Listen Live</button>
            </div>
        `);
        markers[freqHz] = marker;

        // Add List Item
        const li = document.createElement('li');
        li.className = 'repeater-item';
        li.id = `rep-${freqHz}`;
        li.innerHTML = `
            <div class="rep-header">
                <span class="rep-call">${rep.Callsign || 'NWS'} (${rep.Channel || 'Unknown'})</span>
                <span class="rep-freq">${rep.Downlink || rep.freq}</span>
            </div>
            <div class="rep-details">
                <span>Dist: ${rep.distance_km.toFixed(1)} km</span>
            </div>
            <div class="signal-meter">
                <div class="signal-fill" id="sig-${freqHz}"></div>
            </div>
        `;
        li.onclick = () => {
            map.setView([lat, lon], 12);
            marker.openPopup();
        };
        repeaterList.appendChild(li);
    });
}

function handleActivityUpdate(data) {
    const freqHz = data.freq;
    const isAct = data.isActive;
    const snr = parseFloat(data.snr);

    const li = document.getElementById(`rep-${freqHz}`);
    const sigFill = document.getElementById(`sig-${freqHz}`);
    const marker = markers[freqHz];

    if (li && sigFill && marker) {
        if (isAct) {
            li.classList.add('active-signal');
            marker.setIcon(activeIcon);
        } else {
            li.classList.remove('active-signal');
            marker.setIcon(defaultIcon);
        }

        // Map SNR to 0-100% (assuming max around 30dB for UI scale)
        const pct = Math.max(0, Math.min(100, (snr / 30) * 100));
        sigFill.style.width = `${pct}%`;
    }
}

let audioCtx = null;
let nextAudioTime = 0;

function initAudio() {
    if (!audioCtx) {
        // Remove forced sampleRate as it can cause issues on Safari/macOS
        audioCtx = new (window.AudioContext || window.webkitAudioContext)();
        console.log('AudioContext initialized at rate:', audioCtx.sampleRate);
    }
    if (audioCtx.state === 'suspended') {
        audioCtx.resume().then(() => {
            console.log('AudioContext resumed successfully');
        });
    }
    nextAudioTime = 0;
    updateAudioStatus();
}

function updateAudioStatus() {
    if (audioCtx && audioCtx.state === 'suspended') {
        resumeAudioBtn.classList.remove('hidden');
    } else {
        resumeAudioBtn.classList.add('hidden');
    }
}

// Poll status for Safari/iMac compatibility
setInterval(updateAudioStatus, 1000);

function listenToRepeater(freqHz, callsign, freq) {
    // Disconnect old audio if any
    if (wsAudio) {
        wsAudio.close();
    }

    initAudio();

    audioRepeaterCallsign.textContent = callsign;
    audioRepeaterFreq.textContent = freq + ' MHz';
    audioPanel.classList.remove('hidden');

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    wsAudio = new WebSocket(`${protocol}//${window.location.host}/ws/audio/${freqHz}`);
    wsAudio.binaryType = 'arraybuffer';

    let frameCount = 0;
    wsAudio.onmessage = (event) => {
        frameCount++;
        if (frameCount % 100 === 0) {
            console.log(`Received 100 audio frames. Buffer state: ${audioCtx.state}`);
        }

        // Data is sent as np.float32 array bytes from backend Opus decoder
        const floats = new Float32Array(event.data);
        if (floats.length === 0) {
            console.log("Empty audio frame");
            return;
        }

        let rms = 0;
        for (let i = 0; i < floats.length; i++) {
            rms += floats[i] * floats[i];
        }
        rms = Math.sqrt(rms / floats.length);
        if (frameCount % 100 === 0) {
            console.log(`Audio RMS: ${rms.toFixed(4)}`);
        }

        // All streams are now aligned to 12000Hz (Opus and S16LE)
        const rate = 12000;
        const buffer = audioCtx.createBuffer(1, floats.length, rate);
        buffer.copyToChannel(floats, 0);

        const source = audioCtx.createBufferSource();
        source.buffer = buffer;
        source.connect(audioCtx.destination);

        // Schedule playback smoothly
        const drift = nextAudioTime - audioCtx.currentTime;
        if (nextAudioTime < audioCtx.currentTime) {
            if (drift < -0.1) {
                console.warn(`Audio drift detected (late): ${drift.toFixed(3)}s. Resetting.`);
            }
            nextAudioTime = audioCtx.currentTime + 0.05; // 50ms buffer
        } else if (drift > 1.0) {
            console.warn(`Audio drift detected (early): ${drift.toFixed(3)}s. Resetting.`);
            nextAudioTime = audioCtx.currentTime + 0.05;
        }

        source.start(nextAudioTime);
        nextAudioTime += buffer.duration;
    };

    // Close popup
    map.closePopup();
}

stopAudioBtn.onclick = () => {
    if (wsAudio) {
        wsAudio.onmessage = null; // Prevent processing queued packets
        wsAudio.close();
        wsAudio = null;
    }
    if (audioCtx) {
        // Suspending context immediately stops all scheduled audio
        audioCtx.suspend();
    }
    audioPanel.classList.add('hidden');
    audioRepeaterCallsign.textContent = 'None';
    // Clear list selection
    document.querySelectorAll('.repeater-item').forEach(el => el.classList.remove('active'));
};
stopAudioBtn.addEventListener('click', () => {
    if (wsAudio) {
        wsAudio.close();
        wsAudio = null;
    }
    audioPanel.classList.add('hidden');
});

resumeAudioBtn.addEventListener('click', () => {
    if (audioCtx) {
        audioCtx.resume().then(() => {
            console.log('Audio manually resumed via button');
            updateAudioStatus();
        });
    }
});

// Event Listeners
searchBtn.addEventListener('click', triggerSearch);
locationInput.addEventListener('keypress', (e) => {
    if (e.key === 'Enter') triggerSearch();
});

squelchSlider.addEventListener('input', (e) => {
    squelchValue.textContent = e.target.value;
});
squelchSlider.addEventListener('change', (e) => {
    if (wsControl.readyState === WebSocket.OPEN) {
        // Resend search to update squelch setting globally
        triggerSearch();
    }
});

radiusSlider.addEventListener('change', (e) => {
    if (wsControl.readyState === WebSocket.OPEN) {
        triggerSearch();
    }
});

gainSlider.addEventListener('input', (e) => {
    gainValue.textContent = e.target.value;
});
gainSlider.addEventListener('change', (e) => {
    if (wsControl.readyState === WebSocket.OPEN) {
        triggerSearch();
    }
});

// App Entry
initMap();
connectWebSocket();
