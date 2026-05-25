/** @odoo-module **/

/**
 * Ses Efektleri Modülü — Web Audio API
 * Harici ses dosyası gerektirmez, tarayıcıda tone üretir.
 *
 * Kullanım:
 *   import { playSoundPutaway, playSoundRemove, playSoundTransfer, playSoundError } from "../sound_utils";
 *   playSoundPutaway();  // Raflama başarılı
 */

const _audioCtx = typeof AudioContext !== 'undefined'
    ? new AudioContext() : typeof webkitAudioContext !== 'undefined'
        ? new webkitAudioContext() : null;

function _playTone(frequencies, durations, type = 'sine', volume = 0.3) {
    if (!_audioCtx) return;
    if (_audioCtx.state === 'suspended') _audioCtx.resume();
    const now = _audioCtx.currentTime;
    let offset = 0;
    for (let i = 0; i < frequencies.length; i++) {
        const osc = _audioCtx.createOscillator();
        const gain = _audioCtx.createGain();
        osc.type = type;
        osc.frequency.value = frequencies[i];
        gain.gain.setValueAtTime(volume, now + offset);
        gain.gain.exponentialRampToValueAtTime(0.01, now + offset + durations[i]);
        osc.connect(gain);
        gain.connect(_audioCtx.destination);
        osc.start(now + offset);
        osc.stop(now + offset + durations[i]);
        offset += durations[i] * 0.7;
    }
}

/** ✅ Raflama başarılı — ascending chime (do-mi-sol) */
export function playSoundPutaway() {
    _playTone([523, 659, 784], [0.12, 0.12, 0.25], 'sine', 0.35);
}

/** 📤 Raftan kaldırma — descending tone (sol-mi-do) */
export function playSoundRemove() {
    _playTone([784, 659, 523], [0.1, 0.1, 0.2], 'triangle', 0.3);
}

/** 🔄 Raf taşıma — swoosh effect (mi-fa#-la) */
export function playSoundTransfer() {
    _playTone([330, 370, 440], [0.08, 0.08, 0.2], 'sine', 0.25);
}

/** ❌ Hata — warning buzz */
export function playSoundError() {
    _playTone([200, 150], [0.15, 0.25], 'square', 0.15);
}

/** 🗑️ Toplu silme — deep tone */
export function playSoundClear() {
    _playTone([392, 330, 262], [0.1, 0.1, 0.3], 'triangle', 0.2);
}

/** 📳 Titreşim feedback (mobil) */
export function vibrate(pattern = 150) {
    if (navigator.vibrate) navigator.vibrate(pattern);
}

/** 📳 Hata titreşimi */
export function vibrateError() {
    if (navigator.vibrate) navigator.vibrate([100, 50, 100]);
}
