document.addEventListener('DOMContentLoaded', () => {
    // --- VAPI VOICE INTEGRATION ---
    // Reads Vapi Public Key & Assistant ID from URL params or default
    const urlParams = new URLSearchParams(window.location.search);
    const VAPI_PUBLIC_KEY = urlParams.get('vapi_key') || window.VAPI_PUBLIC_KEY || '3517999b-48d3-492c-aac7-28605970f044';
    const VAPI_ASSISTANT_ID = urlParams.get('assistant_id') || window.VAPI_ASSISTANT_ID || '0de15885-971e-4610-8336-a99f08104d2a';

    let vapi = null;
    let isConnected = false;
    let isMuted = false;
    let timerInterval = null;
    let callStartTime = null;

    // --- DOM ELEMENTS ---
    const callTimer = document.getElementById('call-timer');
    const volumeBar = document.getElementById('volume-bar');
    const transcriptFeed = document.getElementById('transcript-feed');
    const orbStatusText = document.getElementById('orb-status-text');
    const agentDisplayName = document.getElementById('agent-display-name');

    const actionBtn = document.getElementById('action-btn');
    const muteBtn = document.getElementById('mute-btn');
    const resetBtn = document.getElementById('reset-btn');

    if (window.lucide) {
        window.lucide.createIcons();
    }

    if (agentDisplayName) agentDisplayName.textContent = "Sarah (Apex Dental AI)";

    // Inject Vapi Web SDK script dynamically
    const script = document.createElement('script');
    script.src = "https://cdn.jsdelivr.net/gh/VapiAI/html-script-tag@latest/dist/assets/index.js";
    script.defer = true;
    script.onload = () => {
        initVapi();
    };
    document.head.appendChild(script);

    function initVapi() {
        if (!window.vapiSDK) return;
        vapi = window.vapiSDK.run({
            apiKey: VAPI_PUBLIC_KEY,
        });

        // Vapi Event Listeners
        vapi.on('call-start', () => {
            isConnected = true;
            updateStatus('CONNECTED', 'online');
            startTimer();
            setOrbState('speaking');
        });

        vapi.on('call-end', () => {
            isConnected = false;
            updateStatus('DISCONNECTED', 'offline');
            stopTimer();
            setOrbState('idle');
        });

        vapi.on('speech-start', () => {
            setOrbState('speaking');
        });

        vapi.on('speech-end', () => {
            setOrbState('idle');
        });

        vapi.on('message', (message) => {
            if (message.type === 'transcript') {
                appendTranscript(message.role === 'user' ? 'user' : 'bot', message.transcript);
            }
        });

        vapi.on('error', (e) => {
            console.error('Vapi Error:', e);
            updateStatus('ERROR CONNECTING', 'error');
        });
    }

    // --- BUTTON EVENT LISTENERS ---
    if (actionBtn) {
        actionBtn.addEventListener('click', () => {
            if (!isConnected) {
                connectToAgent();
            } else {
                disconnectAgent();
            }
        });
    }

    if (muteBtn) muteBtn.addEventListener('click', toggleMute);
    if (resetBtn) resetBtn.addEventListener('click', disconnectAgent);

    // --- CORE FUNCTIONS ---
    async function connectToAgent() {
        if (!vapi) {
            alert('Vapi SDK loading... please wait a second and try again.');
            return;
        }

        updateStatus('CONNECTING...', 'connecting');
        try {
            await vapi.start(VAPI_ASSISTANT_ID);
        } catch (err) {
            console.error('Failed to start call:', err);
            updateStatus('READY TO CONNECT', 'idle');
        }
    }

    function disconnectAgent() {
        if (vapi && isConnected) {
            vapi.stop();
        }
        isConnected = false;
        updateStatus('DISCONNECTED', 'offline');
        stopTimer();
        setOrbState('idle');
    }

    function toggleMute() {
        if (!vapi || !isConnected) return;
        isMuted = !isMuted;
        vapi.setMuted(isMuted);
        if (muteBtn) {
            muteBtn.classList.toggle('active', isMuted);
        }
    }

    function updateStatus(text, state) {
        if (orbStatusText) orbStatusText.textContent = text;
        if (actionBtn) {
            actionBtn.classList.toggle('active', isConnected);
        }
    }

    function setOrbState(state) {
        const orb = document.getElementById('orb');
        if (orb) orb.setAttribute('data-state', state);
    }

    function startTimer() {
        callStartTime = Date.now();
        timerInterval = setInterval(() => {
            const elapsed = Math.floor((Date.now() - callStartTime) / 1000);
            const mins = String(Math.floor(elapsed / 60)).padStart(2, '0');
            const secs = String(elapsed % 60).padStart(2, '0');
            if (callTimer) callTimer.textContent = `${mins}:${secs}`;
        }, 1000);
    }

    function stopTimer() {
        if (timerInterval) clearInterval(timerInterval);
        if (callTimer) callTimer.textContent = '00:00';
    }

    function appendTranscript(role, text) {
        if (!transcriptFeed) return;
        const placeholder = transcriptFeed.querySelector('.transcript-placeholder');
        if (placeholder) placeholder.remove();

        const msgDiv = document.createElement('div');
        msgDiv.className = `transcript-item ${role}`;
        msgDiv.textContent = text;
        transcriptFeed.appendChild(msgDiv);
        transcriptFeed.scrollTop = transcriptFeed.scrollHeight;
    }
});
