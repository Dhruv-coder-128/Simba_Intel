
                    (function () {
                        var core = document.getElementById('qcCore');
                        var coreWrap = document.getElementById('qcCoreWrap');
                        var statusEl = document.getElementById('qcCoreStatus');
                        var homeEl = document.getElementById('qcHome');
                        if (!core || !coreWrap) return;

                        var reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
                            || document.documentElement.getAttribute('data-animation') === 'none'
                            || document.documentElement.getAttribute('data-animation') === 'reduced';

                        // Each command's own mode: color, orbit-speed multiplier
                        // (relative to idle), and glow-pulse intensity multiplier.
                        // The center glyph itself never changes (see .qc-core-logo -
                        // it's the brand mark, not a per-mode icon) - only its glow
                        // color follows the mode, same as everything else.
                        var MODES = {
                            document: { rgb: '110, 200, 255', label: 'DOCUMENT MODE', speed: 1.3, pulse: 1.0 },
                            vision: { rgb: '255, 185, 80', label: 'VISION MODE', speed: 0.6, pulse: 1.15 },
                            coding: { rgb: '110, 255, 160', label: 'CODING MODE', speed: 1.9, pulse: 1.0 },
                            diagnostics: { rgb: '255, 95, 95', label: 'DIAGNOSTICS MODE', speed: 2.2, pulse: 1.25 },
                            image: { rgb: '255, 105, 210', label: 'IMAGE STUDIO MODE', speed: 0.9, pulse: 1.3 },
                            frontend: { rgb: '80, 230, 210', label: 'FRONTEND MODE', speed: 1.6, pulse: 1.05 },
                            database: { rgb: '150, 140, 255', label: 'DATABASE MODE', speed: 1.0, pulse: 0.9 },
                            memory: { rgb: '215, 170, 255', label: 'MEMORY MODE', speed: 0.7, pulse: 1.1 }
                        };
                        var IDLE_LABEL = 'IDLE';

                        // ---- Staged, cinematic mode transition ----
                        // Colors/glow are plain CSS transitions (see the .qc-* rules
                        // in <style> - each layer has its own transition-delay so
                        // glow -> rings -> particles -> pulse cascade in, matching
                        // "glow gradually changes, then rings accelerate, then
                        // particles shift color, then pulse grows"). Ring rotation
                        // SPEED can't be smoothly interpolated by CSS at all
                        // (animation-duration changes snap at the next cycle
                        // instead of easing), so it's driven by the rAF loop below
                        // instead, which eases toward a target speed every frame -
                        // that's what actually satisfies "rings should never stop
                        // instantly, smooth easing only." Status text can't be
                        // transitioned either (text content isn't animatable), so
                        // it gets a manual opacity crossfade timed to land last in
                        // the sequence.
                        var statusFadeTimer = null;

                        function crossfadeStatus(label) {
                            if (!statusEl) return;
                            clearTimeout(statusFadeTimer);
                            statusEl.style.opacity = '0';
                            statusFadeTimer = setTimeout(function () {
                                statusEl.textContent = label;
                                requestAnimationFrame(function () {
                                    statusEl.style.opacity = '1';
                                });
                            }, 200);
                        }

                        function applyMode(modeKey) {
                            var m = modeKey && MODES[modeKey];
                            if (m) {
                                core.style.setProperty('--mode-rgb', m.rgb);
                                core.style.setProperty('--pulse-scale', m.pulse);
                                ringSpeed.target = m.speed;
                                crossfadeStatus(m.label);
                            } else {
                                core.style.removeProperty('--mode-rgb');
                                core.style.removeProperty('--pulse-scale');
                                ringSpeed.target = 1;
                                crossfadeStatus(IDLE_LABEL);
                            }
                        }

                        window.applyQcMode = applyMode;

                        document.querySelectorAll('#qcHome .qc-chip[data-mode]').forEach(function (chip) {
                            chip.addEventListener('mouseenter', function () { applyMode(chip.dataset.mode); });
                            chip.addEventListener('focus', function () { applyMode(chip.dataset.mode); });
                            chip.addEventListener('mouseleave', function () { applyMode(null); });
                            chip.addEventListener('blur', function () { applyMode(null); });
                        });

                        // ---- Ring/orbit rotation, driven by requestAnimationFrame ----
                        // Idle speed -> acceleration -> target speed -> deceleration
                        // -> idle, with pure easing (exponential smoothing toward a
                        // target multiplier every frame) instead of CSS keyframes,
                        // which is the only way to get a genuinely smooth speed
                        // change rather than a snap at the next animation cycle.
                        // Skipped entirely under reduced motion - rings stay static.
                        var ringEls = {
                            outer: core.querySelector('.qc-ring-outer'),
                            mid: core.querySelector('.qc-ring-mid'),
                            orbit: core.querySelector('.qc-core-orbit:not(.qc-orbit-reverse)'),
                            orbitRev: core.querySelector('.qc-orbit-reverse')
                        };
                        var ringBaseDegPerSec = { outer: 14, mid: -46, orbit: 62, orbitRev: -42 };
                        var ringAngle = { outer: 0, mid: 0, orbit: 0, orbitRev: 0 };
                        var ringSpeed = { current: 1, target: 1 };
                        var lastFrameTime = null;

                        function tickRings(now) {
                            // Same self-stopping idea as the clock below - once
                            // the welcome screen is hidden (first message sent),
                            // there's no point still computing rotation angles for
                            // an invisible element every frame for the rest of the
                            // page's life.
                            if (!homeEl || !homeEl.isConnected || homeEl.style.display === 'none') return;

                            if (lastFrameTime === null) lastFrameTime = now;
                            var dt = Math.min((now - lastFrameTime) / 1000, 0.05);
                            lastFrameTime = now;

                            ringSpeed.current += (ringSpeed.target - ringSpeed.current) * Math.min(dt * 3.2, 1);

                            for (var key in ringEls) {
                                var el = ringEls[key];
                                if (!el) continue;
                                ringAngle[key] = (ringAngle[key] + ringBaseDegPerSec[key] * ringSpeed.current * dt) % 360;
                                el.style.transform = 'rotate(' + ringAngle[key].toFixed(2) + 'deg)';
                            }

                            requestAnimationFrame(tickRings);
                        }
                        if (!reducedMotion) {
                            requestAnimationFrame(tickRings);
                        }

                        // Subtle mouse-tracking tilt - pointer devices only, and
                        // never fires at all under reduced-motion preferences.
                        if (!reducedMotion && window.matchMedia('(pointer: fine)').matches) {
                            coreWrap.addEventListener('mousemove', function (e) {
                                var rect = coreWrap.getBoundingClientRect();
                                var px = (e.clientX - rect.left) / rect.width - 0.5;
                                var py = (e.clientY - rect.top) / rect.height - 0.5;
                                core.style.transform = 'rotateX(' + (-py * 10).toFixed(2) + 'deg) rotateY(' + (px * 10).toFixed(2) + 'deg)';
                            });
                            coreWrap.addEventListener('mouseleave', function () {
                                core.style.transform = '';
                            });
                        }

                        // Live status bar clock - stops itself once the welcome
                        // screen is hidden (sendQuery() hides it via display:none
                        // rather than removing it, since a returning user might
                        // come back to an empty session later) so this doesn't
                        // keep ticking in the background for the rest of the
                        // page's life after the first message is sent.
                        var timeEl = document.getElementById('qcTime');
                        var dateEl = document.getElementById('qcDate');
                        var clockInterval = setInterval(function () {
                            if (!homeEl || !homeEl.isConnected || homeEl.style.display === 'none') {
                                clearInterval(clockInterval);
                                return;
                            }
                            var now = new Date();
                            if (timeEl) timeEl.textContent = now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
                            if (dateEl) dateEl.textContent = now.toLocaleDateString([], { weekday: 'short', year: 'numeric', month: 'short', day: 'numeric' });
                        }, 1000);
                        if (timeEl) timeEl.textContent = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
                        if (dateEl) dateEl.textContent = new Date().toLocaleDateString([], { weekday: 'short', year: 'numeric', month: 'short', day: 'numeric' });
                    })();
                