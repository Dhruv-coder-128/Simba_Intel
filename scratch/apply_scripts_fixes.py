with open('templates/chat/scripts.html', 'r', encoding='utf-8') as f:
    code = f.read()

# 1. Update sendQuery for Voice Mode
old_sendquery_top = '''            const sessionParam = new URLSearchParams(window.location.search).get("session");
            const sessionTypeParam = new URLSearchParams(window.location.search).get("type") || "{{ session_type|default:'assistant' }}";
            const isAgentMode = (sessionTypeParam === 'agent');

            let loaderId = "";
            let labelElement = null;

            if (!isAgentMode) {'''

new_sendquery_top = '''            const sessionParam = new URLSearchParams(window.location.search).get("session");
            const sessionTypeParam = new URLSearchParams(window.location.search).get("type") || "{{ session_type|default:'assistant' }}";
            const isAgentMode = (sessionTypeParam === 'agent');
            const isVoiceMode = (sessionTypeParam === 'voice');

            let loaderId = "";
            let labelElement = null;

            if (!isAgentMode && !isVoiceMode) {'''

assert old_sendquery_top in code, "old_sendquery_top not found!"
code = code.replace(old_sendquery_top, new_sendquery_top)

# Update scheduleStreamRender in sendQuery
old_sched = '''                function scheduleStreamRender() {
                    if (scheduledRenderId !== null || isAgentMode || !contentDiv) return;'''
new_sched = '''                function scheduleStreamRender() {
                    if (scheduledRenderId !== null || isAgentMode || isVoiceMode || !contentDiv) return;'''
assert old_sched in code, "old_sched not found!"
code = code.replace(old_sched, new_sched)

# Update while loop chunk flushing in sendQuery
old_flush1 = '''                                if (flushText) {
                                    if (!isAgentMode) {
                                        fullResponse += flushText;
                                        scheduleStreamRender();
                                    } else {
                                        agentTextOutput += flushText;
                                    }
                                }'''
new_flush1 = '''                                if (flushText) {
                                    if (!isAgentMode && !isVoiceMode) {
                                        fullResponse += flushText;
                                        scheduleStreamRender();
                                    } else if (isAgentMode) {
                                        agentTextOutput += flushText;
                                    } else if (isVoiceMode) {
                                        fullResponse += flushText;
                                        const vRespCard = document.getElementById('voiceResponseCard');
                                        const vRespText = document.getElementById('voiceResponseText');
                                        if (vRespCard && vRespText) {
                                            vRespCard.style.display = 'block';
                                            vRespText.textContent = fullResponse.replace(/<[^>]+>/g, '').trim();
                                        }
                                    }
                                }'''
assert old_flush1 in code, "old_flush1 not found!"
code = code.replace(old_flush1, new_flush1)

old_flush2 = '''                                if (!isAgentMode) {
                                    fullResponse += streamBuffer;
                                    streamBuffer = "";
                                    scheduleStreamRender();
                                } else {
                                    agentTextOutput += streamBuffer;
                                    streamBuffer = "";
                                }'''
new_flush2 = '''                                if (!isAgentMode && !isVoiceMode) {
                                    fullResponse += streamBuffer;
                                    streamBuffer = "";
                                    scheduleStreamRender();
                                } else if (isAgentMode) {
                                    agentTextOutput += streamBuffer;
                                    streamBuffer = "";
                                } else if (isVoiceMode) {
                                    fullResponse += streamBuffer;
                                    streamBuffer = "";
                                    const vRespCard = document.getElementById('voiceResponseCard');
                                    const vRespText = document.getElementById('voiceResponseText');
                                    if (vRespCard && vRespText) {
                                        vRespCard.style.display = 'block';
                                        vRespText.textContent = fullResponse.replace(/<[^>]+>/g, '').trim();
                                    }
                                }'''
assert old_flush2 in code, "old_flush2 not found!"
code = code.replace(old_flush2, new_flush2)

# Update post-stream completion in sendQuery
old_post_stream = '''                if (typeof maybeVoiceSpeakResponse === 'function') {
                    maybeVoiceSpeakResponse(fullResponse, { turnId: currentVoiceTurnId, sessionId: currentVoiceSessionId });
                }'''
new_post_stream = '''                if (isVoiceMode) {
                    if (typeof recordSpokenTurn === 'function') {
                        const cleanSpoken = fullResponse.replace(/<[^>]+>/g, '').trim();
                        recordSpokenTurn(query, cleanSpoken, window.isVoiceActionRequest, window.simbaAgentState && window.simbaAgentState.activeTool);
                    }
                }
                if (typeof maybeVoiceSpeakResponse === 'function') {
                    maybeVoiceSpeakResponse(fullResponse, { turnId: currentVoiceTurnId, sessionId: currentVoiceSessionId });
                }'''
assert old_post_stream in code, "old_post_stream not found!"
code = code.replace(old_post_stream, new_post_stream, 1)

# 2. Update syncDesktopAgentStatus element IDs and hide duplicate command pill
old_sync = '''                const bridgeBanner = document.getElementById('agentBridgeBanner');
                const bridgePill = document.getElementById('bridgeStatusPill');
                const bridgePillText = document.getElementById('bridgeStatusPillText');
                const bridgeTitle = document.getElementById('agentBridgeTitle');
                const bridgeSub = document.getElementById('agentBridgeSub');
                const bridgeActionBtn = document.getElementById('btnBridgeStatusAction');

                if (isOnline) {
                    if (stateEl) stateEl.innerHTML = '<span style="color:#0edb2a;"><i class="fa-solid fa-circle-check"></i> Connected &amp; Online</span>';
                    if (devEl) devEl.textContent = `${dev.hostname || 'Windows PC'} (${dev.platform || 'Windows'})`;
                    if (chip) {
                        chip.className = 'pc-status-chip connected';
                    }
                    if (chipLabel) {
                        chipLabel.innerHTML = '<i class="fa-brands fa-windows"></i> Desktop Online';
                    }
                    if (chipDesc) {
                        chipDesc.textContent = `Active on ${dev.hostname || 'Windows PC'} (${dev.platform || 'Windows'}). Local automation active.`;
                    }
                    if (headerDot) {
                        headerDot.className = 'status-dot dot-online';
                    }
                    if (headerLabel) {
                        headerLabel.innerHTML = 'Desktop: <strong>Online</strong>';
                    }
                    if (chipHeader) {
                        chipHeader.className = 'system-chip desktop-chip connected';
                        chipHeader.title = `Desktop Agent connected (${dev.hostname || 'Windows PC'})`;
                    }

                    // Bridge Banner Online State
                    if (bridgeBanner) bridgeBanner.className = 'agent-bridge-banner online';
                    if (bridgePill) bridgePill.className = 'bridge-status-pill online';
                    if (bridgePillText) bridgePillText.textContent = 'ONLINE';
                    if (bridgeTitle) bridgeTitle.textContent = 'DESKTOP AGENT CONNECTED';
                    if (bridgeSub) bridgeSub.textContent = `Connected to ${dev.hostname || 'Windows PC'} (${dev.platform || 'Windows'}). Full local automation tools active.`;
                    if (bridgeActionBtn) bridgeActionBtn.innerHTML = '<i class="fa-solid fa-circle-check"></i> <span>Manage Bridge</span>';
                } else {
                    if (stateEl) stateEl.innerHTML = '<span style="color:#f87171;"><i class="fa-solid fa-circle-xmark"></i> Offline</span>';
                    if (devEl) devEl.textContent = 'No local Desktop Agent active';
                    if (chip) {
                        chip.className = 'pc-status-chip offline';
                    }
                    if (chipLabel) {
                        chipLabel.innerHTML = '<i class="fa-solid fa-desktop"></i> Desktop Offline';
                    }
                    if (chipDesc) {
                        chipDesc.textContent = 'Local computer control requires the Desktop Agent to be connected. Cloud tasks remain active.';
                    }
                    if (headerDot) {
                        headerDot.className = 'status-dot dot-offline';
                    }
                    if (headerLabel) {
                        headerLabel.innerHTML = 'Desktop: <strong>Offline</strong>';
                    }
                    if (chipHeader) {
                        chipHeader.className = 'system-chip desktop-chip offline';
                        chipHeader.title = 'Desktop Agent offline (click to configure)';
                    }

                    // Bridge Banner Offline State
                    if (bridgeBanner) bridgeBanner.className = 'agent-bridge-banner offline';
                    if (bridgePill) bridgePill.className = 'bridge-status-pill offline';
                    if (bridgePillText) bridgePillText.textContent = 'OFFLINE';
                    if (bridgeTitle) bridgeTitle.textContent = 'DESKTOP AGENT OFFLINE';
                    if (bridgeSub) bridgeSub.textContent = 'Local desktop automation tools (window, mouse, apps, files) require the local agent daemon.';
                    if (bridgeActionBtn) bridgeActionBtn.innerHTML = '<i class="fa-solid fa-terminal"></i> <span>Connect Agent</span>';
                }'''

new_sync = '''                const bridgeBanner = document.getElementById('agentBridgeBanner');
                const bridgeCmdPill = document.getElementById('bridgeCommandPill');
                const bridgeTitle = document.getElementById('bridgeBannerTitle') || document.getElementById('agentBridgeTitle');
                const bridgeSub = document.getElementById('bridgeBannerSub') || document.getElementById('agentBridgeSub');
                const bridgeBeaconDot = document.getElementById('bridgeBeaconDot');
                const bridgeBeaconIcon = document.getElementById('bridgeBeaconIcon');
                const btnPing = document.getElementById('btnPingBridge');
                const pingLabel = document.getElementById('pingBridgeLabel');

                if (isOnline) {
                    if (stateEl) stateEl.innerHTML = '<span style="color:#0edb2a;"><i class="fa-solid fa-circle-check"></i> Connected &amp; Online</span>';
                    if (devEl) devEl.textContent = `${dev.hostname || 'Windows PC'} (${dev.platform || 'Windows'})`;
                    if (chip) {
                        chip.className = 'pc-status-chip connected';
                    }
                    if (chipLabel) {
                        chipLabel.innerHTML = '<i class="fa-brands fa-windows"></i> Desktop Online';
                    }
                    if (chipDesc) {
                        chipDesc.textContent = `Active on ${dev.hostname || 'Windows PC'} (${dev.platform || 'Windows'}). Local automation active.`;
                    }
                    if (headerDot) {
                        headerDot.className = 'status-dot dot-online';
                    }
                    if (headerLabel) {
                        headerLabel.innerHTML = 'Desktop: <strong>Online</strong>';
                    }
                    if (chipHeader) {
                        chipHeader.className = 'system-chip desktop-chip connected';
                        chipHeader.title = `Desktop Agent connected (${dev.hostname || 'Windows PC'})`;
                    }

                    // Bridge Banner Online State - HIDE redundant terminal command when connected!
                    if (bridgeBanner) bridgeBanner.className = 'agent-bridge-banner online';
                    if (bridgeCmdPill) bridgeCmdPill.style.display = 'none';
                    if (bridgeTitle) bridgeTitle.textContent = 'DESKTOP BRIDGE CONNECTED // ' + (dev.hostname || 'WINDOWS PC').toUpperCase();
                    if (bridgeSub) bridgeSub.textContent = `Platform: ${dev.platform || 'Windows'} • TLS WebSocket Active • Local Automation Ready`;
                    if (bridgeBeaconDot) bridgeBeaconDot.className = 'bridge-beacon online';
                    if (bridgeBeaconIcon) bridgeBeaconIcon.className = 'fa-brands fa-windows';
                    if (btnPing) btnPing.className = 'btn-ping-bridge online';
                    if (pingLabel) pingLabel.textContent = 'Bridge Online';
                } else {
                    if (stateEl) stateEl.innerHTML = '<span style="color:#f87171;"><i class="fa-solid fa-circle-xmark"></i> Offline</span>';
                    if (devEl) devEl.textContent = 'No local Desktop Agent active';
                    if (chip) {
                        chip.className = 'pc-status-chip offline';
                    }
                    if (chipLabel) {
                        chipLabel.innerHTML = '<i class="fa-solid fa-desktop"></i> Desktop Offline';
                    }
                    if (chipDesc) {
                        chipDesc.textContent = 'Local computer control requires the Desktop Agent to be connected. Cloud tasks remain active.';
                    }
                    if (headerDot) {
                        headerDot.className = 'status-dot dot-offline';
                    }
                    if (headerLabel) {
                        headerLabel.innerHTML = 'Desktop: <strong>Offline</strong>';
                    }
                    if (chipHeader) {
                        chipHeader.className = 'system-chip desktop-chip offline';
                        chipHeader.title = 'Desktop Agent offline (click to configure)';
                    }

                    // Bridge Banner Offline State - SHOW command ribbon so user can easily copy and connect
                    if (bridgeBanner) bridgeBanner.className = 'agent-bridge-banner';
                    if (bridgeCmdPill) bridgeCmdPill.style.display = 'flex';
                    if (bridgeTitle) bridgeTitle.textContent = 'DESKTOP AGENT DISCONNECTED // LOCAL PC CONTROL STANDING BY';
                    if (bridgeSub) bridgeSub.textContent = 'Run the local bridge command below in terminal to enable mouse, keyboard, app launching, and local file access:';
                    if (bridgeBeaconDot) bridgeBeaconDot.className = 'bridge-beacon';
                    if (bridgeBeaconIcon) bridgeBeaconIcon.className = 'fa-solid fa-tower-broadcast';
                    if (btnPing) btnPing.className = 'btn-ping-bridge';
                    if (pingLabel) pingLabel.textContent = 'Check Bridge';
                }'''

assert old_sync in code, "old_sync not found!"
code = code.replace(old_sync, new_sync)

# 3. Voice Stop regex and barge-in
old_stop_regex = '''        const VOICE_STOP_REGEX = /^(?:stop|stop talking|be quiet|shut up|cancel|mute|pause|quiet|abort|hold on)$/i;
        const VOICE_STOP_PHRASE_REGEX = /\\b(?:stop talking|be quiet|shut up)\\b/i;'''

new_stop_regex = '''        const VOICE_STOP_REGEX = /\\b(?:stop|stop talking|stop audio|be quiet|shut up|cancel|mute|pause|quiet|abort|hold on|enough)\\b/i;
        const VOICE_STOP_PHRASE_REGEX = /\\b(?:stop|stop talking|stop audio|be quiet|shut up|cancel)\\b/i;

        function isVoiceStopCommand(text) {
            if (!text) return false;
            const clean = text.trim().toLowerCase().replace(/[.,!?;:]/g, '');
            return VOICE_STOP_REGEX.test(clean) || VOICE_STOP_PHRASE_REGEX.test(clean);
        }'''

assert old_stop_regex in code, "old_stop_regex not found!"
code = code.replace(old_stop_regex, new_stop_regex)

# In voiceRecognition.onresult:
old_is_stop_line = '''                    const lowerLive = liveText.toLowerCase();
                    const isStop = VOICE_STOP_REGEX.test(lowerLive) || VOICE_STOP_PHRASE_REGEX.test(lowerLive);'''

new_is_stop_line = '''                    const lowerLive = liveText.toLowerCase();
                    const isStop = isVoiceStopCommand(liveText);'''

assert old_is_stop_line in code, "old_is_stop_line not found!"
code = code.replace(old_is_stop_line, new_is_stop_line)

# Update Stop handling during isSimbaSpeaking
old_speaking_stop = '''                    if (isSimbaSpeaking) {
                        if (isStop) {
                            console.log('[Voice] Stop command intercepted during TTS playback:', liveText);
                            simbaStopSpeaking(false);
                            activeVoiceTurnId = 'vturn_' + (++voiceTurnCounter); // Invalidate in-flight responses
                            setVoiceState('LISTENING', 'Listening...', null, { subtext: 'Stopped audio. Listening for your next query...' });
                            return;
                        }'''

new_speaking_stop = '''                    if (isSimbaSpeaking) {
                        if (isStop) {
                            console.log('[Voice] Stop command intercepted during TTS playback:', liveText);
                            simbaStopSpeaking(true);
                            activeVoiceTurnId = 'vturn_' + (++voiceTurnCounter); // Invalidate in-flight responses
                            if (currentAbortController) {
                                try { currentAbortController.abort(); } catch (e) { }
                            }
                            setVoiceState('READY', 'AUDIO STOPPED', null, { subtext: 'Voice stopped on command.' });
                            showSimbaToast('Voice stopped', 'info', 1600);
                            return;
                        }'''

assert old_speaking_stop in code, "old_speaking_stop not found!"
code = code.replace(old_speaking_stop, new_speaking_stop)

# Ensure voice recognition runs during simbaSpeak so barge-in works!
old_speak_start = '''            voiceCurrentUtterance.onstart = function () {
                isSimbaSpeaking = true;
                setVoiceState('SPEAKING');'''

new_speak_start = '''            voiceCurrentUtterance.onstart = function () {
                isSimbaSpeaking = true;
                setVoiceState('SPEAKING');
                ensureVoiceRecognitionRunning();'''

assert old_speak_start in code, "old_speak_start not found!"
code = code.replace(old_speak_start, new_speak_start)

# 4. Global keyboard shortcuts: Ctrl + Windows key
old_key_listener = '''        // Global Shortcut: Ctrl + Windows key -> Activate Voice Agent
        document.addEventListener('keydown', (e) => {
            const isWin = e.key === 'Meta' || e.key === 'OS' || e.code === 'MetaLeft' || e.code === 'MetaRight';
            const isCtrl = e.key === 'Control' || e.code === 'ControlLeft' || e.code === 'ControlRight';
            const hasWin = e.metaKey || isWin;
            const hasCtrl = e.ctrlKey || isCtrl;

            if (hasWin && hasCtrl && (isWin || isCtrl)) {
                e.preventDefault();
                const currentType = new URLSearchParams(window.location.search).get('type');
                if (currentType === 'voice') {
                    if (typeof toggleVoiceListening === 'function') {
                        toggleVoiceListening();
                    }
                } else {
                    window.location.href = '/?type=voice&autolisten=1';
                }
            }
        });'''

new_key_listener = '''        // Global Shortcut: Ctrl + Windows key (or Alt+M or Ctrl+Shift+V) -> Toggle Voice Agent Mic
        window.toggleVoiceListening = function () {
            if (typeof toggleVoiceAgentListening === 'function') {
                toggleVoiceAgentListening();
            }
        };
        window.startVoiceListening = function () {
            if (!isVoiceListening && typeof toggleVoiceAgentListening === 'function') {
                toggleVoiceAgentListening();
            }
        };

        document.addEventListener('keydown', (e) => {
            const isWin = e.key === 'Meta' || e.key === 'OS' || e.code === 'MetaLeft' || e.code === 'MetaRight';
            const isCtrl = e.key === 'Control' || e.code === 'ControlLeft' || e.code === 'ControlRight';
            const hasWin = e.metaKey || isWin;
            const hasCtrl = e.ctrlKey || isCtrl;

            const isCtrlWin = (hasWin && hasCtrl && (isWin || isCtrl));
            const isAltM = (e.altKey && (e.code === 'KeyM' || e.key === 'm' || e.key === 'M'));
            const isCtrlShiftV = (e.ctrlKey && e.shiftKey && (e.code === 'KeyV' || e.key === 'v' || e.key === 'V'));

            if (isCtrlWin || isAltM || isCtrlShiftV) {
                e.preventDefault();
                e.stopPropagation();
                const currentType = new URLSearchParams(window.location.search).get('type') || '{{ session_type|default:"assistant" }}';
                if (currentType === 'voice') {
                    if (typeof toggleVoiceAgentListening === 'function') {
                        toggleVoiceAgentListening();
                    }
                } else {
                    window.location.href = '/?type=voice&autolisten=1';
                }
            }
        });'''

assert old_key_listener in code, "old_key_listener not found!"
code = code.replace(old_key_listener, new_key_listener)

# 5. Voice History persistence in localStorage
idx_rec_start = code.find('window.recordSpokenTurn = function (query, response, isAction, toolName) {')
idx_rec_end = code.find('window.copyVoiceResponseText = function (btnEl) {')
assert idx_rec_start != -1 and idx_rec_end != -1, "recordSpokenTurn bounds not found!"

new_record_block = '''window.recordSpokenTurn = function (query, response, isAction, toolName) {
            const feedList = document.getElementById('voiceFeedList');
            const feedEmpty = document.getElementById('voiceFeedEmpty');
            if (!feedList) return;
            if (feedEmpty) feedEmpty.style.display = 'none';

            const timeStr = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
            const card = document.createElement('div');
            card.className = `voice-feed-card ${isAction ? 'action' : ''}`;

            const actionBadge = isAction
                ? `<span class="feed-tag action"><i class="fa-solid fa-bolt"></i> ${escapeHtml(toolName || 'ACTION')}</span>`
                : `<span class="feed-tag info"><i class="fa-regular fa-comment-dots"></i> QUERY</span>`;

            const cleanRespForReplay = (response || '').replace(/'/g, "\\\\'").replace(/"/g, '&quot;');

            card.innerHTML = `
                <div class="feed-card-header">
                    <div style="display:flex; align-items:center; gap:8px;">
                        ${actionBadge}
                        <span class="feed-time">${timeStr}</span>
                    </div>
                    <div class="feed-card-actions">
                        <button type="button" class="btn-feed-action" onclick="simbaSpeak('${cleanRespForReplay}')" title="Replay voice audio">
                            <i class="fa-solid fa-volume-high"></i>
                        </button>
                        <button type="button" class="btn-feed-action" onclick="copyVoiceResponseText(this)" title="Copy text">
                            <i class="fa-regular fa-copy"></i>
                        </button>
                    </div>
                </div>
                <div class="feed-user-query">
                    <i class="fa-solid fa-microphone"></i>
                    <span>${escapeHtml(query || '')}</span>
                </div>
                <div class="feed-simba-resp">
                    <i class="fa-solid fa-robot"></i>
                    <span class="feed-resp-content">${escapeHtml(response || '')}</span>
                </div>
            `;

            feedList.insertBefore(card, feedList.firstChild);

            // Persist spoken turn to localStorage for persistence across reloads
            try {
                const sid = activeVoiceSessionId || new URLSearchParams(window.location.search).get('session') || 'current';
                const key = 'simba_voice_history_' + sid;
                let list = JSON.parse(localStorage.getItem(key) || '[]');
                list.unshift({ query: query || '', response: response || '', isAction: !!isAction, toolName: toolName || '', time: timeStr });
                if (list.length > 50) list = list.slice(0, 50);
                localStorage.setItem(key, JSON.stringify(list));
            } catch (_) {}

            // Keep maximum 50 turns in DOM
            while (feedList.children.length > 50) {
                feedList.removeChild(feedList.lastChild);
            }
        };

        window.restoreVoiceHistoryFromStorage = function () {
            const feedList = document.getElementById('voiceFeedList');
            if (!feedList) return;
            if (feedList.querySelectorAll('.voice-feed-card').length > 0) return;
            const sid = activeVoiceSessionId || new URLSearchParams(window.location.search).get('session') || 'current';
            const key = 'simba_voice_history_' + sid;
            try {
                const list = JSON.parse(localStorage.getItem(key) || '[]');
                if (list && list.length > 0) {
                    const empty = document.getElementById('voiceFeedEmpty');
                    if (empty) empty.style.display = 'none';
                    list.forEach(turn => {
                        const card = document.createElement('div');
                        card.className = `voice-feed-card ${turn.isAction ? 'action' : ''}`;
                        const actionBadge = turn.isAction
                            ? `<span class="feed-tag action"><i class="fa-solid fa-bolt"></i> ${escapeHtml(turn.toolName || 'ACTION')}</span>`
                            : `<span class="feed-tag info"><i class="fa-regular fa-comment-dots"></i> QUERY</span>`;
                        const cleanResp = (turn.response || '').replace(/'/g, "\\\\'").replace(/"/g, '&quot;');
                        card.innerHTML = `
                            <div class="feed-card-header">
                                <div style="display:flex; align-items:center; gap:8px;">
                                    ${actionBadge}
                                    <span class="feed-time">${turn.time || ''}</span>
                                </div>
                                <div class="feed-card-actions">
                                    <button type="button" class="btn-feed-action" onclick="simbaSpeak('${cleanResp}')" title="Replay voice audio">
                                        <i class="fa-solid fa-volume-high"></i>
                                    </button>
                                    <button type="button" class="btn-feed-action" onclick="copyVoiceResponseText(this)" title="Copy text">
                                        <i class="fa-regular fa-copy"></i>
                                    </button>
                                </div>
                            </div>
                            <div class="feed-user-query">
                                <i class="fa-solid fa-microphone"></i>
                                <span>${escapeHtml(turn.query || '')}</span>
                            </div>
                            <div class="feed-simba-resp">
                                <i class="fa-solid fa-robot"></i>
                                <span class="feed-resp-content">${escapeHtml(turn.response || '')}</span>
                            </div>
                        `;
                        feedList.appendChild(card);
                    });
                }
            } catch (_) {}
        };

        window.clearVoiceTurnHistory = function () {
            const feedList = document.getElementById('voiceFeedList');
            if (!feedList) return;
            const sid = activeVoiceSessionId || new URLSearchParams(window.location.search).get('session') || 'current';
            try { localStorage.removeItem('simba_voice_history_' + sid); } catch (_) {}
            feedList.innerHTML = `
                <div class="voice-feed-empty" id="voiceFeedEmpty">
                    <i class="fa-solid fa-headset" style="font-size:24px; opacity:0.3; margin-bottom:8px;"></i>
                    <div>Spoken conversation turns will be recorded here with instant audio replay.</div>
                </div>
            `;
            if (typeof showSimbaToast === 'function') {
                showSimbaToast('Voice conversation history cleared', 'info', 1800);
            }
        };

        '''

code = code[:idx_rec_start] + new_record_block + code[idx_rec_end:]

# Call restoreVoiceHistoryFromStorage in DOMContentLoaded
old_dom_content = '''            if (typeof initVoiceAgent === 'function') {
                initVoiceAgent();
            }'''

new_dom_content = '''            if (typeof initVoiceAgent === 'function') {
                initVoiceAgent();
            }
            if (typeof restoreVoiceHistoryFromStorage === 'function') {
                restoreVoiceHistoryFromStorage();
            }'''

assert old_dom_content in code, "old_dom_content not found!"
code = code.replace(old_dom_content, new_dom_content)

# Also fix the autolisten trigger
old_autolisten = '''            // Auto-start voice recognition if triggered by global hotkey (?autolisten=1)
            const urlParams = new URLSearchParams(window.location.search);
            if (urlParams.get('autolisten') === '1') {
                setTimeout(() => {
                    if (typeof startVoiceListening === 'function') {
                        startVoiceListening();
                    } else if (typeof toggleVoiceListening === 'function') {
                        toggleVoiceListening();
                    }
                }, 400);
            }'''

new_autolisten = '''            // Auto-start voice recognition if triggered by global hotkey (?autolisten=1)
            const urlParams = new URLSearchParams(window.location.search);
            if (urlParams.get('autolisten') === '1') {
                setTimeout(() => {
                    if (typeof toggleVoiceAgentListening === 'function') {
                        toggleVoiceAgentListening();
                    }
                }, 500);
            }'''

assert old_autolisten in code, "old_autolisten not found!"
code = code.replace(old_autolisten, new_autolisten)

with open('templates/chat/scripts.html', 'w', encoding='utf-8') as f:
    f.write(code)

print("Successfully updated templates/chat/scripts.html with all functional fixes!")
