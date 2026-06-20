const csrfToken = document.getElementById("csrf-token").value;

// ================= MENU, PIN, DELETE, RENAME, COPY, SHARE =================
function toggleMenu(event, id) {
    event.stopPropagation();
    document.querySelectorAll('.side-dropdown').forEach(d => d.classList.remove('show'));
    document.getElementById(id).classList.toggle('show');
}

window.addEventListener("click", function (e) {
    if (!e.target.closest('.side-menu')) {
        document.querySelectorAll('.side-dropdown').forEach(d => d.classList.remove('show'));
    }
});

async function togglePin(id) {
    try {
        const res = await fetch(`/pin_session/${id}/`, {
            method: "POST",
            headers: {
                "Content-Type": "application/x-www-form-urlencoded",
                "X-CSRFToken": csrfToken
            }
        });
        if (res.ok) location.reload();
        else alert("Pin failed");
    } catch (err) { console.error(err); }
}

async function deleteChat(id) {
    if (!confirm("DELETE_SESSION?")) return;
    const res = await fetch(`/delete_session/${id}/`, {
        method: "POST",
        headers: {
            "Content-Type": "application/x-www-form-urlencoded",
            "X-CSRFToken": csrfToken
        }
    });
    if (res.ok) location.href = "/";
}

async function renameChat(id, oldTitle) {
    const newTitle = prompt("New Title:", oldTitle);
    if (!newTitle || newTitle === oldTitle) return;
    await fetch(`/rename_session/${id}/`, {
        method: "POST",
        headers: {
            "Content-Type": "application/x-www-form-urlencoded",
            "X-CSRFToken": csrfToken
        },
        body: `title=${encodeURIComponent(newTitle)}`
    });
    location.reload();
}

function copyToClipboard(text, btn) {
    navigator.clipboard.writeText(text).then(() => {
        const original = btn.innerHTML;
        btn.innerHTML = '<i class="fa-solid fa-check"></i> COPIED!';
        setTimeout(() => btn.innerHTML = original, 2000);
    });
}

function shareChat(text) {
    if (navigator.share) {
        navigator.share({ title: "Simba Intel Log", text: text });
    } else { alert("Sharing not supported."); }
}

// ================= FORMAT & CODE BUTTONS =================
function formatAllMessages() {
    document.querySelectorAll(".simba-block").forEach(block => {
        const raw = block.querySelector(".raw-data");
        const content = block.querySelector(".markdown-content");
        if (raw && content && raw.value.trim() !== "") {
            content.innerHTML = marked.parse(raw.value.trim());
            if (window.Prism) Prism.highlightAllUnder(content);
        }
    });
    applyCodeButtons();
}

function applyCodeButtons() {
    document.querySelectorAll("pre").forEach(pre => {

        if (pre.querySelector(".copy-btn")) return;

        pre.style.position = "relative";

        const btn = document.createElement("button");
        btn.className = "copy-btn";
        btn.style.position = "absolute";
        btn.style.top = "8px";
        btn.style.right = "10px";
        btn.innerHTML = '<i class="fa-regular fa-copy"></i> COPY';

        btn.onclick = function () {

            const codeElement = pre.querySelector("code");

            let codeText = "";

            if (codeElement) {
                codeText = codeElement.innerText;
            } else {
                codeText = pre.innerText;
            }

            navigator.clipboard.writeText(codeText).then(() => {
                btn.innerHTML = "COPIED!";
                setTimeout(() => {
                    btn.innerHTML = '<i class="fa-regular fa-copy"></i> COPY_CODE';
                }, 2000);
            });

        };

        pre.appendChild(btn);
    });
}

// ================= Custom Dropdown Logic (૧૦૦% સિંક ફિક્સ્ડ) =================
const select = document.getElementById("cyberSelect");
const optionsBox = document.getElementById("cyberOptions");
const hiddenInput = document.getElementById("model-selector");
const selectedText = document.getElementById("selectedText");

select.addEventListener("click", (e) => {
    e.stopPropagation();
    const isVisible = optionsBox.style.display === "block";
    optionsBox.style.display = isVisible ? "none" : "block";
    select.classList.toggle("open");
});

document.querySelectorAll(".cyber-option").forEach(option => {
    option.addEventListener("click", async function (e) {
        e.stopPropagation();
        const value = this.getAttribute("data-value");
        const text = this.innerText;

        hiddenInput.value = value;
        selectedText.innerText = text;
        localStorage.setItem("selected_simba_model", value); // કી ફિક્સ કરી [cite: 2026-03-01]

        document.querySelectorAll(".cyber-option").forEach(o => o.classList.remove("active"));
        this.classList.add("active");

        // સર્વરના સેશનને પણ તે જ સમયે અપડેટ કરો [cite: 2026-03-01]
        try {
            await fetch(`/update_model/?model=${value}`);
            console.log("SIMBA_SESSION: Model synced to " + value);
        } catch (err) { console.log("Sync Error"); }

        optionsBox.style.display = "none";
        select.classList.remove("open");
    });
});

window.addEventListener("click", () => {
    if (optionsBox) optionsBox.style.display = "none";
    if (select) select.classList.remove("open");
});

// ================= URL SYNC & HISTORY FIX =================
function updateBrowserURL(sessionId) {
    const url = new URL(window.location.href);
    if (url.searchParams.get('session') !== sessionId) {
        url.searchParams.set('session', sessionId);
        window.history.replaceState({ path: url.href }, '', url.href); // આનાથી રિફ્રેશ પર ચેટ રહેશે [cite: 2026-03-01]
    }
}

/// ================= SEND QUERY (ચેટ અને સેશન સિંક સાથે) =================
async function sendQuery(event) {
    if (event) event.preventDefault();

    const input = document.getElementById("user-input");
    const query = input.value.trim();
    if (!query) return;

    function setStatus(state, text) {
        const el = document.getElementById("aiStatus");
        if (!el) return;
        el.className = "ai-status " + state;
        el.querySelector(".status-text").innerText = text;
    }

    // 🟡 PROCESSING STATE
    setStatus("status-processing", "PROCESSING...");

    const welcomeContainer = document.querySelector('.welcome-container');
    if (welcomeContainer) welcomeContainer.style.display = 'none';

    const currentModel =
        document.getElementById("model-selector").value ||
        localStorage.getItem("selected_simba_model") ||
        "offline";

    input.value = "";
    const cf = document.getElementById("chat-flow");

    let formattedQuery = query;

    // detect code
    if (query.includes("{") || query.includes(";") || query.includes("function") || query.includes("const")) {
        formattedQuery = `<pre><code class="language-js">${query.replace(/</g, "&lt;").replace(/>/g, "&gt;")}</code></pre>`;
    }

    cf.insertAdjacentHTML("beforeend", `
<div class="chat-block user-block">
<span class="msg-label">DHRUV_INPUT</span>
<div class="content">${formattedQuery}</div>
</div>
`);

    if (window.Prism) Prism.highlightAll();

    const loaderId = "load-" + Date.now();

    cf.insertAdjacentHTML("beforeend", `
        <div class="chat-block simba-block" id="${loaderId}">
            <span class="msg-label" id="status-label-${loaderId}">
                SIMBA_STATUS: INITIALIZING...
            </span>
            <div class="content">
                <div class="typing-loader">
                    <div class="typing-dot"></div>
                    <div class="typing-dot"></div>
                    <div class="typing-dot"></div>
                </div>
            </div>
        </div>
    `);

    cf.scrollTop = cf.scrollHeight;

    const statusMessages = [
        "OPTIMIZING LOGIC PATH...",
        "ACCESSING DATABASE...",
        "SIMBA_AI: GENERATING...",
        "ANALYZING QUERY STRUCTURE..."
    ];

    let msgIndex = 0;
    const labelElement = document.getElementById(`status-label-${loaderId}`);

    const statusInterval = setInterval(() => {
        if (labelElement) {
            labelElement.innerText =
                "SIMBA_STATUS: " + statusMessages[msgIndex];
            msgIndex = (msgIndex + 1) % statusMessages.length;
        }
    }, 1500);

    try {
        const startTime = performance.now();

        const res = await fetch("/ask_ai/", {
            method: "POST",
            headers: {
                "Content-Type": "application/x-www-form-urlencoded",
                "X-CSRFToken": csrfToken
            },
            body: `query=${encodeURIComponent(query)}&model_choice=${encodeURIComponent(currentModel)}&session_id=${new URLSearchParams(window.location.search).get("session")}`
        });

        if (!res.ok) throw new Error(`Server error: ${res.status}`);

        const sID = res.headers.get('X-Session-ID');
        const urlParams = new URLSearchParams(window.location.search);

        if (sID && !urlParams.get('session')) {
            const sidebarList =
                document.querySelector('.archive-list') ||
                document.querySelector('.archive_logs');

            if (sidebarList) {
                const displayTitle =
                    query.length > 20 ? query.substring(0, 20) + "..." : query;

                const newEntry = `
                    <div class="sidebar-item active" style="animation: slideIn 0.3s ease;">
                        <a href="/?session=${sID}">> ${displayTitle}</a>
                    </div>
                `;
                sidebarList.insertAdjacentHTML('afterbegin', newEntry);
            }

            updateBrowserURL(sID);
        }

        clearInterval(statusInterval);

        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let fullResponse = "";
        let isThinking = false;
        let firstTokenReceived = false;

        const loader = document.getElementById(loaderId);
        const contentDiv = loader.querySelector('.content');

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            const chunk = decoder.decode(value, { stream: true });
            const isAtBottom =
                cf.scrollHeight - cf.clientHeight <= cf.scrollTop + 100;

            if (!firstTokenReceived) {
                contentDiv.innerHTML = "";
                labelElement.innerText = "SIMBA_RESPONSE";
                firstTokenReceived = true;
            }

            // Create containers only once
            if (!contentDiv.querySelector('.markdown-content')) {
                contentDiv.innerHTML = `
            <div class="markdown-content"></div>
        `;
            }

            const markdownDiv = contentDiv.querySelector('.markdown-content');
            const thoughtContent = contentDiv.querySelector('.thought-content');
            const thinkingBox = contentDiv.querySelector('.thinking-box');

            // Handle thinking mode
            if (chunk.includes("<think>")) isThinking = true;

            if (isThinking) {
                let part = chunk.replace("<think>", "");

                if (part.includes("</think>")) {
                    let splitParts = part.split("</think>");

                    if (thoughtContent)
                        thoughtContent.innerText += splitParts[0];

                    isThinking = false;
                    if (thinkingBox) thinkingBox.open = false;

                    fullResponse += splitParts[1];
                } else {
                    if (thoughtContent)
                        thoughtContent.innerText += part;
                }
            } else {
                fullResponse += chunk.replace("</think>", "");
            }

            // ⚡ LIGHTER UPDATE (no Prism here)
            if (markdownDiv) {
                markdownDiv.innerHTML = marked.parse(fullResponse);
            }

            if (isAtBottom) cf.scrollTop = cf.scrollHeight;
        }

        // Highlight only once after full response complete
        if (window.Prism) Prism.highlightAllUnder(loader);
        applyCodeButtons();

        // const latency =
        //     ((performance.now() - startTime) / 1000).toFixed(2);

        loader.insertAdjacentHTML("beforeend", `
                    <textarea class="raw-data" style="display:none;">
                        ${fullResponse}
                    </textarea>

                    <div style="display:flex;gap:10px;margin-top:5px;">
                        <button class="copy-btn"
                            onclick="copyToClipboard(
                            this.closest('.simba-block')
                            .querySelector('.raw-data').value,this)">
                            COPY_INTEL
                        </button>

                        <button class="copy-btn"
                            onclick="shareChat(
                            this.closest('.simba-block')
                            .querySelector('.raw-data').value)">
                            SHARE
                        </button>
                    </div>
                `);

        const latency = ((performance.now() - startTime) / 1000).toFixed(2);

        setStatus("status-online", "CORE ONLINE");

        if (labelElement) {
            labelElement.innerText = `SIMBA_RESPONSE • ${latency}s`;
        }

    } catch (error) {
        clearInterval(statusInterval);
        console.error("Error:", error);

        const loader = document.getElementById(loaderId);
        if (loader)
            loader.querySelector('.content').innerText =
                "SYSTEM ERROR: " + error.message;

        // 🔴 ERROR STATE
        setStatus("status-offline", "CONNECTION LOST");
    }
}

// ================= LOCAL STORAGE & INIT =================
window.addEventListener("load", () => {
    const savedModel = localStorage.getItem("selected_simba_model"); // કી મેચ કરી [cite: 2026-03-01]
    if (savedModel) {
        hiddenInput.value = savedModel;
        document.querySelectorAll(".cyber-option").forEach(option => {
            if (option.getAttribute("data-value") === savedModel) {
                option.classList.add("active");
                selectedText.innerText = option.innerText;
            } else {
                option.classList.remove("active");
            }
        });
    }
    formatAllMessages(); // જૂની ચેટને પ્રોપર બતાવવા માટે [cite: 2026-03-01]
    const cf = document.getElementById("chat-flow");
    if (cf) cf.scrollTop = cf.scrollHeight;
});

// ================= LIVE STATEMENT UPDATE =================
function updateSystemStats() {
    fetch('/system_stats/')
        .then(res => res.json())
        .then(data => {

            const circumference = 2 * Math.PI * 50; // r = 50 (SVG circle radius)

            const cpuVal = document.getElementById("cpu-val");
            const ramVal = document.getElementById("ram-val");

            const cpuCircle = document.getElementById("cpu-circle");
            const ramCircle = document.getElementById("ram-circle");

            // ---- CPU ----
            if (cpuVal && cpuCircle) {
                cpuVal.innerText = data.cpu + "%";

                const cpuOffset = circumference - (data.cpu / 100) * circumference;
                cpuCircle.style.strokeDashoffset = cpuOffset;

                // Color change based on load
                cpuCircle.style.stroke = data.cpu > 85 ? "#ff4444" : "#bf9b30";
            }

            // ---- RAM ----
            if (ramVal && ramCircle) {
                ramVal.innerText = data.ram + "%";

                const ramOffset = circumference - (data.ram / 100) * circumference;
                ramCircle.style.strokeDashoffset = ramOffset;

                ramCircle.style.stroke = data.ram > 85 ? "#ff4444" : "#bf9b30";
            }

            // ---- Accent Color Optimization ----
            let currentAccent = getComputedStyle(document.documentElement)
                .getPropertyValue('--accent').trim();

            if (data.cpu > 65 && currentAccent !== '#ff4444') {
                document.documentElement.style.setProperty('--accent', '#ff4444');
            }

            if (data.cpu <= 65 && currentAccent !== '#00e5ff') {
                document.documentElement.style.setProperty('--accent', '#00e5ff');
            }

        })
        .catch(() => console.log("Re-establishing metrics link..."));
}
let statsInterval = setInterval(updateSystemStats, 1000);
window.addEventListener("load", updateSystemStats);



// ===== SIMBA MIC VOICE SYSTEM =====

const micBtn = document.getElementById("micBtn")
const inputBox = document.getElementById("user-input")
const waveContainer = document.getElementById("wave-container")

let recognition
let listening = false


// ---- COMMAND ENGINE ----
function runVoiceCommand(text) {

    text = text.toLowerCase().trim()

    if (text.includes("open youtube")) {
        window.open("https://youtube.com", "_blank")
        return true
    }

    if (text.includes("open google")) {
        window.open("https://google.com", "_blank")
        return true
    }

    if (text.includes("open github")) {
        window.open("https://github.com", "_blank")
        return true
    }

    if (text.includes("open reddit")) {
        window.open("https://reddit.com", "_blank")
        return true
    }

    if (text.startsWith("open ")) {
        let site = text.replace("open ", "").trim()
        window.open("https://" + site + ".com", "_blank")
        return true
    }

    if (text.startsWith("play ")) {

        let song = text.replace("play ", "")

        let url = "https://www.youtube.com/results?search_query=" + encodeURIComponent(song)

        window.open(url, "_blank")

        return true
    }

    // if (text.includes("play music")) {
    //     window.open("https://music.youtube.com/search?q=lofi", "_blank")
    //     return true
    // }

    return false
}


// ---- SPEECH ENGINE ----
if ('webkitSpeechRecognition' in window) {

    recognition = new webkitSpeechRecognition()

    recognition.continuous = true
    recognition.interimResults = true
    recognition.lang = "en-US"

    recognition.onstart = () => {

        micBtn.classList.add("mic-active")

        if (waveContainer) {
            waveContainer.style.display = "flex"
        }

    }


    recognition.onresult = (event) => {

        let transcript = ""

        for (let i = event.resultIndex; i < event.results.length; i++) {
            transcript += event.results[i][0].transcript
        }

        transcript = transcript.trim()

        // show live speech
        inputBox.value = transcript


        if (event.results[event.results.length - 1].isFinal) {

            let executed = runVoiceCommand(transcript)

            if (executed) {

                inputBox.value = ""

                listening = false
                recognition.stop()

            }

        }

    }


    recognition.onend = () => {

        micBtn.classList.remove("mic-active")

        if (waveContainer) {
            waveContainer.style.display = "none"
        }

        if (listening) {
            recognition.start()
        }

    }

}


// ---- MIC BUTTON ----
micBtn.onclick = () => {

    if (!recognition) return

    if (!listening) {

        listening = true
        recognition.start()

    } else {

        listening = false
        recognition.stop()

    }

}



const input = document.getElementById("user-input");

input.addEventListener("input", () => {

    input.style.height = "auto";

    if (input.scrollHeight < 20) {
        input.style.height = input.scrollHeight + "px";
    }

});
document.getElementById("user-input").addEventListener("keydown", function (e) {

    if (e.key === "Enter" && !e.shiftKey) {

        e.preventDefault()

        sendQuery()

    }

})