// Mail Order kart sayfası betiği BIN davranışı testleri (A2-G3; KK-2.1..2.5, G-9 yanı).
// Gerçek static/src/js/mail_order_card.js node:vm içinde küçük DOM + sahte fetch ile koşulur (jsdom yok).
// Gerçek tarayıcı + CSP + HAR doğrulaması A2-G3/G4 Playwright'tadır (04-kabul-testleri.md).
// Koşu: node --test addons/sanal_pos/static/tests/mail_order_card_bin.test.mjs
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const SOURCE = fs.readFileSync(new URL('../src/js/mail_order_card.js', import.meta.url), 'utf8');
const PAN = '4355084355084358';             // herkese açık Paratika test kartı
const BIN = '43550843';
const BIN_PATH = '/sanal_pos/mail_order/bin';
const WARN = 'Kartın taksitleri doğrulanamadı; tüm seçenekler gösteriliyor, desteklenmeyen taksiti banka reddeder.';
const FIRST = { 1: ['1.000,00 TL', '1.000,00 TL', ''], 2: ['1.000,00 TL', '500,00 TL', ''],
  3: ['1.015,00 TL', '338,33 TL', '15,00 TL'], 6: ['1.030,00 TL', '171,67 TL', '30,00 TL'] };

class El {
  constructor(doc, id, props = {}) {
    Object.assign(this, { doc, id, value: '', dataset: {}, hidden: false, disabled: false,
      textContent: '', attrs: {}, listeners: {}, selectionStart: null, validity: { valid: true },
      checked: false, name: '', maxLength: -1, placeholder: '', children: [] }, props);
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

// Taksit kartı: <label class="mo-inst-card"><input radio/><span.mo-inst-body>başlık,tutar,toplam,ücret,ağ</span></label>
function card(doc, count, withTitle = true) {
  const [total, monthly, surcharge] = FIRST[count] || ['0', '0', ''];
  const input = new El(doc, null, { name: 'installmentCount', value: String(count), checked: count === 1 });
  input.dataset = { label: count === 1 ? 'Tek çekim' : `${count} taksit`, total, monthly };
  if (surcharge) input.dataset.surcharge = surcharge;
  const label = new El(doc, null, { cls: 'mo-inst-card' });
  const spans = {};
  for (const c of ['title', 'amount', 'total', 'fee', 'networks']) {
    spans[c] = new El(doc, null, { cls: `mo-inst-${c}` });
  }
  spans.title.textContent = input.dataset.label;
  spans.amount.textContent = count === 1 ? total : `${monthly} / ay`;
  spans.total.textContent = `Toplam ${total}`;
  spans.fee.textContent = surcharge ? `%1,50 · ${surcharge}` : 'Vade farkı yok';
  label.spans = spans;
  label.querySelector = (sel) => spans[sel.replace(/^\.mo-inst-/, '')] || null;
  label.querySelectorAll = (sel) => (spans[sel.replace(/^\.mo-inst-/, '')] ? [spans[sel.replace(/^\.mo-inst-/, '')]] : []);
  label.children = Object.values(spans);
  input.closest = () => label;
  input.parentElement = label;
  input.parentNode = label;
  input.card = label;
  label.input = input;
  return input;
}

const shown = (r) => !(r.card.hidden || r.hidden);

function page({ bin = true, counts = [1, 2, 3, 6], omit = [], hang = false, pid = '4711' } = {}) {
  const doc = { readyState: 'complete', activeElement: null, listeners: {},
    addEventListener(t, fn) { (this.listeners[t] ||= []).push(fn); } };
  const html = { classes: new Set() };
  doc.documentElement = { classList: { add: (c) => html.classes.add(c) } };
  const ids = ['mo-form', 'pan', 'cardOwner', 'expiryMonth', 'expiryYear', 'cvv', 'mo-pay',
    'mo-pay-text', 'mo-sum-total', 'mo-sum-detail', 'mo-remaining', 'mo-expired', 'mo-amex',
    'mo-form-error', 'cardOwner-error', 'pan-error', 'expiry-error', 'cvv-error',
    'mo-bin-status', 'mo-detected', 'mo-inst-note'];
  const els = {};
  for (const id of ids) if (!omit.includes(id)) els[id] = new El(doc, id);
  for (const id of ['mo-sum-detail', 'mo-expired', 'mo-amex', 'mo-form-error', 'cardOwner-error',
    'pan-error', 'expiry-error', 'cvv-error']) els[id].hidden = true;
  els.pan.attrs.pattern = '[0-9]{12,19}';
  els.pan.maxLength = 19;
  els['mo-pay-text'].textContent = 'Öde · 3D Secure';
  els['mo-sum-total'].textContent = '1.000,00 TL';
  els['mo-remaining'].dataset.seconds = '2700';
  els['mo-form'].dataset.nowYm = '2026-10';
  els['mo-form'].dataset.paymentId = pid;
  if (bin) els['mo-form'].dataset.bin = '1';
  const cards = new El(doc, null);
  cards.dataset.brand = '';
  const radios = counts.map((n) => card(doc, n));
  els['mo-form'].querySelectorAll = (sel) => {
    if (sel.includes('installmentCount')) return radios;
    if (sel.includes('mo-inst-card')) return radios.map((r) => r.card);
    return [];
  };
  doc.getElementById = (id) => els[id] || null;
  doc.querySelector = (sel) => (sel === '.mo-cards' ? cards : null);

  const clock = { t: 1000, timers: [] };
  const submits = [];
  class HTMLFormElement {}
  HTMLFormElement.prototype.submit = function () { submits.push({ pan: els.pan.value }); };
  const win = { listeners: {}, addEventListener(t, fn) { (this.listeners[t] ||= []).push(fn); } };

  const fetches = [];
  const timeouts = [];
  const fakeFetch = (url, opts) => {
    const entry = { url, opts };
    entry.promise = new Promise((resolve, reject) => { entry.resolve = resolve; entry.reject = reject; });
    fetches.push(entry);
    return entry.promise;
  };
  class AbortController {
    constructor() { this.signal = { aborted: false }; }
    abort() { this.signal.aborted = true; this.onabort?.(); }
  }
  const ctx = vm.createContext({
    document: doc, window: win, HTMLFormElement, fetch: fakeFetch, AbortController, JSON, Promise,
    performance: { now: () => clock.t },
    setInterval: (fn, ms) => { clock.timers.push({ fn, ms }); return clock.timers.length; },
    clearInterval: (h) => { if (clock.timers[h - 1]) clock.timers[h - 1].cleared = true; },
    setTimeout: (fn, ms) => { timeouts.push({ fn, ms, cleared: false }); return timeouts.length; },
    clearTimeout: (h) => { if (timeouts[h - 1]) timeouts[h - 1].cleared = true; },
  });
  vm.runInContext(SOURCE, ctx);
  return { doc, els, html, radios, clock, submits, fetches, timeouts, win };
}

const flush = async () => { for (let i = 0; i < 6; i++) await new Promise((r) => setImmediate(r)); };

function type(p, value) {
  p.els.pan.value = value;
  p.els.pan.selectionStart = value.length;
  p.els.pan.focus();
  p.els.pan.fire('input', { inputType: 'insertText' });
}

function row(count, total, monthly, rate, surcharge) {
  return { count, label: count === 1 ? 'Tek çekim' : `${count} taksit`, total_text: total,
    monthly_text: monthly, rate_text: rate, surcharge_text: surcharge, networks: [] };
}

const CREDIT = {
  ok: true, card_type: 'credit', foreign: false, bank: 'Akbank', program: 'Axess', brand: 'visa',
  detected: 'Akbank · Axess · Kredi kartı', installments: true, note: '',
  rows: [row(1, '1.000,00 TL', '1.000,00 TL', 'Vade farkı yok', ''),
    row(2, '1.000,00 TL', '500,00 TL', 'Vade farkı yok', ''),
    row(3, '1.020,00 TL', '340,00 TL', '%2,00', '20,00 TL')],
};
const DEBIT = {
  ok: true, card_type: 'debit', foreign: false, bank: 'Akbank', program: '', brand: 'mastercard',
  detected: 'Akbank · Banka kartı', installments: false, note: 'Banka kartıyla taksit yapılamaz.',
  rows: [row(1, '1.000,00 TL', '1.000,00 TL', 'Vade farkı yok', '')],
};
const reply = (entry, body, status = 200) => (assert.ok(entry, 'beklenen fetch yapılmadı'), entry).resolve({ ok: status < 300, status, json: async () => body });

test('data_bin_yoksa_fetch_yok', async () => {
  const p = page({ bin: false });
  type(p, PAN);
  await flush();
  assert.equal(p.fetches.length, 0);
  assert.equal(p.els['mo-bin-status'].textContent, '');
});

test('sekizinci_hanede_tek_fetch_tam_secenekler', async () => {
  const p = page();
  type(p, '4355 084');
  assert.equal(p.fetches.length, 0, '7 hanede istek yok');
  type(p, '4355 0843');
  assert.equal(p.fetches.length, 1);
  assert.ok(p.fetches[0], 'beklenen fetch yapılmadı');
  const { url, opts } = p.fetches[0];
  assert.equal(url, BIN_PATH);
  assert.equal(opts.method, 'POST');
  assert.equal(opts.credentials, 'same-origin');
  assert.equal(opts.redirect, 'error');
  assert.equal(opts.cache, 'no-store');
  assert.equal(opts.referrerPolicy, 'no-referrer');
  assert.equal(opts.headers['Content-Type'], 'application/json');
  assert.ok(opts.signal, 'AbortController sinyali');
  const body = JSON.parse(opts.body);
  assert.deepEqual(Object.keys(body).sort(), ['bin', 'payment_id']);
  assert.equal(body.bin, BIN);
  assert.equal(body.payment_id, 4711);
  assert.equal(typeof body.payment_id, 'number');
  assert.doesNotMatch(opts.body, /4355084355|cvv|expiry|cardOwner/);
});

test('dokuzuncu_ve_sonraki_haneler_istek_tetiklemez', async () => {
  const p = page();
  type(p, '43550843');
  for (const v of ['435508435', '4355084355', PAN]) type(p, v);
  assert.equal(p.fetches.length, 1);
});

test('ayni_bin_onbellekten_farkli_bin_yeni_istek', async () => {
  const p = page();
  type(p, BIN);
  reply(p.fetches[0], CREDIT);
  await flush();
  type(p, '4355');                                  // 8 haneden aşağı
  type(p, BIN);                                     // aynı BIN: istek yok, sonuç yeniden uygulanır
  await flush();
  assert.equal(p.fetches.length, 1, 'aynı BIN için tek istek');
  assert.equal(p.els['mo-detected'].textContent, CREDIT.detected, 'önbellekten yeniden uygulandı');
  type(p, '52828282');
  assert.equal(p.fetches.length, 2, 'farklı BIN yeni istek');
  assert.equal(JSON.parse(p.fetches[1].opts.body).bin, '52828282');
});

test('amex_onekleri_34_37_istek_atmaz', async () => {
  const p = page();
  type(p, '34000000');
  type(p, '37123456');
  await flush();
  assert.equal(p.fetches.length, 0);
});

test('kisa_pan_aglari_diners_amex_istek_atmaz_not_yazar', async () => {
  // G2-4: 14-15 haneli ağlarda ilk 8 hane PAN'ın yarısından fazlasıdır; sorulmaz, uyarı yazılır
  const SKIP = 'Bu kartta taksit sorgulanmaz; desteklenmeyen taksiti banka reddeder.';
  for (const value of ['36000000', '30000000', '30512345', '38000000', '39000000', '34000000', '37000000']) {
    const p = page();
    type(p, value);
    await flush();
    assert.equal(p.fetches.length, 0, value);
    assert.equal(p.els['mo-bin-status'].textContent, SKIP, value);
    assert.ok(p.radios.every(shown), 'tüm seçenekler görünür kalır: ' + value);
    type(p, BIN);
    assert.equal(p.fetches.length, 1, 'normal BIN sonrası sorgu çalışır: ' + value);
  }
  const p = page();
  type(p, '30612345');               // 306 Diners aralığında değil (300-305)
  assert.equal(p.fetches.length, 1);
});

test('beklerken_yukleniyor_gosterilir_dugme_kilitlenmez_gonderim_gecer', async () => {
  const p = page();
  p.els.cardOwner.value = 'AHMET YILMAZ';
  p.els.expiryMonth.value = '12';
  p.els.expiryYear.value = '2030';
  type(p, PAN);
  assert.equal(p.fetches.length, 1);
  assert.equal(p.els['mo-bin-status'].textContent, 'Taksitler yükleniyor…');
  assert.equal(p.els['mo-pay'].disabled, false, 'düğme kilitlenmez (KK-2.5)');
  p.els['mo-form'].fire('submit');
  assert.equal(p.submits.length, 1, 'yanıt gelmeden gönderim yapılabilir');
});

test('kredi_karti_yalniz_programin_kartlari_ve_metinler', async () => {
  const p = page();
  type(p, PAN);
  reply(p.fetches[0], CREDIT);
  await flush();
  assert.deepEqual(p.radios.map((r) => shown(r)), [true, true, true, false], '6 taksit gizlendi');
  const three = p.radios[2];
  assert.equal(three.card.spans.total.textContent, 'Toplam 1.020,00 TL');
  assert.match(three.card.spans.amount.textContent, /340,00 TL/);
  assert.match(three.card.spans.fee.textContent, /%2,00/);
  assert.match(three.card.spans.fee.textContent, /20,00 TL/);
  assert.equal(three.dataset.total, '1.020,00 TL');
  assert.equal(three.dataset.monthly, '340,00 TL');
  assert.equal(three.dataset.surcharge, '20,00 TL');
  assert.equal(p.els['mo-detected'].textContent, 'Akbank · Axess · Kredi kartı');
  assert.notEqual(p.els['mo-bin-status'].textContent, 'Taksitler yükleniyor…', 'yükleniyor temizlendi');
  assert.equal(p.radios.length, 4, 'yeni öğe üretilmez');
});

test('hesap_karti_yalniz_tek_cekim_ve_not', async () => {
  const p = page();
  type(p, PAN);
  reply(p.fetches[0], DEBIT);
  await flush();
  assert.deepEqual(p.radios.map((r) => shown(r)), [true, false, false, false]);
  assert.equal(p.radios[0].checked, true);
  assert.equal(p.els['mo-bin-status'].textContent, 'Banka kartıyla taksit yapılamaz.');
  assert.equal(p.els['mo-detected'].textContent, 'Akbank · Banka kartı');
});

test('secili_taksit_desteklenmiyorsa_tek_cekime_doner_not_yazar', async () => {
  const p = page();
  p.radios[3].checked = true;                       // 6 taksit seçili
  p.radios[0].checked = false;
  type(p, PAN);
  reply(p.fetches[0], CREDIT);                      // programda 6 yok
  await flush();
  assert.equal(p.radios[3].checked, false);
  assert.equal(p.radios[0].checked, true, 'Tek çekim seçildi');
  assert.equal(p.els['mo-inst-note'].textContent, 'Bu kart 6 taksiti desteklemiyor; tek çekim seçildi');
  assert.equal(p.els['mo-sum-total'].textContent, '1.000,00 TL', 'özet güncel');
});

test('secili_taksit_destekleniyorsa_yeni_oranla_guncel_kalir', async () => {
  const p = page();
  p.radios[2].checked = true;
  p.radios[0].checked = false;
  p.radios[2].fire('change');
  type(p, PAN);
  reply(p.fetches[0], CREDIT);
  await flush();
  assert.equal(p.radios[2].checked, true);
  assert.equal(p.els['mo-inst-note'].textContent, '');
  assert.match(p.els['mo-sum-total'].textContent, /1\.020,00 TL/, 'yeni oranla toplam');
});

test('sayfada_olmayan_satir_yok_sayilir', async () => {
  const p = page({ counts: [1, 3] });
  type(p, PAN);
  reply(p.fetches[0], CREDIT);                      // 2 sayfada yok
  await flush();
  assert.equal(p.radios.length, 2);
  assert.deepEqual(p.radios.map((r) => shown(r)), [true, true]);
});

for (const [name, fail] of [
  ['http_502', (e) => reply(e, { ok: false, error: 'provider' }, 502)],
  ['http_429', (e) => reply(e, { ok: false, error: 'rate_limited' }, 429)],
  ['ag_reddi', (e) => e.reject(new TypeError('network'))],
  ['bozuk_json', (e) => e.resolve({ ok: true, status: 200, json: async () => { throw new SyntaxError('x'); } })],
  ['ok_false_200', (e) => reply(e, { ok: false, error: 'server' }, 200)],
]) {
  test(`hata_${name}_ilk_goruntu_ve_uyari`, async () => {
    const p = page();
    p.radios[2].checked = true;
    p.radios[0].checked = false;
    type(p, PAN);
    assert.ok(p.fetches[0], 'beklenen fetch yapılmadı');
    fail(p.fetches[0]);
    await flush();
    assert.deepEqual(p.radios.map((r) => shown(r)), [true, true, true, true], 'ilk görüntü: tümü görünür');
    assert.equal(p.radios[2].checked, true, 'kullanıcının seçimi korunur');
    assert.equal(p.els['mo-bin-status'].textContent, WARN);
    assert.equal(p.els['mo-detected'].textContent, '');
    assert.equal(p.radios[2].dataset.total, FIRST[3][0], 'metinler ilk anlık görüntüde');
  });
}

test('alti_saniye_zaman_asimi_iptal_eder_ve_uyarir', async () => {
  const p = page();
  type(p, PAN);
  const timer = p.timeouts.find((t) => t.ms === 6000);
  assert.ok(timer, '6000 ms zaman aşımı kurulur');
  assert.ok(p.fetches[0], 'beklenen fetch yapılmadı');
  assert.equal(p.fetches[0].opts.signal.aborted, false);
  timer.fn();                                       // zaman aşımı dolar
  p.fetches[0].reject(Object.assign(new Error('abort'), { name: 'AbortError' }));
  await flush();
  assert.equal(p.fetches[0].opts.signal.aborted, true);
  assert.equal(p.els['mo-bin-status'].textContent, WARN);
});

test('gec_gelen_eski_yanit_yeni_bini_bozmaz', async () => {
  const p = page();
  type(p, BIN);                                     // istek 1
  type(p, '52828282');                              // istek 2
  assert.equal(p.fetches.length, 2);
  reply(p.fetches[1], DEBIT);
  await flush();
  reply(p.fetches[0], CREDIT);                      // eski yanıt geç gelir
  await flush();
  assert.equal(p.els['mo-detected'].textContent, 'Akbank · Banka kartı', 'eski yanıt yok sayıldı');
  assert.deepEqual(p.radios.map((r) => shown(r)), [true, false, false, false]);
});

test('gec_gelen_yanit_pan_8_haneden_asagi_inmisse_uygulanmaz', async () => {
  const p = page();
  type(p, BIN);
  type(p, '4355');
  reply(p.fetches[0], DEBIT);
  await flush();
  assert.deepEqual(p.radios.map((r) => shown(r)), [true, true, true, true]);
  assert.equal(p.els['mo-detected'].textContent, '');
});

test('pan_8_haneden_asagi_inince_ilk_goruntu_ve_temizlik', async () => {
  const p = page();
  type(p, PAN);
  reply(p.fetches[0], DEBIT);
  await flush();
  assert.equal(p.els['mo-detected'].textContent, 'Akbank · Banka kartı');
  type(p, '4355 084');
  assert.deepEqual(p.radios.map((r) => shown(r)), [true, true, true, true]);
  assert.equal(p.els['mo-detected'].textContent, '');
  assert.equal(p.els['mo-bin-status'].textContent, '');
  assert.equal(p.els['mo-inst-note'].textContent, '');
  assert.equal(p.radios[2].dataset.total, FIRST[3][0], 'metinler ilk görüntüye döndü');
});

test('hata_sonrasi_pan_kisalinca_uyari_temizlenir', async () => {
  const p = page();
  type(p, PAN);
  reply(p.fetches[0], { ok: false }, 502);
  await flush();
  assert.equal(p.els['mo-bin-status'].textContent, WARN);
  type(p, '4355');
  assert.equal(p.els['mo-bin-status'].textContent, '');
});

test('betik_boyutu_12_kb_ve_tek_fetch_ve_yerel_veri_yok', () => {
  assert.ok(Buffer.byteLength(SOURCE, 'utf8') <= 12288, 'betik <= 12 KB');
  assert.equal((SOURCE.match(/\bfetch\b/g) || []).length, 1, 'tek fetch');
  assert.equal((SOURCE.match(/localStorage|sessionStorage|indexedDB|sendBeacon|XMLHttpRequest|WebSocket/g) || []).length, 0);
  assert.ok(SOURCE.includes(BIN_PATH));
});

// A2-G3 kardeş yollar (sözleşme S1-S4)
test('ayni_bin_hata_sonrasi_yeniden_sorulur', async () => {
  const p = page();
  type(p, BIN);
  reply(p.fetches[0], { ok: false, error: 'provider' }, 502);
  await flush();
  type(p, '4355');
  type(p, BIN);                                     // S1: hata önbelleğe girmez
  assert.equal(p.fetches.length, 2, 'hata sonrası aynı BIN bir kez daha sorulur');
  reply(p.fetches[1], CREDIT);
  await flush();
  assert.equal(p.els['mo-detected'].textContent, CREDIT.detected);
  type(p, '4355');
  type(p, BIN);                                     // başarılı yanıt önbellekte
  await flush();
  assert.equal(p.fetches.length, 2);
});

test('zaman_asimi_sonrasi_ayni_bin_yeniden_sorulur', async () => {
  const p = page();
  type(p, BIN);
  p.timeouts.find((t) => t.ms === 6000).fn();
  p.fetches[0].reject(Object.assign(new Error('abort'), { name: 'AbortError' }));
  await flush();
  type(p, '4355');
  type(p, BIN);
  assert.equal(p.fetches.length, 2);
});

test('bekleyen_bin_yeniden_yazilinca_cift_istek_yok', async () => {
  const p = page();
  type(p, BIN);
  type(p, '4355');
  type(p, BIN);                                     // ilk istek hâlâ sürüyor
  assert.equal(p.fetches.length, 1, 'aynı anda tek istek');
  assert.equal(p.els['mo-bin-status'].textContent, 'Taksitler yükleniyor…');
  reply(p.fetches[0], DEBIT);
  await flush();
  assert.equal(p.els['mo-detected'].textContent, DEBIT.detected, 'bekleyen yanıt güncel BIN için uygulanır');
});

test('sure_dolmussa_bin_istegi_yok', async () => {
  const p = page();
  p.clock.t += 2701 * 1000;
  for (const fn of p.doc.listeners.visibilitychange) fn();
  assert.equal(p.els['mo-pay'].disabled, true, 'süre doldu');
  type(p, PAN);
  await flush();
  assert.equal(p.fetches.length, 0);
});

test('tek_radyo_bin_yeni_kart_eklemez', async () => {
  const p = page({ counts: [1] });
  type(p, PAN);
  reply(p.fetches[0], CREDIT);
  await flush();
  assert.equal(p.radios.length, 1);
  assert.deepEqual(p.radios.map((r) => shown(r)), [true]);
  assert.equal(p.els['mo-detected'].textContent, CREDIT.detected);
});

for (const id of ['mo-bin-status', 'mo-detected', 'mo-inst-note']) {
  test(`yuva_eksikse_bin_kapali_a1_calisir_${id}`, async () => {
    const p = page({ omit: [id] });
    assert.ok(p.html.classes.has('mo-js'), 'betik kuruldu');
    type(p, PAN);
    await flush();
    assert.equal(p.fetches.length, 0);
    assert.equal(p.els.pan.value, '4355 0843 5508 4358');
  });
}

for (const pid of ['', '0', 'abc']) {
  test(`payment_id_gecersizse_bin_kapali_${pid || 'bos'}`, async () => {
    const p = page({ pid });
    assert.ok(p.html.classes.has('mo-js'));
    type(p, PAN);
    await flush();
    assert.equal(p.fetches.length, 0);
  });
}

test('secim_degisince_tek_cekim_notu_temizlenir', async () => {
  const p = page();
  p.radios[3].checked = true;
  p.radios[0].checked = false;
  type(p, PAN);
  reply(p.fetches[0], CREDIT);
  await flush();
  assert.match(p.els['mo-inst-note'].textContent, /6 taksiti desteklemiyor/);
  p.radios[0].checked = false;
  p.radios[2].checked = true;
  p.els['mo-form'].fire('change', { target: p.radios[2] });
  assert.equal(p.els['mo-inst-note'].textContent, '', 'S3: not temizlendi');
  assert.equal(p.els['mo-sum-total'].textContent, '1.020,00 TL');
});

test('kart_numarasinin_tamami_ve_cvv_aga_gitmez', async () => {
  const p = page();
  p.els.cvv.value = '123';
  type(p, PAN);
  const blob = JSON.stringify(p.fetches.map((f) => [f.url, f.opts]));
  assert.ok(!blob.includes(PAN));
  assert.ok(!blob.includes('123"'));
  assert.ok(p.fetches[0], 'beklenen fetch yapılmadı');
  assert.equal(JSON.parse(p.fetches[0].opts.body).bin.length, 8);
});
