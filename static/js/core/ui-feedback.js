const AppFeedback = (function() {
    'use strict';

    let stackEl = null;
    let nextToastId = 1;

    function init() {
        ensureStack();
        installGlobalHandlers();
    }

    function ensureStack() {
        if (stackEl && document.body.contains(stackEl)) return stackEl;

        stackEl = document.getElementById('appToastStack');
        if (!stackEl) {
            stackEl = document.createElement('div');
            stackEl.id = 'appToastStack';
            stackEl.className = 'app-toast-stack';
            document.body.appendChild(stackEl);
        }
        return stackEl;
    }

    function toast(options) {
        const opts = options || {};
        const type = normalizeType(opts.type);
        const id = nextToastId++;
        const durationMs = Number.isFinite(opts.durationMs) ? opts.durationMs : 6500;

        const root = document.createElement('div');
        root.className = `app-toast ${type}`;
        root.dataset.toastId = String(id);

        const titleEl = document.createElement('div');
        titleEl.className = 'app-toast-title';
        titleEl.textContent = String(opts.title || defaultTitle(type));
        root.appendChild(titleEl);

        const msgEl = document.createElement('div');
        msgEl.className = 'app-toast-msg';
        msgEl.textContent = String(opts.message || '');
        root.appendChild(msgEl);

        const actions = Array.isArray(opts.actions) ? opts.actions.filter(Boolean).slice(0, 3) : [];
        if (actions.length > 0) {
            const actionsEl = document.createElement('div');
            actionsEl.className = 'app-toast-actions';
            for (const action of actions) {
                const btn = document.createElement('button');
                btn.type = 'button';
                btn.textContent = String(action.label || 'Action');
                btn.addEventListener('click', () => {
                    try {
                        if (typeof action.onClick === 'function') {
                            action.onClick();
                        }
                    } finally {
                        removeToast(id);
                    }
                });
                actionsEl.appendChild(btn);
            }
            root.appendChild(actionsEl);
        }

        ensureStack().appendChild(root);

        if (durationMs > 0) {
            window.setTimeout(() => {
                removeToast(id);
            }, durationMs);
        }

        return id;
    }

    function removeToast(id) {
        if (!stackEl) return;
        const toastEl = stackEl.querySelector(`[data-toast-id="${id}"]`);
        if (!toastEl) return;
        toastEl.remove();
    }

    function reportError(context, error, options) {
        const opts = options || {};
        const message = extractMessage(error);
        const actions = [];

        if (isSettingsError(message)) {
            actions.push({
                label: 'Open Settings',
                onClick: () => {
                    if (typeof showSettings === 'function') {
                        showSettings();
                    }
                }
            });
        }

        if (isNetworkError(message)) {
            actions.push({
                label: 'Retry',
                onClick: () => {
                    if (typeof opts.onRetry === 'function') {
                        opts.onRetry();
                    }
                }
            });
        }

        if (typeof opts.extraAction === 'function' && opts.extraActionLabel) {
            actions.push({
                label: String(opts.extraActionLabel),
                onClick: opts.extraAction,
            });
        }

        return toast({
            type: 'error',
            title: context || 'Action Failed',
            message,
            actions,
            durationMs: opts.persistent ? 0 : 8500,
        });
    }

    function installGlobalHandlers() {
        window.addEventListener('error', (event) => {
            const target = event && event.target;
            if (target && (target.tagName === 'IMG' || target.tagName === 'SCRIPT')) {
                return;
            }

            const message = extractMessage(event && event.error) || String(event.message || 'Unknown error');
            if (shouldIgnore(message)) return;
            toast({
                type: 'warning',
                title: 'Unhandled Error',
                message,
            });
        });

        window.addEventListener('unhandledrejection', (event) => {
            const message = extractMessage(event && event.reason);
            if (shouldIgnore(message)) return;
            toast({
                type: 'warning',
                title: 'Promise Rejection',
                message,
            });
        });
    }

    function normalizeType(type) {
        const t = String(type || 'info').toLowerCase();
        if (t === 'error' || t === 'warning') return t;
        return 'info';
    }

    function defaultTitle(type) {
        if (type === 'error') return 'Error';
        if (type === 'warning') return 'Warning';
        return 'Notice';
    }

    function extractMessage(error) {
        if (!error) return 'Unknown error';
        if (typeof error === 'string') return error;
        if (error instanceof Error) return error.message || error.name;
        if (typeof error.message === 'string') return error.message;
        return String(error);
    }

    function shouldIgnore(message) {
        const text = String(message || '').toLowerCase();
        return text.includes('script error') || text.includes('resizeobserver loop limit exceeded');
    }

    function renderCollectionState(container, options) {
        if (!container) return null;
        const opts = options || {};
        const type = String(opts.type || 'empty').toLowerCase();
        const message = String(opts.message || (type === 'loading' ? 'Loading...' : 'No data available'));
        const className = opts.className || `app-collection-state is-${type}`;

        container.innerHTML = '';

        if (container.tagName === 'TBODY') {
            const row = document.createElement('tr');
            row.className = 'app-collection-state-row';
            const cell = document.createElement('td');
            const columns = Number.isFinite(opts.columns) ? opts.columns : 1;
            cell.colSpan = Math.max(1, columns);
            const state = document.createElement('div');
            state.className = className;
            state.textContent = message;
            cell.appendChild(state);
            row.appendChild(cell);
            container.appendChild(row);
            return row;
        }

        const state = document.createElement('div');
        state.className = className;
        state.textContent = message;
        container.appendChild(state);
        return state;
    }

    function isOffline() {
        return typeof navigator !== 'undefined' && navigator.onLine === false;
    }

    function isTransientNetworkError(error) {
        const text = String(extractMessage(error) || '').toLowerCase();
        if (!text) return false;

        return text.includes('networkerror') ||
            text.includes('failed to fetch') ||
            text.includes('network request failed') ||
            text.includes('load failed') ||
            text.includes('err_network_io_suspended') ||
            text.includes('network io suspended') ||
            text.includes('the network connection was lost') ||
            text.includes('connection reset') ||
            text.includes('timeout');
    }

    function isTransientOrOffline(error) {
        return isOffline() || isTransientNetworkError(error);
    }

    function isNetworkError(message) {
        return isTransientNetworkError(message);
    }

    function isSettingsError(message) {
        const text = String(message || '').toLowerCase();
        return text.includes('permission') || text.includes('denied') || text.includes('dependency') || text.includes('tool');
    }

    return {
        init,
        toast,
        reportError,
        removeToast,
        renderCollectionState,
        isOffline,
        isTransientNetworkError,
        isTransientOrOffline,
    };
})();

window.showAppToast = function(title, message, type) {
    return AppFeedback.toast({
        title,
        message,
        type,
    });
};

window.reportActionableError = function(context, error, options) {
    return AppFeedback.reportError(context, error, options);
};

window.renderCollectionState = function(container, options) {
    return AppFeedback.renderCollectionState(container, options);
};

window.isOffline = function() {
    return AppFeedback.isOffline();
};

window.isTransientNetworkError = function(error) {
    return AppFeedback.isTransientNetworkError(error);
};

window.isTransientOrOffline = function(error) {
    return AppFeedback.isTransientOrOffline(error);
};

document.addEventListener('DOMContentLoaded', () => {
    AppFeedback.init();
});
