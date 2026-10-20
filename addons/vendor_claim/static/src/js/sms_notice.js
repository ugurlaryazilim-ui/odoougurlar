/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";

/**
 * Sunucu yanıtlarındaki sms {state, error} sonucunu kullanıcıya bildirir (KK-B14).
 * smsList: tek sonuç ya da kayıt başına sonuç dizisi.
 *  - error: uyarı (SMS gitmedi; durum değişikliği yine de yapıldı)
 *  - test:  "Test modu: SMS gönderilmedi" uyarısı
 *  - queued: normal bilgi (SMS gönderim sırasına alındı)
 *  - none / yok: sessiz
 */
export function notifySms(notification, smsList) {
    const list = (Array.isArray(smsList) ? smsList : [smsList]).filter(Boolean);
    const errors = list.filter((s) => s.state === "error");
    const tests = list.filter((s) => s.state === "test");
    const queued = list.filter((s) => s.state === "queued");
    if (errors.length) {
        const detail = errors[0].error ? `: ${errors[0].error}` : "";
        notification.add(
            errors.length > 1
                ? _t("%(n)s kayıt için SMS gönderilemedi%(detail)s", { n: errors.length, detail })
                : _t("SMS gönderilemedi%(detail)s", { detail }),
            { type: "warning" }
        );
    }
    if (tests.length) {
        notification.add(
            tests.length > 1
                ? _t("Test modu: %(n)s kayıt için SMS gönderilmedi.", { n: tests.length })
                : _t("Test modu: SMS gönderilmedi."),
            { type: "warning" }
        );
    }
    if (queued.length) {
        notification.add(
            queued.length > 1
                ? _t("%(n)s SMS gönderim sırasına alındı.", { n: queued.length })
                : _t("SMS gönderim sırasına alındı."),
            { type: "info" }
        );
    }
}
