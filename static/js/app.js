
const API = {
    getStatus: () => fetch('/api/status').then(r => r.json()),
    toggleService: () => fetch('/api/service/toggle', { method: 'POST' }).then(r => r.json()),
    getChannels: () => fetch('/api/channels').then(r => r.json()),
    addChannel: (ch) => fetch('/api/channels', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ channel: ch })
    }).then(r => r.json()),
    deleteChannel: (ch) => fetch(`/api/channels/${ch}`, { method: 'DELETE' }).then(r => r.json()),
    toggleChannel: (ch) => fetch(`/api/channels/toggle/${ch}`, { method: 'POST' }).then(r => r.json()),
    getRecordings: () => fetch('/api/recordings').then(r => r.json()),
    stopRecording: (ch) => fetch(`/api/recording/stop/${ch}`, { method: 'POST' }).then(r => r.json()),
    deleteRecording: (filename) => fetch(`/api/recording/${filename}`, { method: 'DELETE' }).then(r => r.json()),

    getSettings: () => fetch('/api/settings').then(r => r.json()),
    updateSettings: (data) => fetch('/api/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data)
    }).then(r => r.json()),

    // Auth
    initYoutubeAuth: (secrets) => fetch('/api/auth/youtube/init', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ client_secrets: secrets })
    }).then(r => r.json()),

    // Uploads
    uploadArchive: (filename, title) => fetch('/api/upload/archive', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ filename, title })
    }).then(r => r.json()),

    uploadYoutube: (data) => fetch('/api/upload/youtube', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data)
    }).then(r => r.json())
};

// Utils
const $ = (s) => document.querySelector(s);
const $$ = (s) => document.querySelectorAll(s);

function showToast(msg) {
    const el = $('#toast');
    el.textContent = msg;
    el.classList.remove('hidden');
    setTimeout(() => el.classList.add('hidden'), 3000);
}

// Navigation
function showView(viewId) {
    $$('.view-section').forEach(el => el.classList.remove('active'));
    $(`#view-${viewId}`).classList.add('active');

    // Clear active class from all nav items
    $$('.nav-item').forEach(el => el.classList.remove('active'));

    // Make sure we select all buttons associated with this view
    // Use data-target attribute for consistency
    const buttons = $$(`.nav-item[data-target="${viewId}"]`);
    buttons.forEach(el => el.classList.add('active'));

    // Auto-refresh logic
    if (viewId === 'recordings') {
        refreshRecordings();
        startPolling();
    } else {
        stopPolling();
    }

    if (viewId === 'settings') loadSettingsPage();
}

let pollInterval = null;
function startPolling() {
    if (pollInterval) return;
    pollInterval = setInterval(refreshRecordings, 2000); // Fast poll for upload progress
}
function stopPolling() {
    if (pollInterval) {
        clearInterval(pollInterval);
        pollInterval = null;
    }
}


// Service Status (Keep global poll independent of view)
async function updateServiceStatus() {
    const data = await API.getStatus();
    const dot = $('.status-dot');
    const text = $('.status-text');
    const btn = $('#toggle-service-btn');

    if (data.service_enabled) {
        dot.classList.add('active');
        text.textContent = "Serviço Ativo";
        btn.textContent = "Parar Serviço";
        btn.classList.add('btn-danger');
    } else {
        dot.classList.remove('active');
        text.textContent = "Serviço Parado";
        btn.textContent = "Iniciar";
        btn.classList.remove('btn-danger');
    }

    // Update Active Recordings List
    const list = $('#active-recordings-list');
    if (data.active_recordings.length > 0) {
        list.innerHTML = data.active_recordings.map(rec => `
            <li class="list-item">
                <div>
                    <strong>${rec.channel}</strong>
                    <br><small>${rec.filename}</small>
                </div>
                <button class="btn-secondary btn-danger" onclick="stopRec('${rec.channel}')">Parar</button>
            </li>
        `).join('');
    } else {
        list.innerHTML = '<div class="empty-state">Nenhuma gravação ativa.</div>';
    }
}

async function toggleService() {
    await API.toggleService();
    updateServiceStatus();
}

async function stopRec(channel) {
    if (confirm(`Parar gravação de ${channel}?`)) {
        await API.stopRecording(channel);
        showToast("Gravação parada.");
        updateServiceStatus();
    }
}

// Channels
async function loadChannels() {
    const channels = await API.getChannels();
    const list = $('#channels-list');

    list.innerHTML = channels.map(c => `
        <li class="list-item">
            <div style="display:flex; align-items:center; gap:0.5rem">
                <input type="checkbox" ${c.active ? 'checked' : ''} onchange="toggleChannelItem('${c.name}')">
                <span>${c.name}</span>
            </div>
            <button class="btn-icon" onclick="deleteChannelItem('${c.name}')"><i data-lucide="trash-2"></i></button>
        </li>
    `).join('');
    lucide.createIcons();
}

async function addChannel(e) {
    e.preventDefault();
    const input = $('#new-channel-input');
    const val = input.value;
    if (!val) return;

    const name = val.split('twitch.tv/').pop().split('/')[0];

    await API.addChannel(name);
    input.value = '';
    loadChannels();
    showToast("Canal adicionado!");
}

async function deleteChannelItem(name) {
    if (confirm(`Remover ${name}?`)) {
        await API.deleteChannel(name);
        loadChannels();
    }
}

async function toggleChannelItem(name) {
    await API.toggleChannel(name);
}

// Recordings
async function refreshRecordings() {
    // Check if user is scrolling or hovering? Maybe just brute force replace for now
    const data = await API.getRecordings();
    const grid = $('#recordings-grid');

    if (data.length === 0) {
        grid.innerHTML = '<p>Nenhuma gravação encontrada.</p>';
        return;
    }

    // Smart Diffing could be here, but full replace is easier for now
    grid.innerHTML = data.map(rec => {
        let actionHtml = '';
        let statusHtml = '';

        if (rec.upload_status) {
            // UPLOADING
            const pct = rec.upload_status.progress || 0;
            const target = rec.upload_status.target;

            statusHtml = `
                <div class="upload-status">
                    <div class="upload-info">
                        <div style="display:flex; gap:0.5rem; align-items:center;">
                            <div class="loading-spinner"></div>
                            <span>Enviando para ${target}...</span>
                        </div>
                        <span style="font-weight:bold;">${pct}%</span>
                    </div>
                    <div class="progress-container">
                        <div class="progress-fill" style="width: ${pct}%"></div>
                    </div>
                </div>
            `;
            actionHtml = `
                <a href="${rec.url}" download class="btn-icon"><i data-lucide="download"></i></a>
                <button class="btn-icon" disabled title="Upload em andamento"><i data-lucide="upload-cloud"></i></button>
                <button class="btn-icon" disabled title="Aguarde o upload terminar"><i data-lucide="trash"></i></button>
            `;
        } else {
            // NORMAL
            actionHtml = `
                <a href="${rec.url}" download class="btn-icon"><i data-lucide="download"></i></a>
                <button class="btn-icon" onclick="openUploadModal('${rec.filename}')"><i data-lucide="upload-cloud"></i></button>
                <button class="btn-icon" onclick="deleteRec('${rec.filename}')"><i data-lucide="trash"></i></button>
            `;
        }

        return `
        <div class="rec-card ${rec.is_active ? 'recording' : ''}">
            <div class="rec-thumb-container">
                ${rec.thumbnail
                ? `<img src="${rec.thumbnail}" class="rec-thumb-img" loading="lazy" alt="${rec.filename}">`
                : `<div class="rec-icon-placeholder"><i data-lucide="video" style="width:48px; height:48px;"></i></div>`
            }
            </div>
            <div class="rec-info">
                <div class="rec-title" title="${rec.filename}">${rec.filename}</div>
                <div class="rec-meta">
                    <span>${rec.size_mb} MB</span>
                    <span>${rec.date}</span>
                </div>
            </div>
            ${statusHtml}
            <div class="rec-actions">
                ${actionHtml}
            </div>
        </div>
        `;
    }).join('');
    lucide.createIcons();
}

async function deleteRec(filename) {
    if (confirm(`Excluir ${filename}?`)) {
        const res = await API.deleteRecording(filename);
        if (res.error) {
            alert(res.error);
        } else {
            showToast("Arquivo excluído.");
            refreshRecordings();
        }
    }
}

// --- Upload Modal Logic ---
let currentUploadFile = null;

function openUploadModal(filename) {
    currentUploadFile = filename;
    $('#modal-filename').textContent = filename;
    $('#upload-title-archive').value = filename;
    $('#upload-title-yt').value = filename;
    $('#upload-modal').classList.add('open');
    toggleUploadFields();
}

function closeModal() {
    $('#upload-modal').classList.remove('open');
    currentUploadFile = null;
}

function toggleUploadFields() {
    const target = $('#upload-target').value;
    if (target === 'archive') {
        $('#fields-archive').style.display = 'block';
        $('#fields-youtube').style.display = 'none';
    } else {
        $('#fields-archive').style.display = 'none';
        $('#fields-youtube').style.display = 'block';
    }
}

async function submitUpload() {
    if (!currentUploadFile) return;

    // Capture file before closing modal clears it
    const fileToUpload = currentUploadFile;
    const target = $('#upload-target').value;

    showToast("Iniciando upload (em segundo plano)...");
    closeModal();

    // Trigger update immediately to show progress spinner
    refreshRecordings();

    if (target === 'archive') {
        const title = $('#upload-title-archive').value;
        const res = await API.uploadArchive(fileToUpload, title);
        if (res.status === 'success') {
            alert("Upload Concluído: " + res.message);
        } else {
            alert("Erro no Upload: " + res.error);
        }
    } else {
        // YouTube
        const data = {
            filename: fileToUpload,
            title: $('#upload-title-yt').value,
            description: $('#upload-desc-yt').value,
            privacy: $('#upload-privacy-yt').value
        };
        const res = await API.uploadYoutube(data);
        if (res.status === 'success') {
            alert("Upload YouTube Concluído: " + res.message);
        } else {
            alert("Erro YouTube: " + res.error);
        }
    }
    refreshRecordings(); // Clear status
}


// Settings
async function loadSettingsPage() {
    const s = await API.getSettings();
    $('#setting-interval').value = s.check_interval || 15;
    $('#setting-format').value = s.recording_format || 'mp4';

    if (s.upload_targets) {
        if (s.upload_targets.archive) {
            $('#setting-archive-access').value = s.upload_targets.archive.access_key || '';
            $('#setting-archive-secret').value = s.upload_targets.archive.secret_key || '';
        }
        if (s.upload_targets.youtube) {
            const yt = s.upload_targets.youtube;
            $('#setting-yt-secrets').value = yt.client_secrets || '';

            if (yt.token) {
                $('#yt-auth-status').textContent = "✅ Token Válido";
                $('#yt-auth-status').style.color = "var(--success)";
            }
        }
    }
}

async function initYouTubeAuth() {
    const secrets = $('#setting-yt-secrets').value;
    if (!secrets) {
        alert("Cole o JSON do Client Secrets primeiro.");
        return;
    }

    // Save locally first just in case
    await saveSettings();

    const res = await API.initYoutubeAuth(secrets);
    if (res.auth_url) {
        window.open(res.auth_url, '_blank');
        showToast("Janela de autenticação aberta.");
    } else {
        alert("Erro: " + res.error);
    }
}

async function saveSettings() {
    const data = {
        check_interval: $('#setting-interval').value,
        recording_format: $('#setting-format').value,
        upload_targets: {
            archive: {
                access_key: $('#setting-archive-access').value,
                secret_key: $('#setting-archive-secret').value
            },
            youtube: {
                client_secrets: $('#setting-yt-secrets').value
            }
        }
    };

    await API.updateSettings(data);
    showToast("Configurações salvas!");
    loadSettingsPage(); // Refresh UI state
}

// Init
setInterval(updateServiceStatus, 2000);
updateServiceStatus();
loadChannels();

