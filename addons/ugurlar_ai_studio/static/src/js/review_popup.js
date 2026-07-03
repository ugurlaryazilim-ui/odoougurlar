/** @odoo-module **/

import { registry } from "@web/core/registry";

/**
 * AI Studio - Profesyonel İnceleme Popup'ı
 * 
 * Session'ın tüm generation'larını sırayla gösterir:
 * - Ön → Arka → Yan → Detay
 * - Onayla/Reddet diyince otomatik sonrakine geçer
 * - Tamamla Kaydet diyince sonraki review session'a geçer
 * - Görseller yan yana büyük gösterilir
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
        const totalCount = items.length;
        const allApproved = items.every(i => i.is_approved);

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
                        <span class="ais-rp-progress-text">${approvedCount}/${totalCount} onaylandı</span>
                    </div>
                    <button class="ais-rp-close" id="ais-rp-close">✕</button>
                </div>

                <!-- Tabs -->
                <div class="ais-rp-tabs">
                    ${items.map((it, idx) => `
                        <button class="ais-rp-tab ${idx === currentIndex ? 'active' : ''} ${it.is_approved ? 'approved' : ''}"
                                data-idx="${idx}">
                            <span class="ais-rp-tab-icon">${getPhotoTypeIcon(it.photo_type)}</span>
                            <span class="ais-rp-tab-label">${it.photo_type_label}</span>
                            ${it.is_approved ? '<span class="ais-rp-tab-check">✓</span>' : ''}
                            ${it.revision_number > 1 ? '<span class="ais-rp-tab-version">v' + it.revision_number + '</span>' : ''}
                        </button>
                    `).join('')}
                </div>

                <!-- İçerik: Yan yana görseller -->
                <div class="ais-rp-content">
                    <div class="ais-rp-comparison">
                        <div class="ais-rp-panel">
                            <div class="ais-rp-panel-label">ORJİNAL</div>
                            <div class="ais-rp-img-wrap ais-rp-zoomable" data-zoom-src="${item.original_url}">
                                <img src="${item.original_url}" class="ais-rp-img" alt="Orijinal"/>
                                <div class="ais-rp-zoom-lens"></div>
                            </div>
                        </div>
                        <div class="ais-rp-vs">VS</div>
                        <div class="ais-rp-panel">
                            <div class="ais-rp-panel-label ais-rp-ai-label">AI SONUÇ</div>
                            <div class="ais-rp-img-wrap ais-rp-zoomable" data-zoom-src="${item.generated_url}">
                                <img src="${item.generated_url}" class="ais-rp-img" alt="AI Sonucu"/>
                                <div class="ais-rp-zoom-lens"></div>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- Alt butonlar -->
                <div class="ais-rp-footer">
                    <div class="ais-rp-actions">
                        ${item.is_approved ? `
                            <div class="ais-rp-approved-badge">✅ Bu görsel onaylandı</div>
                        ` : `
                            <button class="ais-rp-btn ais-rp-btn-reject" id="ais-rp-reject">
                                ❌ Reddet
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
                    ${allApproved || approvedCount > 0 ? `
                        <button class="ais-rp-btn ais-rp-btn-complete" id="ais-rp-complete">
                            ✅ Tamamla ve Kaydet (${approvedCount} görsel)
                        </button>
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

        // Zoom: Mouse takipli büyüteç efekti
        overlay.querySelectorAll('.ais-rp-zoomable').forEach(wrap => {
            const img = wrap.querySelector('.ais-rp-img');
            const lens = wrap.querySelector('.ais-rp-zoom-lens');
            const zoomSrc = wrap.dataset.zoomSrc;
            const ZOOM = 2.5;

            if (!img || !lens) return;

            wrap.addEventListener('mouseenter', () => {
                lens.style.backgroundImage = `url(${zoomSrc})`;
                lens.style.display = 'block';
            });

            wrap.addEventListener('mouseleave', () => {
                lens.style.display = 'none';
            });

            wrap.addEventListener('mousemove', (e) => {
                const rect = img.getBoundingClientRect();
                const x = e.clientX - rect.left;
                const y = e.clientY - rect.top;

                // Resmin dışındaysa gizle
                if (x < 0 || y < 0 || x > rect.width || y > rect.height) {
                    lens.style.display = 'none';
                    return;
                }

                const lensW = 180;
                const lensH = 180;

                // Lens pozisyonu
                lens.style.left = (x - lensW / 2) + 'px';
                lens.style.top = (y - lensH / 2) + 'px';
                lens.style.width = lensW + 'px';
                lens.style.height = lensH + 'px';

                // Background size ve position
                const bgW = rect.width * ZOOM;
                const bgH = rect.height * ZOOM;
                const bgX = -(x * ZOOM - lensW / 2);
                const bgY = -(y * ZOOM - lensH / 2);

                lens.style.backgroundSize = bgW + 'px ' + bgH + 'px';
                lens.style.backgroundPosition = bgX + 'px ' + bgY + 'px';
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
                is_primary: currentIndex === 0, // İlk görsel ana resim
            });
            item.is_approved = true;

            // Sonraki onaylanmamış görsele geç
            const nextIdx = items.findIndex((it, idx) => idx > currentIndex && !it.is_approved);
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

            // Reddedilen görseli listeden çıkar (yeni versiyon üretilecek)
            items.splice(currentIndex, 1);
            if (items.length === 0) {
                alert('Tüm görseller revizeye gönderildi. Popup kapatılıyor.');
                close();
                return;
            }
            if (currentIndex >= items.length) currentIndex = items.length - 1;
            render();
        } catch(e) {
            alert('Red hatası: ' + e.message);
            render();
        }
    }

    async function complete() {
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
