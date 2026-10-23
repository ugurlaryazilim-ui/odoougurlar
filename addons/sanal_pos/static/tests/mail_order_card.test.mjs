// Mail Order kart sayfası betiği davranış testleri (A1-G3; KK-1.1/1.2/1.4/1.9/1.12/1.16/1.17/1.18).
// Gerçek static/src/js/mail_order_card.js dosyası node:vm içinde küçük bir DOM taklidiyle koşulur
// (jsdom yok). Gerçek tarayıcı + CSP doğrulaması A1-G4 Playwright'tadır.
// Koşu: node --test addons/sanal_pos/static/tests/mail_order_card.test.mjs
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const SOURCE = fs.readFileSync(new URL('../src/js/mail_order_card.js', import.meta.url), 'utf8');
const GOOD_PAN = '4355084355084358';

class El {
  constructor(doc, id, props = {}) {
    Object.assign(this, { doc, id, value: '', dataset: {}, hidden: false, disabled: false,
      textContent: '', attrs: {}, listeners: {}, selectionStart: null, validity: { valid: true },
      checked: false, name: '', maxLength: -1, placeholder: '' }, props);
  }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; }
  removeAttribute(k) { delete this.attrs[k]; }
  addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); }
  fire(type, extra = {}) {
    const ev = { type, target: this, defaultPrevented: false,
      preventDefault() { this.defaultPrevented = true; }, ...extra };
    for (const fn of this.listeners[type] || []) fn(ev);
    return ev;
  }
  setSelectionRange(a) { this.selectionStart = a; }
  focus() { this.doc.activeElement = this; }
}

function radio(doc, count, total, monthly, surcharge, checked = false) {
  const r = new El(doc, null, { name: 'installmentCount', value: String(count), checked });
  r.dataset = { label: count === 1 ? 'Tek çekim' : `${count} taksit`, total, monthly };
  if (surcharge) r.dataset.surcharge = surcharge;
  return r;
}

function page({ omit = [], seconds = '2700', nowYm = '2026-10', single = false } = {}) {
  const doc = { readyState: 'complete', activeElement: null, listeners: {},
    addEventListener(t, fn) { (this.listeners[t] ||= []).push(fn); } };
  const html = { classes: new Set() };
  doc.documentElement = { classList: { add: (c) => html.classes.add(c) } };
  const ids = ['mo-form', 'pan', 'cardOwner', 'expiryMonth', 'expiryYear', 'cvv', 'mo-pay',
    'mo-pay-text', 'mo-sum-total', 'mo-sum-detail', 'mo-remaining', 'mo-expired', 'mo-amex',
    'mo-form-error', 'cardOwner-error', 'pan-error', 'expiry-error', 'cvv-error'];
  const els = {};
  for (const id of ids) if (!omit.includes(id)) els[id] = new El(doc, id);
  for (const id of ['mo-sum-detail', 'mo-expired', 'mo-amex', 'mo-form-error', 'cardOwner-error',
    'pan-error', 'expiry-error', 'cvv-error']) if (els[id]) els[id].hidden = true;
  const pan = els.pan;
  pan.attrs.pattern = '[0-9]{12,19}';
  pan.maxLength = 19;
  pan.placeholder = '1234567812345678';
  els['mo-pay-text'].textContent = 'Öde · 3D Secure';
  els['mo-sum-total'].textContent = '1.450,00 TL';
  if (els['mo-remaining']) els['mo-remaining'].dataset.seconds = seconds;
  els['mo-form'].dataset.nowYm = nowYm;
  const cards = new El(doc, null);
  cards.dataset.brand = '';
  const radios = [radio(doc, 1, '1.450,00 TL', '1.450,00 TL', '', true)];
  if (!single) radios.push(radio(doc, 3, '1.646,77 TL', '548,92 TL', '196,77 TL'));
  els['mo-form'].querySelectorAll = (sel) => (sel === 'input[name="installmentCount"]' ? radios : []);
  doc.getElementById = (id) => els[id] || null;
  doc.querySelector = (sel) => (sel === '.mo-cards' ? cards : null);

  const clock = { t: 1000, timers: [] };
  const submits = [];
  const state = { submitThrows: false };
  class HTMLFormElement {}
  HTMLFormElement.prototype.submit = function () {
    if (state.submitThrows) throw new Error('x');
    submits.push({ form: this, pan: pan.value });
  };
  const win = { listeners: {}, addEventListener(t, fn) { (this.listeners[t] ||= []).push(fn); } };
  const ctx = vm.createContext({
    document: doc, window: win, HTMLFormElement,
    performance: { now: () => clock.t },
    setInterval: (fn, ms) => { clock.timers.push({ fn, ms }); return clock.timers.length; },
    clearInterval: (h) => { if (clock.timers[h - 1]) clock.timers[h - 1].cleared = true; },
  });
  vm.runInContext(SOURCE, ctx);
  return { doc, els, html, cards, radios, clock, submits, state, win };
}

function type(p, value, caret = value.length, inputType = 'insertText') {
  const pan = p.els.pan;
  pan.value = value;
  pan.selectionStart = caret;
  pan.focus();
  pan.fire('input', { inputType });
}

function fillValid(p, panValue = GOOD_PAN) {
  p.els.cardOwner.value = 'AHMET YILMAZ';
  type(p, panValue);
  p.els.expiryMonth.value = '12';
  p.els.expiryYear.value = '2030';
}

const submit = (p) => p.els['mo-form'].fire('submit');

test('kurulum_basarili_mo_js_ve_gevsek_desen', () => {
  const p = page();
  assert.ok(p.html.classes.has('mo-js'));
  assert.equal(p.els.pan.getAttribute('pattern'), '[0-9 ]{12,23}');
  assert.equal(p.els.pan.maxLength, 23);
  assert.equal(p.els.pan.placeholder, '0000 0000 0000 0000');
});

test('eksik_oge_scriptsiz_mod_kalir', () => {
  for (const id of ['mo-form-error', 'mo-amex', 'pan-error', 'mo-remaining']) {
    const p = page({ omit: [id] });
    assert.ok(!p.html.classes.has('mo-js'), id);
    assert.equal(p.els.pan.getAttribute('pattern'), '[0-9]{12,19}', id);
    assert.equal((p.els.pan.listeners.input || []).length, 0, id);
    assert.equal((p.els['mo-form'].listeners.submit || []).length, 0, id);
  }
  const bad = page({ nowYm: '' });
  assert.ok(!bad.html.classes.has('mo-js'));
});

test('gruplama_imlec_ve_19_hane', () => {
  const p = page();
  type(p, GOOD_PAN);
  assert.equal(p.els.pan.value, '4355 0843 5508 4358');
  assert.equal(p.els.pan.selectionStart, 19);
  type(p, '4355 10843 5508 4358', 6);                 // ortaya '1' eklendi
  assert.equal(p.els.pan.value, '4355 1084 3550 8435 8');
  assert.equal(p.els.pan.selectionStart, 6);
  type(p, '4355-0843-5508-4358-1234');                 // yapıştırma: rakam dışı atılır, 19 hane
  assert.equal(p.els.pan.value, '4355 0843 5508 4358 123');
});

test('bosluk_geri_silinince_onceki_rakam_silinir', () => {
  const p = page();
  type(p, '43550843');
  assert.equal(p.els.pan.value, '4355 0843');
  type(p, '43550843', 4, 'deleteContentBackward');     // '4355 |0843' -> boşluk silindi
  assert.equal(p.els.pan.value, '4350 843');
  assert.equal(p.els.pan.selectionStart, 3);
  type(p, '4350843', 4, 'deleteContentForward');       // '4350| 843' -> boşluk ileri silindi
  assert.equal(p.els.pan.value, '4350 43');
});

test('marka_vurgusu_ve_amex_uyarisi', () => {
  const p = page();
  const cases = { '4': 'visa', '51': 'mastercard', '55': 'mastercard', '2221': 'mastercard',
    '2720': 'mastercard', '2721': '', '9792': 'troy', '6011': '', '50': '', '34': '', '37': '' };
  for (const [prefix, brand] of Object.entries(cases)) {
    type(p, prefix);
    assert.equal(p.cards.dataset.brand, brand, prefix);
    assert.equal(p.els['mo-amex'].hidden, !['34', '37'].includes(prefix), prefix);
  }
});

test('amex_gonderimi_engellemez', () => {
  const p = page();
  fillValid(p, '378282246310005');
  assert.equal(p.els['mo-amex'].hidden, false);
  submit(p);
  assert.equal(p.submits.length, 1);
  assert.equal(p.submits[0].pan, '378282246310005');
});

test('luhn_ve_uzunluk_engeli_mesaj_aria_invalid', () => {
  const p = page();
  fillValid(p, '4355084355084359');
  const ev = submit(p);
  assert.ok(ev.defaultPrevented);
  assert.equal(p.submits.length, 0);
  assert.equal(p.els['pan-error'].textContent, 'Kart numarası geçersiz (kontrol hanesi tutmuyor)');
  assert.equal(p.els['pan-error'].hidden, false);
  assert.equal(p.els.pan.getAttribute('aria-invalid'), 'true');
  assert.equal(p.doc.activeElement, p.els.pan);
  type(p, '43550843');
  submit(p);
  assert.equal(p.els['pan-error'].textContent, 'Kart numarası 12-19 hane olmalı');
  type(p, GOOD_PAN);                                   // düzeltilince hata kalkar
  assert.equal(p.els.pan.getAttribute('aria-invalid'), null);
  assert.equal(p.els['pan-error'].hidden, true);
});

test('skt_gecmis_engellenir_bu_ay_gecerli', () => {
  const p = page({ nowYm: '2026-10' });
  fillValid(p);
  p.els.expiryMonth.value = '09';
  p.els.expiryYear.value = '2026';
  submit(p);
  assert.equal(p.submits.length, 0);
  assert.equal(p.els['expiry-error'].textContent, 'Son kullanma tarihi geçmiş');
  assert.equal(p.els.expiryMonth.getAttribute('aria-invalid'), 'true');
  p.els.expiryMonth.value = '10';
  submit(p);
  assert.equal(p.submits.length, 1);
});

test('cvv_validity_ile_denetlenir_degeri_okunmaz', () => {
  const p = page();
  let reads = 0;
  Object.defineProperty(p.els.cvv, 'value', { get() { reads += 1; return '123'; } });
  fillValid(p);
  p.els.cvv.validity = { valid: false };
  submit(p);
  assert.equal(p.submits.length, 0);
  assert.equal(p.els['cvv-error'].textContent, 'CVV 3 hane olmalı');
  p.els.cvv.validity = { valid: true };
  submit(p);
  assert.equal(p.submits.length, 1);
  assert.equal(reads, 0, 'CVV değeri okunmamalı');
});

test('gecerli_gonderim_yalniz_rakam_tek_post_cift_gonderim_yok', () => {
  const p = page();
  fillValid(p);
  assert.equal(p.els.pan.value, '4355 0843 5508 4358');
  const first = submit(p);
  const second = submit(p);
  assert.ok(first.defaultPrevented && second.defaultPrevented);
  assert.equal(p.submits.length, 1);
  assert.equal(p.submits[0].pan, GOOD_PAN);
  assert.match(p.submits[0].pan, /^\d{12,19}$/);
  assert.equal(p.submits[0].form, p.els['mo-form']);
  assert.equal(p.els['mo-pay'].disabled, true);
});

test('dogrulamada_istisna_fail_closed_gonderim_yok', () => {
  const p = page();
  fillValid(p);
  Object.defineProperty(p.els.cvv, 'validity', { get() { throw new Error('boom'); } });
  const ev = submit(p);
  assert.ok(ev.defaultPrevented);
  assert.equal(p.submits.length, 0);
  assert.equal(p.els['mo-form-error'].hidden, false);
  assert.equal(p.els.pan.value, '4355 0843 5508 4358');
});

test('submit_istisnasi_genel_hata_gosterir', () => {
  const p = page();
  fillValid(p);
  p.state.submitThrows = true;
  assert.ok(submit(p).defaultPrevented);
  assert.equal(p.els['mo-form-error'].textContent, 'Ödeme başlatılamadı; sayfayı yenileyip tekrar deneyin.');
  assert.equal(p.els['mo-form-error'].hidden, false);
});

test('taksit_secimi_dugme_ve_ozete_yansir_tek_cekime_doner', () => {
  const p = page();
  const t = p.els['mo-pay-text'];
  assert.equal(t.textContent, '1.450,00 TL öde · 3D Secure');
  p.radios[0].checked = false;
  p.radios[1].checked = true;
  p.els['mo-form'].fire('change', { target: p.radios[1] });
  assert.equal(t.textContent, '1.646,77 TL öde · 3D Secure');
  assert.equal(p.els['mo-sum-total'].textContent, '1.646,77 TL');
  assert.equal(p.els['mo-sum-detail'].textContent,
    'Fatura tutarı 1.450,00 TL · Vade farkı 196,77 TL · Çekilecek toplam 1.646,77 TL · 3 × 548,92 TL');
  assert.equal(p.els['mo-sum-detail'].hidden, false);
  p.radios[1].checked = false;
  p.radios[0].checked = true;
  p.els['mo-form'].fire('change', { target: p.radios[0] });
  assert.equal(t.textContent, '1.450,00 TL öde · 3D Secure');
  assert.equal(p.els['mo-sum-total'].textContent, '1.450,00 TL');
  assert.equal(p.els['mo-sum-detail'].hidden, true);
});

test('tek_radyo_taksit_sorgusu_hatasinda_calisir', () => {
  const p = page({ single: true });
  assert.ok(p.html.classes.has('mo-js'));
  assert.equal(p.els['mo-pay-text'].textContent, '1.450,00 TL öde · 3D Secure');
});

test('kalan_sure_monotonik_30_sn_altinda_guncellenir_0da_kilitlenir', () => {
  const p = page({ seconds: '120' });
  assert.equal(p.els['mo-remaining'].textContent, '2 dk kaldı');
  assert.equal(p.clock.timers.length, 1);
  assert.ok(p.clock.timers[0].ms <= 30000);
  p.clock.t += 61000;
  p.clock.timers[0].fn();
  assert.equal(p.els['mo-remaining'].textContent, '1 dk kaldı');
  fillValid(p);
  p.clock.t += 59000;
  p.clock.timers[0].fn();
  assert.equal(p.els['mo-pay'].disabled, true);
  assert.equal(p.els['mo-expired'].hidden, false);
  assert.ok(p.clock.timers[0].cleared);
  submit(p);
  assert.equal(p.submits.length, 0);
});

test('acilista_sure_dolmus', () => {
  const p = page({ seconds: '0' });
  assert.equal(p.els['mo-pay'].disabled, true);
  assert.equal(p.els['mo-expired'].hidden, false);
  assert.equal(p.clock.timers.length, 0);
  fillValid(p);
  submit(p);
  assert.equal(p.submits.length, 0);
});

test('pageshow_sifirlar', () => {
  const p = page();
  fillValid(p);
  submit(p);
  assert.equal(p.els['mo-pay'].disabled, true);
  for (const fn of p.win.listeners.pageshow) fn({ persisted: true });
  assert.equal(p.els['mo-pay'].disabled, false);
  submit(p);
  assert.equal(p.submits.length, 2);
});

test('blur_ve_invalid_olayi_hata_satiri_gosterir', () => {
  const p = page();
  p.els.cardOwner.fire('blur');
  assert.equal(p.els['cardOwner-error'].textContent, 'Kart sahibinin adını girin');
  assert.equal(p.els.cardOwner.getAttribute('aria-invalid'), 'true');
  p.els.cardOwner.value = 'AHMET';
  p.els.cardOwner.fire('input');
  assert.equal(p.els['cardOwner-error'].hidden, true);
  const ev = p.els['mo-form'].fire('invalid', { target: p.els.cvv });
  assert.equal(p.els['expiry-error'].textContent, 'Son kullanma ayını ve yılını seçin');
  assert.equal(p.els['pan-error'].textContent, 'Kart numarası 12-19 hane olmalı');
  // G-6: satır gösterildi -> yerel balon bastırılır (çift mesaj yok), odak ilk hatalı alana.
  assert.equal(ev.defaultPrevented, true);
  assert.equal(p.doc.activeElement, p.els.pan);
});

test('invalid_olayi_betik_hata_bulmazsa_yerel_balon_kalir', () => {
  const p = page();
  fillValid(p);
  const ev = p.els['mo-form'].fire('invalid', { target: p.els.cvv });
  assert.equal(ev.defaultPrevented, false, 'betik satır göstermediyse kullanıcı yerel mesajı görmeli');
  assert.equal(p.submits.length, 0);
});
