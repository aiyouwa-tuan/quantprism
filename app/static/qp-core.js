/* QuantPrism — Interaction Enhancement JS (qp-core.js) */

(function () {
    'use strict';

    /* ═══ CountUp Animation ═══ */
    function initCountUp(el, duration) {
        duration = duration || 800;
        var target = parseFloat(el.getAttribute('data-target') || el.textContent);
        if (isNaN(target)) return;
        var fmt = el.getAttribute('data-format') || 'number';
        var start = 0;
        var startTime = null;

        function easeOut(t) { return 1 - Math.pow(1 - t, 3); }

        function formatVal(v) {
            switch (fmt) {
                case 'percent':
                    return v.toFixed(1) + '%';
                case 'currency':
                    return '$' + v.toLocaleString('en-US', { minimumFractionDigits: 0, maximumFractionDigits: 0 });
                case 'ratio':
                    return v.toFixed(2);
                default:
                    return Math.abs(v) >= 100 ? Math.round(v).toLocaleString() : v.toFixed(1);
            }
        }

        function step(ts) {
            if (!startTime) startTime = ts;
            var progress = Math.min((ts - startTime) / duration, 1);
            var current = start + (target - start) * easeOut(progress);
            el.textContent = formatVal(current);
            if (progress < 1) requestAnimationFrame(step);
        }
        el.textContent = formatVal(0);
        requestAnimationFrame(step);
    }

    /* ═══ Card Stagger ═══ */
    function initCardStagger(container) {
        if (!container) return;
        var children = container.querySelectorAll('.qp-card-enter');
        children.forEach(function (child, i) {
            child.style.animationDelay = Math.min(i * 0.06, 0.36) + 's';
        });
    }

    /* ═══ Skeleton Helpers ═══ */
    function showSkeleton(containerId, count) {
        var el = document.getElementById(containerId);
        if (!el) return;
        count = count || 3;
        var html = '';
        for (var i = 0; i < count; i++) {
            html += '<div class="qp-skeleton h-16 rounded-lg mb-3"></div>';
        }
        el.innerHTML = html;
        el.setAttribute('aria-busy', 'true');
    }

    function hideSkeleton(containerId) {
        var el = document.getElementById(containerId);
        if (el) el.setAttribute('aria-busy', 'false');
    }

    /* ═══ Tab System ═══ */
    function initTabs(containerSelector) {
        var container = document.querySelector(containerSelector);
        if (!container) return;
        var tabs = container.querySelectorAll('.qp-tab');
        var panels = container.querySelectorAll('.qp-tab-content');
        var chartInited = {};

        tabs.forEach(function (tab) {
            tab.addEventListener('click', function () {
                var target = tab.getAttribute('data-tab');
                tabs.forEach(function (t) { t.classList.remove('active'); });
                panels.forEach(function (p) { p.classList.remove('active'); });
                tab.classList.add('active');
                var panel = container.querySelector('#' + target);
                if (panel) panel.classList.add('active');

                // Lazy-init charts on first activation
                if (!chartInited[target]) {
                    chartInited[target] = true;
                    var evt = new CustomEvent('qp:tab-activate', { detail: { tabId: target } });
                    document.dispatchEvent(evt);
                }
                // Resize existing charts
                if (window.qpCharts && window.qpCharts[target]) {
                    window.qpCharts[target].forEach(function (c) {
                        if (c && c.resize) c.resize();
                    });
                }
            });
        });
    }

    /* ═══ Side Panel ═══ */
    function openSidePanel(panelId) {
        var panel = document.getElementById(panelId);
        if (panel) panel.classList.add('open');
    }

    function closeSidePanel(panelId) {
        var panel = document.getElementById(panelId);
        if (panel) panel.classList.remove('open');
    }

    /* ═══ Position Tab Filter ═══ */
    function initPositionTabs() {
        var tabs = document.querySelectorAll('.qp-pos-tab');
        if (!tabs.length) return;
        tabs.forEach(function (tab) {
            tab.addEventListener('click', function () {
                var type = tab.getAttribute('data-type');
                tabs.forEach(function (t) { t.classList.remove('active', 'bg-dark-500', 'text-white'); t.classList.add('bg-dark-700', 'text-gray-400'); });
                tab.classList.remove('bg-dark-700', 'text-gray-400');
                tab.classList.add('active', 'bg-dark-500', 'text-white');
                document.querySelectorAll('.qp-pos-row').forEach(function (row) {
                    if (type === 'all' || row.getAttribute('data-type') === type) {
                        row.style.display = '';
                    } else {
                        row.style.display = 'none';
                    }
                });
            });
        });
    }

    /* ═══ MutationObserver: auto-init on HTMX swap ═══ */
    var observer = new MutationObserver(function (mutations) {
        mutations.forEach(function (m) {
            m.addedNodes.forEach(function (node) {
                if (node.nodeType !== 1) return;
                // CountUp
                node.querySelectorAll && node.querySelectorAll('.qp-number-up').forEach(function (el) {
                    initCountUp(el);
                });
                // Card stagger
                if (node.querySelector && node.querySelector('.qp-card-enter')) {
                    initCardStagger(node);
                }
            });
        });
    });
    observer.observe(document.body, { childList: true, subtree: true });

    /* ═══ HTMX Integration ═══ */
    document.addEventListener('htmx:beforeRequest', function (evt) {
        var target = evt.detail.target;
        if (target && target.id) {
            target.setAttribute('aria-busy', 'true');
        }
    });

    document.addEventListener('htmx:afterSwap', function (evt) {
        var target = evt.detail.target;
        if (!target) return;
        target.setAttribute('aria-busy', 'false');
        target.querySelectorAll('.qp-number-up').forEach(function (el) { initCountUp(el); });
        if (target.querySelector('.qp-card-enter')) initCardStagger(target);
    });

    /* ═══ Init on DOMContentLoaded ═══ */
    document.addEventListener('DOMContentLoaded', function () {
        document.querySelectorAll('.qp-number-up').forEach(function (el) { initCountUp(el); });
        document.querySelectorAll('.qp-card-stagger').forEach(function (c) { initCardStagger(c); });
        initPositionTabs();

        // Init all tab systems
        document.querySelectorAll('.qp-tabs-container').forEach(function (c) {
            initTabs('#' + c.id);
        });
    });

    /* ═══ Expose to global ═══ */
    window.qpCore = {
        initCountUp: initCountUp,
        initCardStagger: initCardStagger,
        showSkeleton: showSkeleton,
        hideSkeleton: hideSkeleton,
        initTabs: initTabs,
        openSidePanel: openSidePanel,
        closeSidePanel: closeSidePanel,
        initPositionTabs: initPositionTabs,
    };

    // Chart registry for resize on tab activation
    window.qpCharts = window.qpCharts || {};

})();
