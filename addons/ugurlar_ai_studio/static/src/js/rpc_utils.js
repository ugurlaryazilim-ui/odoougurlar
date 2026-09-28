/** @odoo-module **/

import { rpc } from "@web/core/network/rpc";

/**
 * AI Studio JSON-RPC yardımcısı (Odoo'nun rpc'si üzerinde).
 *
 * Odoo'nun RPCError'ı genel bir "Odoo Server Error" mesajı taşır; asıl açıklama
 * error.data.message içindedir. Ekranlar e.message'ı doğrudan gösterdiği için
 * burada anlamlı mesajla yeniden fırlatılır.
 */
export async function aisRpc(url, params = {}) {
    try {
        return await rpc(url, params);
    } catch (e) {
        throw new Error(e?.data?.message || e?.message || "RPC Error");
    }
}

/** Oturumun review popup'ını aç (tek inceleme arayüzü). */
export function openReviewPopup(actionService, sessionId) {
    return actionService.doAction({
        type: "ir.actions.client",
        tag: "ugurlar_ai_studio.review_popup",
        params: { session_id: sessionId },
    });
}
