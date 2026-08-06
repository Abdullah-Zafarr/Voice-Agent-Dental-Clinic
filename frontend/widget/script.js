document.addEventListener('DOMContentLoaded', () => {
    // --- VAPI VOICE INTEGRATION ---
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

    // Lazy load Vapi SDK instance
    function getVapiInstance() {
        if (vapi) return vapi;
        try {
            const VapiSDK = window.vapiSDK || window.Vapi || (window.vapi && window.vapi.default) || window.vapi;
            if (VapiSDK && typeof VapiSDK.run === 'function') {
                vapi = VapiSDK.run({ apiKey: VAPI_PUBLIC_KEY });
            } else if (typeof VapiSDK === 'function') {
                vapi = new VapiSDK(VAPI_PUBLIC_KEY);
            }
        } catch (e) {
            console.error("Vapi init error:", e);
        }
        return vapi;
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
        const vapiInstance = getVapiInstance();
        if (!vapiInstance) {
            alert('Initializing Vapi Voice SDK... please try again in 2 seconds.');
            return;
        }

        updateStatus('CONNECTING...', 'connecting');
        try {
            // Attach event listeners safely once
            vapiInstance.on('call-start', () => {
                isConnected = true;
                updateStatus('CONNECTED', 'online');
                startTimer();
                setOrbState('speaking');
            });

            vapiInstance.on('call-end', () => {
                isConnected = false;
                updateStatus('DISCONNECTED', 'offline');
                stopTimer();
                setOrbState('idle');
            });

            vapiInstance.on('speech-start', () => setOrbState('speaking'));
            vapiInstance.on('speech-end', () => setOrbState('idle'));

            vapiInstance.on('message', (message) => {
                if (message.type === 'transcript') {
                    appendTranscript(message.role === 'user' ? 'user' : 'bot', message.transcript);
                }
            });

            vapiInstance.on('error', (e) => {
                console.error('Vapi Error:', e);
                updateStatus('READY TO CONNECT', 'idle');
            });

            await vapiInstance.start(VAPI_ASSISTANT_ID);
        } catch (err) {
            console.error('Failed to start call:', err);
            updateStatus('READY TO CONNECT', 'idle');
        }
    }

    function disconnectAgent() {
        const vapiInstance = getVapiInstance();
        if (vapiInstance && isConnected) {
            vapiInstance.stop();
        }
        isConnected = false;
        updateStatus('DISCONNECTED', 'offline');
        stopTimer();
        setOrbState('idle');
    }

    function toggleMute() {
        const vapiInstance = getVapiInstance();
        if (!vapiInstance || !isConnected) return;
        isMuted = !isMuted;
        vapiInstance.setMuted(isMuted);
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
