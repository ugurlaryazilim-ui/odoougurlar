/** @odoo-module **/

/**
 * TTS (Text-to-Speech) Seslendirme Modülü
 * ========================================
 * Backend'deki ugurlar.tts.message modelinden mesajları çeker,
 * cache'ler ve Web Speech API ile Türkçe seslendirir.
 *
 * Kullanım:
 *   import { speak, loadTtsConfig, vibrate, vibrateError } from "../sound_utils";
 *   await loadTtsConfig();  // Uygulama başlangıcında 1 kez
 *   speak('stock_search_success');  // → "Ürüne ait bilgiler"
 */

import { rpc } from "@web/core/network/rpc";

// ═══════════════════════════════════════════════════════
// 📳 Titreşim (Haptic Feedback)
// ═══════════════════════════════════════════════════════

/** 📳 Başarı titreşimi (mobil) */
export function vibrate(pattern = 150) {
    if (navigator.vibrate) navigator.vibrate(pattern);
}

/** 📳 Hata titreşimi */
export function vibrateError() {
    if (navigator.vibrate) navigator.vibrate([100, 50, 100]);
}

// ═══════════════════════════════════════════════════════
// 🔊 TTS — Text-to-Speech (Sesli Mesaj)
// Web Speech API ile Türkçe sesli geri bildirim
// ═══════════════════════════════════════════════════════

// TTS mesaj cache'i — key → message
let _ttsCache = {};
let _ttsLoaded = false;
let _ttsLoading = false;

/**
 * Backend'den TTS mesajlarını yükle ve cache'le.
 * Uygulama başlangıcında 1 kez çağrılır.
 * Tekrar çağrılırsa cache'i yeniler.
 */
export async function loadTtsConfig() {
    if (_ttsLoading) return;
    _ttsLoading = true;
    try {
        const res = await rpc('/ugurlar_barcode/api/tts_config', {});
        if (res && res.messages) {
            _ttsCache = res.messages;
            _ttsLoaded = true;
        }
    } catch (e) {
        console.warn('[TTS] Config yüklenemedi:', e);
    }
    _ttsLoading = false;
}

// İlk kullanıcı etkileşiminde TTS engine'i ısıt
let _ttsWarmedUp = false;
function _warmUpTTS() {
    if (_ttsWarmedUp) return;
    _ttsWarmedUp = true;
    try {
        const warmup = new SpeechSynthesisUtterance('');
        warmup.volume = 0;
        speechSynthesis.speak(warmup);
    } catch (e) { /* bazı tarayıcılarda hata verebilir */ }
}
document.addEventListener('click', _warmUpTTS, { once: true });
document.addEventListener('keydown', _warmUpTTS, { once: true });

/**
 * 🔊 Sesli mesaj oku (TTS)
 *
 * @param {string} keyOrText - Cache'deki anahtar VEYA doğrudan metin.
 *   Eğer key cache'de varsa → cache'deki metni okur.
 *   Yoksa → parametre olarak gelen metni doğrudan okur.
 *
 * @param {object} [opts] - Seçenekler
 * @param {number} [opts.rate=1.0] - Konuşma hızı (0.5-2.0)
 * @param {number} [opts.pitch=1.0] - Ses tonu (0-2)
 * @param {number} [opts.volume=1.0] - Ses seviyesi (0-1)
 */
export function speak(keyOrText, opts = {}) {
    if (!keyOrText || typeof speechSynthesis === 'undefined') return;

    // Cache'den metin çek veya doğrudan kullan
    const text = _ttsCache[keyOrText] || keyOrText;

    // Boş veya devre dışı mesaj
    if (!text || text === '-' || text === 'off') return;

    // Önceki konuşmayı kes
    speechSynthesis.cancel();

    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = 'tr-TR';
    utterance.rate = opts.rate ?? 1.0;
    utterance.pitch = opts.pitch ?? 1.0;
    utterance.volume = opts.volume ?? 1.0;

    // Türkçe ses varsa onu seç
    const voices = speechSynthesis.getVoices();
    const trVoice = voices.find(v => v.lang.startsWith('tr'));
    if (trVoice) utterance.voice = trVoice;

    speechSynthesis.speak(utterance);
}

/**
 * TTS cache'inin yüklenip yüklenmediğini kontrol et.
 * Yüklenmediyse otomatik yükle.
 */
export function ensureTtsLoaded() {
    if (!_ttsLoaded && !_ttsLoading) {
        loadTtsConfig();
    }
}
