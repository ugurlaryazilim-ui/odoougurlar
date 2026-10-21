/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { FormController } from "@web/views/form/form_controller";
import { useService } from "@web/core/utils/hooks";
import { onMounted, onPatched, onWillUnmount } from "@odoo/owl";

const FAST_DELAY = 400;
const MAX_DELAY = 30000;

// DIKKAT: geri çekilme durumu controller örneğinde değil modül düzeyinde tutulur. Kilit cron'dayken
// sunucu act_window döndürür ve action servisi her seferinde YENİ bir FormController kurar; örnekte
// tutulan durum her yanıtta sıfırlanır, geri çekilme hiç işlemez (A4 YÖ-1).
const autoState = new Map();   // resId -> { delay, notified, lastProgress }

patch(FormController.prototype, {
    setup() {
        super.setup(...arguments);
        this.notification = useService("notification");

        const checkAutoDownload = () => {
            if (this.props.resModel === "ugurlar.invoice.collector") {
                const record = this.model.root;
                if (record && record.data && record.data.state === "downloading") {
                    // Bekleyen fatura sayısını kontrol et
                    // processed_count ve total_found_invoices üzerinden
                    const processed = record.data.processed_count || 0;
                    const total = record.data.total_found_invoices || 0;
                    const pendingCount = record.data.pending_count || 0;

                    // Eğer hâlâ bekleyen fatura varsa otomatik tetikle
                    // pending_count alanı yoksa progress_text'ten anla
                    const progressText = record.data.progress_text || '';
                    const hasPending = pendingCount > 0 ||
                                       (total > 0 && processed < total) ||
                                       progressText.includes('Bekleyen');

                    if (!hasPending) {
                        // Bekleyen fatura yok — otomatik tetikleme yapma
                        autoState.delete(record.resId);
                        return;
                    }

                    // NEDEN: iş cron'da işleniyorsa sunucu adımı atlayıp formu aynen döndürür; ilerleme
                    // olmadan 400 ms'de bir yeniden basmak sunucuyu boşuna yorar (A4 Ö-3). Ardışık
                    // ilerlemesiz yanıtlarda bekleme katlanır: 400 → 800 → 1600 → … → 30000 ms (üst sınır);
                    // ilerleme görülünce 400 ms'ye döner. Bildirim ilk ilerlemesiz yanıtta bir kez çıkar.
                    // NEDEN: her controller en çok bir kez zamanlar. Tıklamadan sonra eski controller da
                    // yamalanıp yeniden değerlendirir (canlı ölçüldü); yanıtla gelen yeni controller de
                    // değerlendirir. Eski controller'ı sessiz tutmazsak her yanıtta gecikme iki kez katlanır.
                    if (this._autoScheduled) {
                        return;
                    }
                    this._autoScheduled = true;
                    const st = autoState.get(record.resId) || { delay: FAST_DELAY, notified: false };
                    if (st.lastProgress === processed) {
                        st.delay = Math.min(st.delay * 2, MAX_DELAY);
                        if (!st.notified) {
                            st.notified = true;
                            this.notification.add(
                                "Faturalar arka planda işleniyor; ekran kendiliğinden güncellenecek.",
                                { type: "info" }
                            );
                        }
                    } else {
                        st.delay = FAST_DELAY;
                        st.notified = false;
                    }
                    st.lastProgress = processed;
                    autoState.set(record.resId, st);

                    this._autoDownloadTimer = setTimeout(() => {
                        const btn = document.querySelector("button[name='action_download_zip']");
                        if (btn) {
                            btn.click();
                        }
                    }, st.delay);
                }
            }
        };

        onMounted(() => {
            checkAutoDownload();
        });

        onPatched(() => {
            checkAutoDownload();
        });

        // NEDEN: diyalog kapanınca/yenisiyle değişince eski controller'ın bekleyen tıklaması kalmasın.
        onWillUnmount(() => {
            clearTimeout(this._autoDownloadTimer);
        });
    }
});
