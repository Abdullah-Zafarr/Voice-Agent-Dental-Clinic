document.addEventListener('DOMContentLoaded', () => {
    const urlParams = new URLSearchParams(window.location.search);
    const VAPI_PUBLIC_KEY = urlParams.get('vapi_key') || window.VAPI_PUBLIC_KEY || '';
    const VAPI_ASSISTANT_ID = urlParams.get('assistant_id') || window.VAPI_ASSISTANT_ID || '0de15885-971e-4610-8336-a99f08104d2a';

    let vapiInstance = null;
    let isConnected = false;
    let isMuted = false;
    let isStarting = false;
    let timerInterval = null;
    let callStartTime = null;
    let connectionStartedAt = null;

    const callTimer = document.getElementById('call-timer');
    const volumeBar = document.getElementById('volume-bar');
    const transcriptFeed = document.getElementById('transcript-feed');
    const orbStatusText = document.getElementById('orb-status-text');
    const agentDisplayName = document.getElementById('agent-display-name');
    const actionBtn = document.getElementById('action-btn');
    const muteBtn = document.getElementById('mute-btn');
    const resetBtn = document.getElementById('reset-btn');

    const activeBubbles = { user: null, bot: null };
    const renderedMessages = new Set();
    const renderedAssistantTurns = new Set();

    if (window.lucide) window.lucide.createIcons();
    if (agentDisplayName) agentDisplayName.textContent = 'Sarah (Apex Dental AI)';

    function normalizeRole(role) {
        return role === 'user' || role === 'customer' ? 'user' : 'bot';
    }

    function updateStatus(text, state) {
        if (orbStatusText) {
            orbStatusText.textContent = text;
            orbStatusText.classList.toggle('animate-pulse', state === 'connecting');
        }
        if (actionBtn) {
            actionBtn.classList.toggle('active', isConnected);
            actionBtn.disabled = state === 'connecting';
        }
    }

    function setOrbState(state) {
        const orb = document.getElementById('orb');
        if (orb) orb.setAttribute('data-state', state);
    }

    function removePlaceholder() {
        const placeholder = transcriptFeed && transcriptFeed.querySelector('.transcript-placeholder');
        if (placeholder) placeholder.remove();
    }

    function scrollTranscriptToBottom() {
        if (transcriptFeed) transcriptFeed.scrollTop = transcriptFeed.scrollHeight;
    }

    function createBubble(role, text) {
        if (!transcriptFeed) return null;
        removePlaceholder();
        const bubble = document.createElement('div');
        bubble.className = `transcript-item ${role}`;
        bubble.dataset.sender = role === 'user' ? 'You' : 'Sarah';
        bubble.textContent = text;
        transcriptFeed.appendChild(bubble);
        scrollTranscriptToBottom();
        return bubble;
    }

    function renderTranscript(role, rawText, isFinal = false, messageId = '') {
        const text = String(rawText || '').trim();
        if (!text) return;

        const normalizedRole = normalizeRole(role);
        const stableKey = messageId || `${normalizedRole}:${text}`;

        if (isFinal && renderedMessages.has(stableKey)) return;

        let bubble = activeBubbles[normalizedRole];
        if (!bubble) {
            bubble = createBubble(normalizedRole, text);
            activeBubbles[normalizedRole] = bubble;
        } else {
            bubble.textContent = text;
        }

        if (isFinal) {
            renderedMessages.add(stableKey);
            activeBubbles[normalizedRole] = null;
        }
        scrollTranscriptToBottom();
    }

    function renderConversationSnapshot(message) {
        const entries = message.conversation || message.messages || [];
        if (!Array.isArray(entries)) return;

        // Vapi sends assistant TTS chunks, transcript events, and snapshots. Only
        // the latest assistant entry in the snapshot is a complete display turn.
        const assistantEntry = [...entries].reverse().find((entry) => (
            entry.role === 'assistant' || entry.role === 'bot'
        ));
        if (!assistantEntry) return;

        const text = String(
            assistantEntry.transcript || assistantEntry.content || assistantEntry.message || ''
        ).trim();
        if (!text) return;

        const turnKey = assistantEntry.id || assistantEntry.messageId || text;
        if (renderedAssistantTurns.has(turnKey)) return;
        renderedAssistantTurns.add(turnKey);
        createBubble('bot', text);
        scrollTranscriptToBottom();
    }

    function startTimer() {
        callStartTime = Date.now();
        stopTimer();
        timerInterval = window.setInterval(() => {
            const elapsed = Math.floor((Date.now() - callStartTime) / 1000);
            const mins = String(Math.floor(elapsed / 60)).padStart(2, '0');
            const secs = String(elapsed % 60).padStart(2, '0');
            if (callTimer) callTimer.textContent = `${mins}:${secs}`;
        }, 1000);
    }

    function stopTimer() {
        if (timerInterval) window.clearInterval(timerInterval);
        timerInterval = null;
        if (callTimer) callTimer.textContent = '00:00';
    }

    function bindVapiEvents(instance) {
        instance.on('call-start', () => {
            isConnected = true;
            isStarting = false;
            const elapsed = connectionStartedAt ? ((Date.now() - connectionStartedAt) / 1000).toFixed(1) : null;
            updateStatus(elapsed ? `LISTENING (${elapsed}S)` : 'LISTENING', 'online');
            startTimer();
            setOrbState('idle');
        });

        instance.on('call-end', () => {
            isConnected = false;
            isStarting = false;
            updateStatus('READY TO CONNECT', 'idle');
            stopTimer();
            setOrbState('idle');
        });

        instance.on('speech-start', () => {
            updateStatus('SARAH IS SPEAKING', 'online');
            setOrbState('speaking');
        });

        instance.on('speech-end', () => {
            if (isConnected) updateStatus('LISTENING', 'online');
            setOrbState('idle');
        });

        instance.on('message', (message) => {
            if (!message) return;
            if (message.type === 'transcript') {
                if (normalizeRole(message.role) !== 'user') return;
                const finalTypes = new Set(['final', 'finalized', 'complete']);
                renderTranscript(message.role, message.transcript, finalTypes.has(message.transcriptType), message.id || message.messageId);
            } else if (message.type === 'conversation-update') {
                renderConversationSnapshot(message);
            } else if (message.type === 'assistant.speechStarted') {
                updateStatus('SARAH IS SPEAKING', 'online');
            } else if (message.type === 'user-interrupted') {
                updateStatus('LISTENING', 'online');
                setOrbState('idle');
            }
        });

        instance.on('error', (error) => {
            console.error('Vapi call error:', error);
            isStarting = false;
            const details = JSON.stringify(error || '').toLowerCase();
            const isAudioError = details.includes('audio') || details.includes('microphone') || details.includes('media');
            updateStatus(isAudioError ? 'MICROPHONE UNAVAILABLE' : 'CONNECTION ERROR', 'error');
            setOrbState('idle');
        });
    }

    function initVapi() {
        if (vapiInstance) return vapiInstance;
        if (!window.vapiSDK || typeof window.vapiSDK.run !== 'function') return null;

        try {
            vapiInstance = window.vapiSDK.run({
                apiKey: VAPI_PUBLIC_KEY,
                assistant: VAPI_ASSISTANT_ID,
                config: { position: 'bottom-right' },
            });
            if (vapiInstance && typeof vapiInstance.on === 'function') bindVapiEvents(vapiInstance);
        } catch (error) {
            console.error('Unable to initialize Vapi:', error);
            updateStatus('VOICE SERVICE UNAVAILABLE', 'error');
        }
        return vapiInstance;
    }

    function warmVapi(attempt = 0) {
        if (initVapi()) return;
        if (attempt < 40) window.setTimeout(() => warmVapi(attempt + 1), 100);
    }

    async function connectToAgent() {
        if (isConnected || isStarting) return;
        isStarting = true;
        connectionStartedAt = Date.now();
        updateStatus('CONNECTING MICROPHONE...', 'connecting');

        const instance = initVapi();
        if (!instance) {
            isStarting = false;
            updateStatus('VOICE SERVICE LOADING', 'connecting');
            warmVapi();
            return;
        }

        try {
            if (typeof instance.start === 'function') {
                await instance.start(VAPI_ASSISTANT_ID);
                return;
            }

            const widgetButton = document.querySelector('.vapi-btn, [data-vapi-button], [id*="vapi"]');
            if (widgetButton instanceof HTMLElement) {
                widgetButton.click();
                return;
            }
            throw new Error('Vapi start control was not found.');
        } catch (error) {
            console.error('Failed to start Vapi call:', error);
            isStarting = false;
            updateStatus('CONNECTION ERROR', 'error');
        }
    }

    function disconnectAgent() {
        if (vapiInstance && typeof vapiInstance.stop === 'function') {
            try {
                vapiInstance.stop();
            } catch (error) {
                console.warn('Vapi stop error:', error);
            }
        }
        isConnected = false;
        isStarting = false;
        updateStatus('READY TO CONNECT', 'idle');
        stopTimer();
        setOrbState('idle');
    }

    function toggleMute() {
        if (!vapiInstance || !isConnected || typeof vapiInstance.setMuted !== 'function') return;
        isMuted = !isMuted;
        vapiInstance.setMuted(isMuted);
        if (muteBtn) muteBtn.classList.toggle('active', isMuted);
    }

    if (actionBtn) actionBtn.addEventListener('click', () => isConnected ? disconnectAgent() : connectToAgent());
    if (muteBtn) muteBtn.addEventListener('click', toggleMute);
    if (resetBtn) resetBtn.addEventListener('click', disconnectAgent);

    warmVapi();
});
