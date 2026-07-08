/** @odoo-module **/

import { registry } from "@web/core/registry";

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

async function openReviewPopup(sessionId) {
    // Veriyi çek
    const data = await _jsonRpc('/ai_studio/review_data', { session_id: sessionId });
    if (data.error) {
        alert(data.error);
        return;
    }
    if (!data.items || data.items.length === 0) {
        alert('İncelenecek görsel bulunamadı.');
        return;
    }

    let currentIndex = 0;
    let items = data.items;
    const rejectReasons = data.reject_reasons || [];
    let showRejectModal = false;
    let selectedReasonId = null;
    let revisionPrompt = '';
    const userRole = data.user_role || 'operator';
    const canApprove = (userRole === 'reviewer' || userRole === 'manager');
    let revisionPollTimer = null;

    // Overlay oluştur
    const overlay = document.createElement('div');
    overlay.className = 'ais-review-overlay';
    document.body.appendChild(overlay);

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

        const approvedCount = items.filter(i => i.is_approved).length;
        const pendingCount = items.filter(i => i.pending_revision).length;
        const failedCount = items.filter(i => i.state === 'failed').length;
        const totalCount = items.length;
        const allResolved = items.every(i => i.is_approved || i.pending_revision === false || i.pending_revision === undefined);
        const hasPending = pendingCount > 0;
        const hasFailed = failedCount > 0;
        const canComplete = canApprove && approvedCount > 0 && !hasPending && !hasFailed;

        // Progress text
        let progressText = `${approvedCount}/${totalCount} onaylandı`;
        if (hasPending) {
            progressText += ` · ⏳ ${pendingCount} revize bekleniyor`;
        }
        if (hasFailed) {
            progressText += ` · ❌ ${failedCount} başarısız`;
        }

        overlay.innerHTML = `
            <div class="ais-rp" onclick="event.stopPropagation()">
                <!-- Header -->
                <div class="ais-rp-header">
                    <div class="ais-rp-title-area">
                        <h2 class="ais-rp-title">🖼️ Görsel İnceleme</h2>
                        <div class="ais-rp-subtitle">${data.product_name || data.session_name}</div>
                    </div>
                    <div class="ais-rp-progress">
                        <div class="ais-rp-progress-bar">
                            <div class="ais-rp-progress-fill" style="width: ${(approvedCount / totalCount) * 100}%"></div>
                        </div>
                        <span class="ais-rp-progress-text">${progressText}</span>
                    </div>
                    <button class="ais-rp-close" id="ais-rp-close">✕</button>
                </div>

                <!-- Tabs -->
                <div class="ais-rp-tabs">
                    ${items.map((it, idx) => `
                        <button class="ais-rp-tab ${idx === currentIndex ? 'active' : ''} ${it.is_approved ? 'approved' : ''} ${it.pending_revision ? 'pending' : ''}"
                                data-idx="${idx}">
                            <span class="ais-rp-tab-icon">${getPhotoTypeIcon(it.photo_type)}</span>
                            <span class="ais-rp-tab-label">${it.photo_type_label}</span>
                            ${it.is_approved ? '<span class="ais-rp-tab-check">✓</span>' : ''}
                            ${it.pending_revision ? '<span class="ais-rp-tab-check" style="color:#f59e0b">⏳</span>' : ''}
                            ${it.state === 'failed' ? '<span class="ais-rp-tab-check" style="color:#ef4444">✗</span>' : ''}
                            ${it.revision_number > 1 ? '<span class="ais-rp-tab-version">v' + it.revision_number + '</span>' : ''}
                        </button>
                    `).join('')}
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
                        </div>
                    ` : item.state === 'failed' ? `
                        <!-- Başarısız Ekranı -->
                        <div class="ais-rp-pending-revision">
                            <div class="ais-rp-pending-icon" style="color:#ef4444">❌</div>
                            <h3 style="color:#ef4444">Üretim Başarısız Oldu</h3>
                            <p style="color:#9ca3af; max-width:500px; text-align:center;">${item.error_message || 'Bilinmeyen bir hata oluştu.'}</p>
                            ${canApprove ? `
                                <button class="ais-rp-btn ais-rp-btn-approve" id="ais-rp-retry" style="margin-top:20px; background:#f59e0b;">
                                    🔄 Tekrar Dene
                                </button>
                            ` : `
                                <p style="color:#6b7280; margin-top:10px;">Onaycının tekrar denemesi bekleniyor.</p>
                            `}
                        </div>
                    ` : `
                        <!-- Yan yana görseller -->
                        <div class="ais-rp-comparison">
                            <div class="ais-rp-panel">
                                <div class="ais-rp-panel-label">ORJİNAL</div>
                                <div class="ais-rp-img-wrap ais-rp-zoomable" data-zoom-src="${item.original_url}">
                                    <img src="${item.original_url}" class="ais-rp-img" alt="Orijinal"/>
                                </div>
                            </div>
                            <div class="ais-rp-vs">VS</div>
                            <div class="ais-rp-panel">
                                <div class="ais-rp-panel-label ais-rp-ai-label">AI SONUÇ</div>
                                <div class="ais-rp-img-wrap ais-rp-zoomable" data-zoom-src="${item.generated_url}">
                                    <img src="${item.generated_url}" class="ais-rp-img" alt="AI Sonucu"/>
                                </div>
                            </div>
                        </div>
                    `}
                </div>

                <!-- Alt butonlar -->
                <div class="ais-rp-footer">
                    <div class="ais-rp-actions">
                        ${item.pending_revision ? `
                            <div class="ais-rp-pending-badge">⏳ Revize üretiliyor — diğer görselleri inceleyebilirsiniz</div>
                        ` : item.state === 'failed' ? `
                            <div class="ais-rp-pending-badge" style="background:rgba(239,68,68,0.15); color:#ef4444;">❌ Bu görsel başarısız oldu${canApprove ? ' — Tekrar Dene butonunu kullanın' : ''}</div>
                        ` : !canApprove ? `
                            <div class="ais-rp-operator-badge">
                                📷 Görüntüleme Modu — Onay yetkisi için onaycı rolü gerekli
                            </div>
                        ` : item.is_approved ? `
                            <div class="ais-rp-approved-badge">✅ Bu görsel onaylandı</div>
                            <button class="ais-rp-btn ais-rp-btn-star ${item.is_primary ? 'active' : ''}" id="ais-rp-star">
                                ⭐ Ana Görsel
                            </button>
                        ` : `
                            <button class="ais-rp-btn ais-rp-btn-reject" id="ais-rp-reject">
                                ❌ Reddet
                            </button>
                            <button class="ais-rp-btn ais-rp-btn-star ${item.is_primary ? 'active' : ''}" id="ais-rp-star">
                                ⭐ Ana Görsel
                            </button>
                            <button class="ais-rp-btn ais-rp-btn-approve" id="ais-rp-approve">
                                ✅ Onayla
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
                            <button class="ais-rp-modal-close" id="ais-rp-modal-close">✕</button>
                        </div>
                        <div class="ais-rp-modal-body">
                            ${rejectReasons.map(r => `
                                <label class="ais-rp-reason ${selectedReasonId === r.id ? 'selected' : ''}" data-reason-id="${r.id}">
                                    <input type="radio" name="reason" ${selectedReasonId === r.id ? 'checked' : ''}/>
                                    ${r.name}
                                </label>
                            `).join('')}
                            <textarea class="ais-rp-textarea" id="ais-rp-revision-prompt" 
                                      placeholder="Ek revizyon talimatı (opsiyonel)...">${revisionPrompt}</textarea>
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
        document.getElementById('ais-rp-star')?.addEventListener('click', () => {
            // Önce tüm item'ların primary'sini kaldır, sonra bu item'ı primary yap
            items.forEach(it => it.is_primary = false);
            items[currentIndex].is_primary = true;
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

            // Sonraki onaylanmamış ve revize beklenmeyen görsele geç
            const nextIdx = items.findIndex((it, idx) => idx > currentIndex && !it.is_approved && !it.pending_revision);
            if (nextIdx >= 0) {
                currentIndex = nextIdx;
            }
            render();
        } catch(e) {
            alert('Onay hatası: ' + e.message);
            render();
        }
    }

    async function submitReject() {
        const item = items[currentIndex];
        const promptEl = document.getElementById('ais-rp-revision-prompt');
        revisionPrompt = promptEl ? promptEl.value : '';

        if (!selectedReasonId) {
            alert('Lütfen bir red sebebi seçin.');
            return;
        }

        const btn = document.getElementById('ais-rp-submit-reject');
        if (btn) { btn.disabled = true; btn.textContent = '⏳...'; }

        try {
            const result = await _jsonRpc('/ai_studio/reject_generation', {
                generation_id: item.id,
                reason_id: selectedReasonId,
                revision_prompt: revisionPrompt,
            });

            showRejectModal = false;
            revisionPrompt = '';

            if (result.error) {
                alert(result.error);
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
            alert('Red hatası: ' + e.message);
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
                alert(result.error);
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
            alert('Tekrar deneme hatası: ' + e.message);
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
                    render();
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
        if (approvedItems.length > 0 && !approvedItems.some(i => i.is_primary)) {
            alert('Lütfen onayladığınız görsellerden birini "Ana Görsel" (yıldız ikonuna tıklayarak) olarak seçin!');
            return;
        }

        const btn = document.getElementById('ais-rp-complete');
        if (btn) { btn.disabled = true; btn.textContent = '⏳ Kaydediliyor...'; }

        try {
            await _jsonRpc('/ai_studio/complete_session', { session_id: data.session_id });

            // Sonraki review session var mı?
            if (data.next_session_id) {
                // Aynı popup'ta sonraki session'ı yükle
                currentIndex = 0;
                const nextData = await _jsonRpc('/ai_studio/review_data', { session_id: data.next_session_id });
                if (nextData.error || !nextData.items || nextData.items.length === 0) {
                    alert('✅ Tamamlandı! İncelenecek başka oturum yok.');
                    close();
                    window.location.reload();
                    return;
                }
                // Verileri güncelle
                data.session_id = nextData.session_id;
                data.session_name = nextData.session_name;
                data.product_name = nextData.product_name;
                data.next_session_id = nextData.next_session_id;
                data.reject_reasons = nextData.reject_reasons || rejectReasons;
                items = nextData.items;
                currentIndex = 0;
                render();
            } else {
                alert('✅ Tamamlandı! İncelenecek başka oturum yok.');
                close();
                window.location.reload();
            }
        } catch(e) {
            alert('Kaydetme hatası: ' + e.message);
            render();
        }
    }

    function close() {
        if (revisionPollTimer) {
            clearInterval(revisionPollTimer);
            revisionPollTimer = null;
        }
        if (overlay.parentNode) overlay.parentNode.removeChild(overlay);
    }

    // İlk render
    render();

    // ESC tuşu ile kapat
    const onKeyDown = (e) => {
        if (e.key === 'Escape') {
            if (showRejectModal) {
                showRejectModal = false;
                render();
            } else {
                close();
                document.removeEventListener('keydown', onKeyDown);
            }
        }
    };
    document.addEventListener('keydown', onKeyDown);
}

// Client action olarak kaydet
registry.category("actions").add("ugurlar_ai_studio.review_popup", async (env, action) => {
    const sessionId = action.params?.session_id;
    if (!sessionId) {
        env.services.notification.add("Session ID bulunamadı.", { type: "danger" });
        return;
    }
    await openReviewPopup(sessionId);
});
