/** @odoo-module **/

import { registry } from "@web/core/registry";
import { _t } from "@web/core/l10n/translation";

/**
 * AI Studio - Profesyonel İnceleme Popup'ı
 * 
 * Session'ın tüm generation'larını sırayla gösterir:
 * - Ön → Arka → Yan → Detay
 * - Onayla/Reddet diyince otomatik sonrakine geçer
 * - Revize edilen görseller "Revize üretiliyor" ile gösterilir ve otomatik polling yapılır
 * - Tamamla Kaydet sadece pending revizyon yokken gösterilir
 */

async function _jsonRpc(url, params = {}) {
    const response = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ jsonrpc: "2.0", method: "call", params }),
    });
    const data = await response.json();
    if (data.error) {
        throw new Error(data.error.data?.message || data.error.message || "RPC Error");
    }
    return data.result;
}

function escapeHtml(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

function showToast(message, type = 'error') {
    // Odoo 19 tarzı bildirim — sağ üst köşede, stack halinde gösterilir
    const TOAST_TYPES = {
        success: { icon: '✅', bg: '#d1fae5', border: '#34d399', color: '#065f46', iconBg: '#a7f3d0' },
        error:   { icon: '⚠️', bg: '#fee2e2', border: '#f87171', color: '#991b1b', iconBg: '#fecaca' },
        warning: { icon: '⚡', bg: '#fef3c7', border: '#fbbf24', color: '#92400e', iconBg: '#fde68a' },
        info:    { icon: 'ℹ️', bg: '#dbeafe', border: '#60a5fa', color: '#1e40af', iconBg: '#bfdbfe' },
    };
    const t = TOAST_TYPES[type] || TOAST_TYPES.error;

    // Container — sağ üst köşede sabit, yeni bildirimler alta eklenir
    let container = document.getElementById('ais-toast-container');
    if (!container) {
        container = document.createElement('div');
        container.id = 'ais-toast-container';
        container.style.cssText = `
            position: fixed;
            top: 10px;
            right: 10px;
            z-index: 2147483647;
            display: flex;
            flex-direction: column;
            gap: 8px;
            pointer-events: none;
            max-width: 420px;
            width: 100%;
        `;
        document.body.appendChild(container);
    }

    const toast = document.createElement('div');
    toast.style.cssText = `
        display: flex;
        align-items: flex-start;
        gap: 10px;
        padding: 12px 14px;
        background: ${t.bg};
        border: 1px solid ${t.border};
        border-left: 4px solid ${t.border};
        border-radius: 6px;
        color: ${t.color};
        font-size: 13px;
        font-weight: 500;
        line-height: 1.45;
        box-shadow: 0 4px 12px rgba(0,0,0,0.08), 0 1px 3px rgba(0,0,0,0.06);
        pointer-events: auto;
        opacity: 0;
        transform: translateX(30px);
        transition: opacity 0.25s ease, transform 0.3s cubic-bezier(0.175,0.885,0.32,1.275);
        word-break: break-word;
    `;
    toast.innerHTML = `
        <span style="
            flex-shrink: 0;
            width: 26px; height: 26px;
            display: flex; align-items: center; justify-content: center;
            background: ${t.iconBg};
            border-radius: 50%;
            font-size: 14px;
        ">${t.icon}</span>
        <span style="flex:1; padding-top:3px;">${message}</span>
        <button style="
            flex-shrink: 0;
            background: none; border: none;
            color: ${t.color}; opacity: 0.5;
            cursor: pointer; font-size: 16px;
            padding: 0 2px; line-height: 1;
        " onclick="this.parentElement.style.opacity='0';this.parentElement.style.transform='translateX(30px)';setTimeout(()=>this.parentElement.remove(),250);" aria-label="Kapat">✕</button>
    `;
    container.appendChild(toast);

    requestAnimationFrame(() => {
        toast.style.opacity = '1';
        toast.style.transform = 'translateX(0)';
    });

    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transform = 'translateX(30px)';
        setTimeout(() => toast.remove(), 300);
    }, 4000);
}

async function openReviewPopup(initialSessionId) {
    // Unique lock token for this specific popup window (let: sonraki session geçişinde güncellenebilir)
    let sessionId = initialSessionId;
    let lockToken = 'lock_' + (crypto.randomUUID ? crypto.randomUUID().replace(/-/g, '').substring(0, 16) : Math.random().toString(36).substring(2) + Date.now().toString(36));

    // ═══ KİLİT KONTROLÜ ═══
    const lockResult = await _jsonRpc('/ai_studio/acquire_lock', { session_id: sessionId, lock_token: lockToken });
    if (!lockResult.success) {
        if (lockResult.locked) {
            showToast(
                `⚠️ Bu oturum şu an ${escapeHtml(lockResult.locked_by_name)} tarafından inceleniyor (${lockResult.lock_duration}). ` +
                `Lütfen tamamlamasını bekleyin veya 5dk sonra otomatik açılacak.`,
                'error'
            );
            return;
        }
        if (lockResult.error) {
            showToast('Kilit hatası: ' + lockResult.error);
            return;
        }
    }

    // Veriyi çek
    const data = await _jsonRpc('/ai_studio/review_data', { session_id: sessionId, lock_token: lockToken });
    if (data.error) {
        await _jsonRpc('/ai_studio/release_lock', { session_id: sessionId, lock_token: lockToken });
        showToast(data.error);
        return;
    }
    if (!data.items || data.items.length === 0) {
        await _jsonRpc('/ai_studio/release_lock', { session_id: sessionId, lock_token: lockToken });
        showToast(_t('İncelenecek görsel bulunamadı.'));
        return;
    }

    let currentIndex = 0;
    let items = data.items;
    const rejectReasons = data.reject_reasons || [];
    let showRejectModal = false;
    let selectedReasonId = null;
    let revisionPrompt = '';
    let revisionPromptEn = '';
    const userRole = data.user_role || 'operator';
    const canApprove = (userRole === 'reviewer' || userRole === 'manager');
    let revisionPollTimer = null;
    let heartbeatTimer = null;

    // ═══ HEARTBEAT — her 2dk'da kilidi canlı tut ═══
    heartbeatTimer = setInterval(async () => {
        try {
            await _jsonRpc('/ai_studio/heartbeat_lock', { session_id: sessionId, lock_token: lockToken });
        } catch(e) {
            console.error('Heartbeat error:', e);
        }
    }, 120000); // 2 dakika

    // Overlay oluştur
    const overlay = document.createElement('div');
    overlay.className = 'ais-review-overlay';
    document.body.appendChild(overlay);

    // MutationObserver: Overlay dışarıdan DOM'dan kaldırılırsa (Odoo navigation, vb.)
    // setInterval timer'larını otomatik temizle
    const _overlayObserver = new MutationObserver((mutations) => {
        for (const m of mutations) {
            for (const removed of m.removedNodes) {
                if (removed === overlay || (removed.contains && removed.contains(overlay))) {
                    _overlayObserver.disconnect();
                    if (revisionPollTimer) { clearInterval(revisionPollTimer); revisionPollTimer = null; }
                    if (heartbeatTimer) { clearInterval(heartbeatTimer); heartbeatTimer = null; }
                    window.removeEventListener('beforeunload', window._aisBeforeUnload);
                    _jsonRpc('/ai_studio/release_lock', { session_id: sessionId, lock_token: lockToken }).catch(() => {});
                    return;
                }
            }
        }
    });
    _overlayObserver.observe(document.body, { childList: true, subtree: true });

    function getPhotoTypeIcon(type) {
        switch(type) {
            case 'front': return '👔';
            case 'back': return '🔙';
            case 'side': return '↔️';
            case 'detail': return '🔍';
            default: return '📷';
        }
    }

    function render() {
        const item = items[currentIndex];
        if (!item) return;

        const activeItems = items.filter(i => !i.is_excluded);
        const excludedCount = items.filter(i => i.is_excluded).length;
        const approvedCount = items.filter(i => i.is_approved && !i.is_excluded).length;
        const pendingCount = items.filter(i => i.pending_revision && !i.is_excluded).length;
        const failedCount = items.filter(i => i.state === 'failed' && !i.is_excluded).length;
        const totalCount = items.length;
        const hasPending = pendingCount > 0;
        const hasFailed = failedCount > 0;
        const canComplete = canApprove && approvedCount > 0 && !hasPending && !hasFailed;

        // Progress text
        let progressText = `${approvedCount}/${activeItems.length} onaylandı`;
        if (excludedCount > 0) {
            progressText += ` · 🚫 ${excludedCount} hariç`;
        }
        if (hasPending) {
            progressText += ` · ⏳ ${pendingCount} revize bekleniyor`;
        }
        if (hasFailed) {
            progressText += ` · ❌ ${failedCount} başarısız`;
        }

        const hasPrimaryImage = items.some(i => i.is_primary);
        const showStarBtn = !hasPrimaryImage || item.is_primary;

        overlay.innerHTML = `
            <div class="ais-rp" onclick="event.stopPropagation()">
                <!-- Header -->
                <div class="ais-rp-header">
                    <div class="ais-rp-title-area">
                        <h2 class="ais-rp-title">🖼️ Görsel İnceleme</h2>
                        <div class="ais-rp-subtitle">${escapeHtml(data.product_name) || escapeHtml(data.session_name)}</div>
                    </div>
                    <div class="ais-rp-progress">
                        <div class="ais-rp-progress-bar">
                            <div class="ais-rp-progress-fill" style="width: ${(activeItems.length > 0 ? (approvedCount / activeItems.length) : 0) * 100}%"></div>
                        </div>
                        <span class="ais-rp-progress-text">${progressText}</span>
                    </div>
                    <button class="ais-rp-close" id="ais-rp-close" aria-label="Kapat">✕</button>
                </div>

                <!-- Tabs & Session Badge -->
                <div class="ais-rp-tabs-container">
                    <div class="ais-rp-tabs">
                        ${items.map((it, idx) => `
                            <button class="ais-rp-tab ${idx === currentIndex ? 'active' : ''} ${it.is_approved ? 'approved' : ''} ${it.pending_revision ? 'pending' : ''} ${it.is_excluded ? 'excluded' : ''}"
                                    data-idx="${idx}">
                                <span class="ais-rp-tab-icon">${getPhotoTypeIcon(it.photo_type)}</span>
                                <span class="ais-rp-tab-label ${it.is_excluded ? 'ais-rp-strikethrough' : ''}">${escapeHtml(it.photo_type_label)}</span>
                                ${it.is_approved && !it.is_excluded ? '<span class="ais-rp-tab-check">✓</span>' : ''}
                                ${it.is_excluded ? '<span class="ais-rp-tab-check" style="color:#9ca3af">🚫</span>' : ''}
                                ${it.pending_revision && !it.is_excluded ? '<span class="ais-rp-tab-check" style="color:#f59e0b">⏳</span>' : ''}
                                ${it.state === 'failed' && !it.is_excluded ? '<span class="ais-rp-tab-check" style="color:#ef4444">✗</span>' : ''}
                                ${it.revision_number > 1 ? '<span class="ais-rp-tab-version">v' + it.revision_number + '</span>' : ''}
                            </button>
                        `).join('')}
                    </div>
                    <div class="ais-rp-session-badge" id="ais-rp-copy-session-btn" title="Tıklayıp Oturum Numarasını Kopyalayın">
                        <span class="ais-rp-sb-icon">📋</span>
                        <span class="ais-rp-sb-text">${escapeHtml(data.session_name)}</span>
                        <span class="ais-rp-sb-copy-hint">Kopyala</span>
                    </div>
                </div>

                <!-- İçerik -->
                <div class="ais-rp-content">
                    ${item.pending_revision ? `
                        <!-- Revize Bekleniyor Ekranı -->
                        <div class="ais-rp-pending-revision">
                            <div class="ais-rp-pending-icon">⏳</div>
                            <h3>Revize Üretiliyor...</h3>
                            <p>Bu görsel reddedildi ve yeni versiyon AI tarafından üretiliyor.</p>
                            <p class="ais-rp-pending-hint">Hazır olduğunda otomatik olarak yüklenecek.</p>
                            <div class="ais-rp-pending-spinner"></div>
                            ${canApprove ? `
                                <button class="ais-rp-btn" id="ais-rp-cancel-revision" style="margin-top:20px; background:#ef4444; border-color:#ef4444; font-size:13px; padding:6px 12px;">
                                    🛑 İptal Et & Geri Dön
                                </button>
                            ` : ''}
                        </div>
                    ` : item.state === 'failed' ? `
                        <!-- Başarısız Ekranı -->
                        <div class="ais-rp-pending-revision">
                            <div class="ais-rp-pending-icon" style="color:#ef4444">❌</div>
                            <h3 style="color:#ef4444">Üretim Başarısız Oldu</h3>
                            <p style="color:#9ca3af; max-width:500px; text-align:center;">${escapeHtml(item.error_message) || 'Bilinmeyen bir hata oluştu.'}</p>
                            ${canApprove ? `
                                <div style="display:flex; gap:10px; justify-content:center; align-items:center; margin-top:20px; flex-wrap:wrap;">
                                    <button class="ais-rp-btn ais-rp-btn-approve" id="ais-rp-retry" style="background:#f59e0b;">
                                        🔄 Tekrar Dene
                                    </button>
                                    <button class="ais-rp-btn ais-rp-btn-exclude" id="ais-rp-toggle-exclude" style="background:#6b7280; color:white;" title="Bu yönü ürüne kaydetme">
                                        🚫 Dahil Etme
                                    </button>
                                    ${item.revision_number > 1 ? `
                                        <button class="ais-rp-btn" id="ais-rp-cancel-revision" style="background:#6b7280; border-color:#6b7280;">
                                            🛑 Revizyonu İptal Et &amp; Geri Dön
                                        </button>
                                    ` : ''}
                                </div>
                            ` : `
                                <p style="color:#6b7280; margin-top:10px;">Onaycının tekrar denemesi bekleniyor.</p>
                            `}
                        </div>
                    ` : `
                        <!-- Yan yana görseller -->
                        <div class="ais-rp-comparison ${item.is_excluded ? 'ais-rp-comparison-excluded' : ''}">
                            <div class="ais-rp-panel">
                                <div class="ais-rp-panel-label">ORJİNAL</div>
                                <div class="ais-rp-img-wrap ais-rp-zoomable" data-zoom-src="${item.original_url_full}">
                                    <img src="${item.original_url}" class="ais-rp-img" alt="Orijinal"/>
                                </div>
                            </div>
                            <div class="ais-rp-vs">VS</div>
                            <div class="ais-rp-panel">
                                <div class="ais-rp-panel-label ais-rp-ai-label">AI SONUÇ</div>
                                <div class="ais-rp-img-wrap ais-rp-zoomable" data-zoom-src="${item.generated_url_full}">
                                    <img src="${item.generated_url}" class="ais-rp-img" alt="AI Sonucu"/>
                                </div>
                            </div>
                        </div>
                    `}
                </div>

                <!-- Alt butonlar -->
                <div class="ais-rp-footer">
                    <div class="ais-rp-actions">
                        ${item.is_excluded ? `
                            <div class="ais-rp-pending-badge" style="background:#f3f4f6; color:#4b5563; border:1px solid #d1d5db;">🚫 Bu yön ürüne kaydedilirken hariç tutulacak</div>
                            ${canApprove ? `
                                <button class="ais-rp-btn ais-rp-btn-include" id="ais-rp-toggle-exclude" style="background:#4b5563; color:white;">
                                    ✅ Tekrar Dahil Et
                                </button>
                            ` : ''}
                        ` : item.pending_revision ? `
                            <div class="ais-rp-pending-badge">⏳ Revize üretiliyor — diğer görselleri inceleyebilirsiniz</div>
                        ` : item.state === 'failed' ? `
                            <div class="ais-rp-pending-badge" style="background:rgba(239,68,68,0.15); color:#ef4444;">❌ Bu görsel başarısız oldu${canApprove ? ' — Tekrar Dene veya Dahil Etme butonunu kullanın' : ''}</div>
                        ` : !canApprove ? `
                            <div class="ais-rp-operator-badge">
                                📷 Görüntüleme Modu — Onay yetkisi için onaycı rolü gerekli
                            </div>
                        ` : item.is_approved ? `
                            <div class="ais-rp-approved-badge">✅ Bu görsel onaylandı</div>
                            ${showStarBtn ? `
                            <button class="ais-rp-btn ais-rp-btn-star ${item.is_primary ? 'active' : ''}" id="ais-rp-star">
                                ⭐ Ana Görsel
                            </button>
                            ` : ''}
                            <button class="ais-rp-btn ais-rp-btn-unapprove" id="ais-rp-unapprove" style="background:#f59e0b; color:white;">
                                ↩️ Onayı Geri Al
                            </button>
                            <button class="ais-rp-btn ais-rp-btn-exclude" id="ais-rp-toggle-exclude" style="background:#6b7280; color:white;" title="Bu yönü ürüne kaydetme">
                                🚫 Dahil Etme
                            </button>
                        ` : `
                            <button class="ais-rp-btn ais-rp-btn-reject" id="ais-rp-reject" aria-label="Reddet">
                                ❌ Reddet
                            </button>
                            ${showStarBtn ? `
                            <button class="ais-rp-btn ais-rp-btn-star ${item.is_primary ? 'active' : ''}" id="ais-rp-star">
                                ⭐ Ana Görsel
                            </button>
                            ` : ''}
                            <button class="ais-rp-btn ais-rp-btn-approve" id="ais-rp-approve" aria-label="Onayla">
                                ✅ Onayla
                            </button>
                            <button class="ais-rp-btn ais-rp-btn-exclude" id="ais-rp-toggle-exclude" style="background:#6b7280; color:white;" title="Bu yönü ürüne kaydetme">
                                🚫 Dahil Etme
                            </button>
                        `}
                    </div>
                    <div class="ais-rp-nav">
                        ${currentIndex > 0 ? '<button class="ais-rp-btn ais-rp-btn-nav" id="ais-rp-prev">← Önceki</button>' : ''}
                        <span class="ais-rp-nav-info">${currentIndex + 1} / ${totalCount}</span>
                        ${currentIndex < totalCount - 1 ? '<button class="ais-rp-btn ais-rp-btn-nav" id="ais-rp-next">Sonraki →</button>' : ''}
                    </div>
                    ${canComplete ? `
                        <button class="ais-rp-btn ais-rp-btn-complete" id="ais-rp-complete">
                            ✅ Tamamla ve Kaydet (${approvedCount} görsel)
                        </button>
                    ` : ''}
                    ${canApprove && hasPending && approvedCount > 0 ? `
                        <div class="ais-rp-pending-warning">
                            ⏳ ${pendingCount} revize tamamlanınca "Tamamla ve Kaydet" aktif olacak
                        </div>
                    ` : ''}
                </div>
            </div>

            ${showRejectModal ? `
                <div class="ais-rp-modal-bg" id="ais-rp-modal-bg">
                    <div class="ais-rp-modal" onclick="event.stopPropagation()">
                        <div class="ais-rp-modal-header">
                            <h3>❌ Red Sebebi</h3>
                            <button class="ais-rp-modal-close" id="ais-rp-modal-close" aria-label="Kapat">✕</button>
                        </div>
                        <div class="ais-rp-modal-body">
                            ${rejectReasons.map(r => `
                                <label class="ais-rp-reason ${selectedReasonId === r.id ? 'selected' : ''}" data-reason-id="${r.id}">
                                    <input type="radio" name="reason" ${selectedReasonId === r.id ? 'checked' : ''}/>
                                    ${escapeHtml(r.name)}
                                </label>
                            `).join('')}
                            <textarea class="ais-rp-textarea" id="ais-rp-revision-prompt" 
                                      placeholder="Ek revizyon talimatı yazın (Türkçe)...">${escapeHtml(revisionPrompt)}</textarea>
                            <div class="ais-rp-en-label" style="margin-top:8px; font-size:12px; color:#9ca3af; display:flex; align-items:center; gap:4px;">
                                <span>🔤</span> İngilizce Çeviri (AI modeline bu gönderilir):
                            </div>
                            <textarea class="ais-rp-textarea ais-rp-textarea-en" id="ais-rp-revision-prompt-en" 
                                      readonly
                                      style="background:#f3f4f6; color:#374151; border:1px solid #d1d5db; font-style:italic; min-height:50px;"
                                      placeholder="Türkçe yazdığınızda otomatik çevrilecek...">${escapeHtml(revisionPromptEn)}</textarea>
                        </div>
                        <div class="ais-rp-modal-footer">
                            <button class="ais-rp-btn ais-rp-btn-reject" id="ais-rp-submit-reject">
                                🔄 Reddet ve Yeni Üret
                            </button>
                        </div>
                    </div>
                </div>
            ` : ''}
        `;

        // Event handlers
        document.getElementById('ais-rp-close')?.addEventListener('click', close);
        document.getElementById('ais-rp-approve')?.addEventListener('click', approve);
        document.getElementById('ais-rp-unapprove')?.addEventListener('click', unapprove);
        document.getElementById('ais-rp-toggle-exclude')?.addEventListener('click', toggleExclude);
        document.getElementById('ais-rp-star')?.addEventListener('click', () => {
            // Önce tüm item'ların primary'sini kaldır, sonra bu item'ı toggle yap
            const wasPrimary = items[currentIndex].is_primary;
            items.forEach(it => it.is_primary = false);
            items[currentIndex].is_primary = !wasPrimary;
            render();
        });
        document.getElementById('ais-rp-reject')?.addEventListener('click', () => {
            showRejectModal = true;
            selectedReasonId = rejectReasons.length > 0 ? rejectReasons[0].id : null;
            render();
        });
        document.getElementById('ais-rp-prev')?.addEventListener('click', () => { currentIndex--; render(); });
        document.getElementById('ais-rp-next')?.addEventListener('click', () => { currentIndex++; render(); });
        document.getElementById('ais-rp-complete')?.addEventListener('click', complete);
        document.getElementById('ais-rp-modal-bg')?.addEventListener('click', () => { showRejectModal = false; render(); });
        document.getElementById('ais-rp-modal-close')?.addEventListener('click', () => { showRejectModal = false; render(); });
        document.getElementById('ais-rp-submit-reject')?.addEventListener('click', submitReject);
        document.getElementById('ais-rp-retry')?.addEventListener('click', retryFailed);

        // Oturum Numarası Kopyalama
        document.getElementById('ais-rp-copy-session-btn')?.addEventListener('click', async () => {
            const sessionName = data.session_name;
            if (!sessionName) return;
            try {
                if (navigator.clipboard && window.isSecureContext) {
                    await navigator.clipboard.writeText(sessionName);
                } else {
                    const tempInput = document.createElement('input');
                    tempInput.value = sessionName;
                    document.body.appendChild(tempInput);
                    tempInput.select();
                    document.execCommand('copy');
                    document.body.removeChild(tempInput);
                }
                const btn = document.getElementById('ais-rp-copy-session-btn');
                if (btn) {
                    btn.classList.add('copied');
                    const hint = btn.querySelector('.ais-rp-sb-copy-hint');
                    if (hint) hint.textContent = '✓ Kopyalandı!';
                    setTimeout(() => {
                        btn.classList.remove('copied');
                        if (hint) hint.textContent = 'Kopyala';
                    }, 2000);
                }
                showToast(`📋 Oturum No kopyalandı: ${sessionName}`, 'success');
            } catch (err) {
                console.error('Kopyalama hatasi:', err);
                showToast(`Oturum No: ${sessionName}`, 'success');
            }
        });

        // Metin yazılırken ana değişkene anlık kaydet (polling render'ında silinmesin)
        const promptInput = document.getElementById('ais-rp-revision-prompt');
        if (promptInput) {
            let translateTimer = null;
            promptInput.addEventListener('input', (e) => {
                revisionPrompt = e.target.value;
                // Debounce: 800ms sonra çeviri yap
                if (translateTimer) clearTimeout(translateTimer);
                if (!revisionPrompt.trim()) {
                    revisionPromptEn = '';
                    const enEl = document.getElementById('ais-rp-revision-prompt-en');
                    if (enEl) enEl.value = '';
                    return;
                }
                translateTimer = setTimeout(async () => {
                    try {
                        const enEl = document.getElementById('ais-rp-revision-prompt-en');
                        if (enEl) enEl.value = '⏳ Çevriliyor...';
                        const result = await _jsonRpc('/ai_studio/translate_revision', {
                            text: revisionPrompt,
                        });
                        if (result && result.translated) {
                            revisionPromptEn = result.translated;
                            const enEl2 = document.getElementById('ais-rp-revision-prompt-en');
                            if (enEl2) enEl2.value = revisionPromptEn;
                        }
                    } catch (err) {
                        console.error('Translation error:', err);
                        revisionPromptEn = revisionPrompt;
                    }
                }, 800);
            });
        }
        
        // Revize İptal Butonu
        const cancelRevisionBtn = overlay.querySelector('#ais-rp-cancel-revision');
        if (cancelRevisionBtn) {
            cancelRevisionBtn.addEventListener('click', async () => {
                const item = items[currentIndex];
                cancelRevisionBtn.disabled = true;
                cancelRevisionBtn.textContent = 'İptal Ediliyor...';
                try {
                    const res = await _jsonRpc('/ai_studio/cancel_revision', {
                        generation_id: item.new_generation_id || item.id, // eger result'tan gelmisse new_generation_id, normal gelmisse id
                    });
                    if (res.error) {
                        showToast(res.error);
                    } else {
                        showToast(_t('Revize iptal edildi.'), 'success');
                    }
                    const freshData = await _jsonRpc('/ai_studio/review_data', { session_id: data.session_id });
                    if (!freshData.error && freshData.items) {
                        items = freshData.items;
                        render();
                    }
                } catch(e) {
                    showToast('İptal hatası: ' + e.message);
                }
            });
        }

        // Tab clicks
        overlay.querySelectorAll('.ais-rp-tab').forEach(tab => {
            tab.addEventListener('click', () => {
                currentIndex = parseInt(tab.dataset.idx);
                render();
            });
        });

        // Reason radio clicks
        overlay.querySelectorAll('.ais-rp-reason').forEach(el => {
            el.addEventListener('click', () => {
                selectedReasonId = parseInt(el.dataset.reasonId);
                render();
            });
        });

        // Zoom: Container-based zoom
        overlay.querySelectorAll('.ais-rp-zoomable').forEach(wrap => {
            const img = wrap.querySelector('.ais-rp-img');
            const zoomSrc = wrap.dataset.zoomSrc;
            if (!img) return;

            wrap.addEventListener('mouseenter', () => {
                wrap.style.backgroundImage = `url(${zoomSrc})`;
                wrap.style.backgroundSize = '250%';
                wrap.style.backgroundRepeat = 'no-repeat';
                img.style.opacity = '0';
            });

            wrap.addEventListener('mouseleave', () => {
                wrap.style.backgroundImage = 'none';
                img.style.opacity = '1';
            });

            wrap.addEventListener('mousemove', (e) => {
                const rect = wrap.getBoundingClientRect();
                const x = ((e.clientX - rect.left) / rect.width) * 100;
                const y = ((e.clientY - rect.top) / rect.height) * 100;
                wrap.style.backgroundPosition = `${x}% ${y}%`;
            });
        });
    }

    async function approve() {
        const item = items[currentIndex];
        const btn = document.getElementById('ais-rp-approve');
        if (btn) { btn.disabled = true; btn.textContent = '⏳...'; }

        try {
            await _jsonRpc('/ai_studio/approve_generation', {
                generation_id: item.id,
                is_primary: item.is_primary,
            });
            item.is_approved = true;

            // Sonraki onaylanmamış, revize beklenmeyen ve hariç tutulmamış görsele geç
            const nextIdx = items.findIndex((it, idx) => idx > currentIndex && !it.is_approved && !it.pending_revision && !it.is_excluded);
            if (nextIdx >= 0) {
                currentIndex = nextIdx;
            }
            render();
        } catch(e) {
            showToast('Onay hatası: ' + e.message);
            render();
        }
    }

    async function toggleExclude() {
        const item = items[currentIndex];
        const btn = document.getElementById('ais-rp-toggle-exclude');
        if (btn) { btn.disabled = true; btn.textContent = '⏳...'; }

        try {
            const res = await _jsonRpc('/ai_studio/toggle_exclude', {
                generation_id: item.id,
            });
            if (res.error) {
                showToast('Hata: ' + res.error);
                render();
                return;
            }
            item.is_excluded = res.is_excluded;
            if (item.is_excluded) {
                item.is_approved = false;
                item.is_primary = false;
                showToast(`🚫 ${item.photo_type_label} ürüne kaydedilirken hariç tutulacak.`, 'success');
                // Sonraki onaylanmamış ve hariç tutulmamış görsele geç
                const nextIdx = items.findIndex((it, idx) => idx > currentIndex && !it.is_approved && !it.pending_revision && !it.is_excluded);
                if (nextIdx >= 0) {
                    currentIndex = nextIdx;
                }
            } else {
                showToast(`✅ ${item.photo_type_label} tekrar dahil edildi.`, 'success');
            }
            render();
        } catch(e) {
            showToast('Hata: ' + e.message);
            render();
        }
    }

    async function unapprove() {
        const item = items[currentIndex];
        const btn = document.getElementById('ais-rp-unapprove');
        if (btn) { btn.disabled = true; btn.textContent = '⏳...'; }

        try {
            await _jsonRpc('/ai_studio/unapprove_generation', {
                generation_id: item.id,
            });
            item.is_approved = false;
            item.is_primary = false;
            render();
        } catch(e) {
            showToast('Onay geri alma hatası: ' + e.message);
            render();
        }
    }

    async function submitReject() {
        const item = items[currentIndex];
        const promptEl = document.getElementById('ais-rp-revision-prompt');
        revisionPrompt = promptEl ? promptEl.value : '';

        if (!selectedReasonId) {
            showToast(_t('Lütfen bir red sebebi seçin.'));
            return;
        }

        const btn = document.getElementById('ais-rp-submit-reject');
        if (btn) { btn.disabled = true; btn.textContent = '⏳...'; }

        try {
            const result = await _jsonRpc('/ai_studio/reject_generation', {
                generation_id: item.id,
                reason_id: selectedReasonId,
                revision_prompt: revisionPrompt,
                revision_prompt_en: revisionPromptEn || revisionPrompt,
            });

            showRejectModal = false;
            revisionPrompt = '';

            if (result.error) {
                showToast(result.error);
                render();
                return;
            }

            // Görseli "revize bekleniyor" durumuna al — listeden silmiyoruz!
            item.pending_revision = true;
            item.new_generation_id = result.new_generation_id;

            // Sonraki incelenmemiş görsele geç
            const nextIdx = items.findIndex((it, idx) => idx > currentIndex && !it.is_approved && !it.pending_revision);
            if (nextIdx >= 0) {
                currentIndex = nextIdx;
            }

            // Revizyon polling başlat
            startRevisionPolling();

            render();
        } catch(e) {
            showToast('Red hatası: ' + e.message);
            render();
        }
    }

    async function retryFailed() {
        const item = items[currentIndex];
        const btn = document.getElementById('ais-rp-retry');
        if (btn) { btn.disabled = true; btn.textContent = '⏳ Yeniden deneniyor...'; }

        try {
            const result = await _jsonRpc('/ai_studio/retry_generation', {
                generation_id: item.id,
            });

            if (result.error) {
                showToast(result.error);
                render();
                return;
            }

            // Başarılı — item'ı pending durumuna al
            item.state = 'pending';
            item.pending_revision = true;
            item.error_message = '';

            // Polling başlat
            startRevisionPolling();

            render();
        } catch(e) {
            showToast('Tekrar deneme hatası: ' + e.message);
            render();
        }
    }

    // Revizyon polling — pending olan görsellerin yeni versiyonlarını kontrol et
    function startRevisionPolling() {
        if (revisionPollTimer) return; // Zaten çalışıyor
        
        revisionPollTimer = setInterval(async () => {
            const pendingItems = items.filter(i => i.pending_revision);
            if (pendingItems.length === 0) {
                clearInterval(revisionPollTimer);
                revisionPollTimer = null;
                return;
            }

            try {
                // Session'ın güncel review verisini çek
                const freshData = await _jsonRpc('/ai_studio/review_data', { session_id: data.session_id });
                if (freshData.error || !freshData.items) return;

                let updated = false;

                for (const pendingItem of pendingItems) {
                    // Aynı photo_type veya aynı ID'nin güncel durumunu bul
                    // action_retry: aynı ID'yi tekrar kullanır (copy yapmaz)
                    // action_confirm_reject: yeni ID oluşturur
                    const freshVersion = freshData.items.find(fi =>
                        (fi.id === pendingItem.id && (fi.state === 'done' || fi.state === 'failed')) ||
                        (fi.photo_type === pendingItem.photo_type &&
                         fi.id !== pendingItem.id &&
                         !fi.is_approved &&
                         (fi.state === 'done' || fi.state === 'failed'))
                    );

                    if (freshVersion) {
                        const idx = items.indexOf(pendingItem);
                        if (idx >= 0) {
                            items[idx] = {
                                ...freshVersion,
                                pending_revision: false,
                            };
                            updated = true;
                        }
                    }
                }

                if (updated) {
                    // Hedefli DOM güncelleme: Eğer aktif tab'da değişiklik varsa
                    // tam render gerekir, değilse sadece tab badge'lerini güncelle
                    if (!showRejectModal) {
                        // Tab badge'lerini güncelle (tam render yerine)
                        const tabs = overlay.querySelectorAll('.ais-rp-tab');
                        let needFullRender = false;
                        tabs.forEach((tab, idx) => {
                            if (idx < items.length) {
                                const it = items[idx];
                                // Pending → Done geçişi varsa ve aktif tab ise tam render gerekli
                                if (idx === currentIndex && !it.pending_revision) {
                                    needFullRender = true;
                                }
                                // Tab class'larını güncelle
                                tab.className = `ais-rp-tab ${idx === currentIndex ? 'active' : ''} ${it.is_approved ? 'approved' : ''} ${it.pending_revision ? 'pending' : ''} ${it.is_excluded ? 'excluded' : ''}`;
                            }
                        });
                        if (needFullRender) {
                            render();
                        }
                    }
                }

                // Hala pending var mı kontrol et
                if (!items.some(i => i.pending_revision)) {
                    clearInterval(revisionPollTimer);
                    revisionPollTimer = null;
                }
            } catch (e) {
                console.error('Revision polling error:', e);
            }
        }, 5000); // 5 saniyede bir kontrol et
    }

    async function complete() {
        const approvedItems = items.filter(i => i.is_approved);
        if (approvedItems.length === 0) {
            showToast(_t('Lütfen en az bir görseli onaylayın!'), 'error');
            return;
        }

        // Eğer hiçbir görsel ana görsel olarak işaretlenmemişse otomatik olarak Ön Görseli (veya ilk onaylıyı) ana görsel yap
        if (!approvedItems.some(i => i.is_primary)) {
            const frontItem = approvedItems.find(i => i.photo_type === 'front') || approvedItems[0];
            frontItem.is_primary = true;
        }

        const btn = document.getElementById('ais-rp-complete');
        if (btn) { btn.disabled = true; btn.textContent = '⏳ Kaydediliyor...'; }

        const previousSessionName = data.session_name;
        const payload = {
            session_id: data.session_id,
            approved_items: approvedItems.map(i => ({ id: i.id, is_primary: i.is_primary }))
        };

        try {
            const result = await _jsonRpc('/ai_studio/complete_session', payload);

            // Sunucu hatası kontrolü — hem success:false hem de error key'i kontrol et
            if (!result || result.success === false || result.error) {
                const errorMsg = (result && (result.error || 'Bilinmeyen hata')) || 'Sunucu yanıt vermedi';
                showToast('❌ Kaydetme hatası: ' + errorMsg, 'error');
                if (btn) { btn.disabled = false; btn.textContent = `✅ Tamamla ve Kaydet (${approvedItems.length} görsel)`; }
                return;
            }

            // Eski session kilidini serbest bırak
            await _jsonRpc('/ai_studio/release_lock', { session_id: sessionId, lock_token: lockToken }).catch(() => {});

            // Sonraki review session var mı?
            if (data.next_session_id) {
                // Yeni session için kilit al
                const newLockToken = 'lock_' + Math.random().toString(36).substring(2) + Date.now().toString(36);
                const nextLock = await _jsonRpc('/ai_studio/acquire_lock', { session_id: data.next_session_id, lock_token: newLockToken }).catch(() => null);
                if (!nextLock || !nextLock.success) {
                    showToast(`✅ ${previousSessionName} başarıyla kaydedildi! Sonraki oturum kilitli veya erişilemiyor.`, 'success');
                    close();
                    window.location.reload();
                    return;
                }

                // Sonraki session'ı yükle
                currentIndex = 0;
                const nextData = await _jsonRpc('/ai_studio/review_data', { session_id: data.next_session_id, lock_token: newLockToken });
                if (nextData.error || !nextData.items || nextData.items.length === 0) {
                    showToast(`✅ ${previousSessionName} başarıyla kaydedildi! İncelenecek başka oturum yok.`, 'success');
                    await _jsonRpc('/ai_studio/release_lock', { session_id: data.next_session_id, lock_token: newLockToken }).catch(() => {});
                    close();
                    window.location.reload();
                    return;
                }
                // Closure değişkenlerini güncelle (heartbeat & close doğru session'ı hedeflesin)
                sessionId = data.next_session_id;
                lockToken = newLockToken;
                // Verileri güncelle
                data.session_id = nextData.session_id;
                data.session_name = nextData.session_name;
                data.product_name = nextData.product_name;
                data.next_session_id = nextData.next_session_id;
                data.reject_reasons = nextData.reject_reasons || rejectReasons;
                items = nextData.items;
                currentIndex = 0;
                showToast(`✅ ${previousSessionName} kaydedildi. Sıradaki oturuma geçildi (${nextData.session_name}).`, 'success');
                render();
            } else {
                showToast(`✅ ${previousSessionName} başarıyla kaydedildi!`, 'success');
                close();
                window.location.reload();
            }
        } catch(e) {
            showToast('❌ Kaydetme hatası: ' + e.message, 'error');
            if (btn) { btn.disabled = false; btn.textContent = `✅ Tamamla ve Kaydet (${approvedItems.length} görsel)`; }
        }
    }

    function close() {
        if (revisionPollTimer) {
            clearInterval(revisionPollTimer);
            revisionPollTimer = null;
        }
        if (heartbeatTimer) {
            clearInterval(heartbeatTimer);
            heartbeatTimer = null;
        }
        // ═══ MutationObserver temizle ═══
        _overlayObserver.disconnect();
        // ═══ KİLİDİ BIRAK ═══
        _jsonRpc('/ai_studio/release_lock', { session_id: sessionId, lock_token: lockToken }).catch(() => {});
        if (overlay.parentNode) overlay.parentNode.removeChild(overlay);
        // beforeunload temizle
        window.removeEventListener('beforeunload', window._aisBeforeUnload);
        if (typeof onKeyDown !== 'undefined') {
            document.removeEventListener('keydown', onKeyDown);
        }
    }

    // İlk render
    render();

    // ESC ve Yön tuşları ile kapat/gez
    const onKeyDown = (e) => {
        if (e.key === 'Escape') {
            if (showRejectModal) {
                showRejectModal = false;
                render();
            } else {
                close();
            }
        } else if (e.key === 'ArrowLeft') {
            if (currentIndex > 0) {
                currentIndex--;
                render();
            }
        } else if (e.key === 'ArrowRight') {
            const activeItems = items.filter(i => !i.is_excluded);
            if (currentIndex < items.length - 1) {
                currentIndex++;
                render();
            }
        }
    };
    document.addEventListener('keydown', onKeyDown);

    // Sayfa kapatılırken kilidi bırak
    const onBeforeUnload = () => {
        // navigator.sendBeacon ile senkron bırakma (sayfa kapanırken çalışır)
        const payload = JSON.stringify({
            jsonrpc: '2.0', method: 'call',
            params: { session_id: sessionId, lock_token: lockToken },
        });
        navigator.sendBeacon('/ai_studio/release_lock', new Blob([payload], { type: 'application/json' }));
    };
    window._aisBeforeUnload = onBeforeUnload;
    window.addEventListener('beforeunload', window._aisBeforeUnload);
}

// Client action olarak kaydet
registry.category("actions").add("ugurlar_ai_studio.review_popup", async (env, action) => {
    const sessionId = action.params?.session_id;
    if (!sessionId) {
        env.services.notification.add("Session ID bulunamadı.", { type: "danger", sticky: false });
        return;
    }
    await openReviewPopup(sessionId);
});
