document.addEventListener('DOMContentLoaded', () => {
    // --- VAPI VOICE INTEGRATION ---
    const urlParams = new URLSearchParams(window.location.search);
    const VAPI_PUBLIC_KEY = urlParams.get('vapi_key') || window.VAPI_PUBLIC_KEY || '';
    const VAPI_ASSISTANT_ID = urlParams.get('assistant_id') || window.VAPI_ASSISTANT_ID || '0de15885-971e-4610-8336-a99f08104d2a';

    let vapiInstance = null;
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

    // Initialize Vapi SDK
    function initVapi() {
        if (vapiInstance) return vapiInstance;

        if (window.vapiSDK && typeof window.vapiSDK.run === 'function') {
            try {
                // vapiSDK.run creates and manages the underlying Vapi call instance
                vapiInstance = window.vapiSDK.run({
                    apiKey: VAPI_PUBLIC_KEY,
                    assistant: VAPI_ASSISTANT_ID,
                    config: {
                        position: "bottom-right"
                    }
                });

                if (vapiInstance) {
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

                    const activeBubbles = { user: null, bot: null };

                    vapiInstance.on('message', (message) => {
                        if (message.type === 'transcript') {
                            const role = message.role === 'user' ? 'user' : 'bot';
                            const text = (message.transcript || '').trim();
                            const isFinal = message.transcriptType === 'final';

                            if (!text) return;

                            if (!transcriptFeed) return;
                            const placeholder = transcriptFeed.querySelector('.transcript-placeholder');
                            if (placeholder) placeholder.remove();

                            // If we have an active partial bubble for this role, update its text
                            if (activeBubbles[role]) {
                                activeBubbles[role].textContent = text;
                            } else {
                                const msgDiv = document.createElement('div');
                                msgDiv.className = `transcript-item ${role}`;
                                msgDiv.textContent = text;
                                transcriptFeed.appendChild(msgDiv);
                                activeBubbles[role] = msgDiv;
                            }

                            // On final, release the active bubble so next utterance starts fresh
                            if (isFinal) {
                                activeBubbles[role] = null;
                            }

                            transcriptFeed.scrollTop = transcriptFeed.scrollHeight;
                        }
                    });

                    vapiInstance.on('error', (e) => {
                        console.error('Vapi Call Error:', e);
                        updateStatus('READY TO CONNECT', 'idle');
                    });
                }
            } catch (err) {
                console.error("vapiSDK.run error:", err);
            }
        }
        return vapiInstance;
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
        if (!window.vapiSDK && !window.Vapi && !window.vapi) {
            alert('Loading Vapi Voice SDK... please try again in 2 seconds.');
            return;
        }

        updateStatus('CONNECTING...', 'connecting');
        
        try {
            const instance = initVapi();
            if (instance && typeof instance.start === 'function') {
                await instance.start(VAPI_ASSISTANT_ID);
            } else {
                const vapiBtn = document.querySelector('.vapi-btn') || document.querySelector('[id*="vapi"]');
                if (vapiBtn) {
                    vapiBtn.click();
                } else {
                    updateStatus('READY TO CONNECT', 'idle');
                }
            }
        } catch (err) {
            console.error('Failed to start call:', err);
            updateStatus('READY TO CONNECT', 'idle');
        }
    }

    function disconnectAgent() {
        if (vapiInstance && isConnected) {
            vapiInstance.stop();
        }
        const vapiBtn = document.querySelector('.vapi-btn');
        if (vapiBtn && isConnected) {
            vapiBtn.click();
        }
        isConnected = false;
        updateStatus('DISCONNECTED', 'offline');
        stopTimer();
        setOrbState('idle');
    }

    function toggleMute() {
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
