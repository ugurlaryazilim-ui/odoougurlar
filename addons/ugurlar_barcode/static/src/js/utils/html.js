/** @odoo-module **/

// Etiket / kargo yazdırma HTML'i Odoo origin'inde açılan pencereye (veya sayfaya) yazılır.
// Müşteri adı, adres, ürün adı pazaryerinden / Nebim'den; şablon alanları içe aktarılan
// JSON'dan gelir: kaçışsız değer oturumu ele geçiren betik çalıştırabilirdi.

export function escapeHtml(value) {
    return String(value ?? "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#39;");
}

// style="" içine yazılan şablon değerleri: yalnız beklenen biçimler, aksi halde varsayılan
export function safeNum(value, fallback = 0) {
    const n = Number(value);
    return Number.isFinite(n) ? n : fallback;
}

const COLOR_RE = /^(#[0-9a-f]{3,8}|transparent|[a-z]{3,20}|rgba?\(\s*[\d.,\s%]+\))$/i;
export function safeColor(value, fallback = "#000000") {
    const v = String(value ?? "").trim();
    return COLOR_RE.test(v) ? v : fallback;
}

const WEIGHTS = new Set(["normal", "bold", "bolder", "lighter", "100", "200", "300", "400", "500", "600", "700", "800", "900"]);
export function safeWeight(value) {
    const v = String(value ?? "normal").trim();
    return WEIGHTS.has(v) ? v : "normal";
}

const ALIGNS = new Set(["left", "center", "right", "justify"]);
export function safeAlign(value) {
    const v = String(value ?? "left").trim();
    return ALIGNS.has(v) ? v : "left";
}
