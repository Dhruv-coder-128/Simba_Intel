const fs = require('fs');
const vm = require('vm');

const code = fs.readFileSync('scratch/live_script_fixed.js', 'utf8');

// Scenario 1: Standard browser without AudioContext permission on load
const mockWindow = {
    location: { href: 'http://127.0.0.1:8000/', search: '', pathname: '/' },
    sessionStorage: {
        getItem: () => null,
        setItem: () => {}
    },
    localStorage: {
        getItem: () => null,
        setItem: () => {}
    },
    addEventListener: () => {},
    removeEventListener: () => {},
    setTimeout: setTimeout,
    clearTimeout: clearTimeout,
    setInterval: setInterval,
    clearInterval: clearInterval,
    console: console,
    // AudioContext undefined or throws when called without user gesture
    AudioContext: function() {
        throw new Error('DOMException: AudioContext was not allowed to start. It must be resumed (or created) after a user gesture on the page.');
    },
    webkitAudioContext: undefined
};

const mockDocument = {
    documentElement: { dataset: {} },
    getElementById: (id) => {
        return {
            id,
            style: {},
            classList: { add: () => {}, remove: () => {}, contains: () => false },
            addEventListener: () => {},
            querySelectorAll: () => [],
            appendChild: () => {}
        };
    },
    querySelectorAll: () => [],
    querySelector: () => null,
    createElement: (tag) => ({
        style: {},
        classList: { add: () => {}, remove: () => {} },
        appendChild: () => {}
    }),
    addEventListener: () => {},
    cookie: ''
};

const sandbox = {
    window: mockWindow,
    document: mockDocument,
    console: console,
    setTimeout: setTimeout,
    clearTimeout: clearTimeout,
    setInterval: setInterval,
    clearInterval: clearInterval,
    AudioContext: mockWindow.AudioContext,
    webkitAudioContext: undefined,
    performance: { getEntriesByType: () => [] },
    navigator: { userAgent: 'test', clipboard: { writeText: () => Promise.resolve() } },
    URLSearchParams: URLSearchParams,
    AbortSignal: { timeout: () => {} },
    fetch: () => Promise.resolve({ json: () => Promise.resolve({}) })
};

sandbox.window.document = mockDocument;

try {
    vm.createContext(sandbox);
    vm.runInContext(code, sandbox);
    console.log('Script executed successfully!');
} catch (err) {
    console.error('CRASH ON SCRIPT LOAD:');
    console.error(err);
}
