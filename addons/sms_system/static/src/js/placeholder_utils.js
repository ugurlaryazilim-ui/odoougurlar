/**
 * Metne yer tutucu ekleme yardımcıları (DOM'dan bağımsız; Node ile test edilir).
 */

/**
 * `token`'ı metne ekler. Seçili aralık varsa onun yerine geçer; imleç bilgisi yoksa (alana hiç tıklanmamış)
 * metnin sonuna eklenir. Konumlar metin uzunluğuna sıkıştırılır.
 *
 * @param {string} text mevcut metin
 * @param {string} token eklenecek yer tutucu, ör. "{ad}"
 * @param {number|null} [selStart] imleç/seçim başı
 * @param {number|null} [selEnd] seçim sonu
 * @returns {{value: string, caret: number}} yeni metin ve eklenen yer tutucunun hemen sonrası
 */
export function insertToken(text, token, selStart = null, selEnd = null) {
    text = text || "";
    const clamp = (n) => Math.min(Math.max(n, 0), text.length);
    const hasCaret = Number.isInteger(selStart);
    const start = hasCaret ? clamp(selStart) : text.length;
    const end = hasCaret && Number.isInteger(selEnd) ? Math.max(start, clamp(selEnd)) : start;
    return {
        value: text.slice(0, start) + token + text.slice(end),
        caret: start + token.length,
    };
}
