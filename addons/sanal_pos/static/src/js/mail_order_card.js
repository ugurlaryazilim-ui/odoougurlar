/* Mail Order kart sayfası betiği (K-16, tasarım §3.5).
 * DIKKAT: assets'e eklenmez; tools.mail_order_script() satır içi basar, sha256'sı CSP'dedir. Her
 * değişiklik kod incelemesi + SCRIPT_SHA256 (test_mail_order_pci) ister. Tek ağ isteği BIN ucuna (ilk
 * 8 hane, §4.7); depolama/console/HTML yazımı yok; CVV değeri okunmaz. Desen gevşetme ve mo-js EN
 * SONDA (yarım kurulum = script'siz). */
(function () {
  'use strict';
  var D = document;
  function $(id) { return D.getElementById(id); }
  function digits(s) { return String(s || '').replace(/\D/g, ''); }

  function luhn(n) {
    var sum = 0;
    for (var i = n.length - 1, dbl = false; i >= 0; i--, dbl = !dbl) {
      var d = n.charCodeAt(i) - 48;
      if (dbl) { d = d * 2 > 9 ? d * 2 - 9 : d * 2; }
      sum += d;
    }
    return sum % 10 === 0;
  }

  function brand(n) {
    var p4 = n.length >= 4 ? +n.slice(0, 4) : 0;
    if (/^4/.test(n)) { return 'visa'; }
    if (/^5[1-5]/.test(n) || (p4 >= 2221 && p4 <= 2720)) { return 'mastercard'; }
    return /^9792/.test(n) ? 'troy' : '';
  }

  function init() {
    var form = $('mo-form'), pan = $('pan'), owner = $('cardOwner');
    var month = $('expiryMonth'), year = $('expiryYear'), cvv = $('cvv');
    var pay = $('mo-pay'), payText = $('mo-pay-text'), sumTotal = $('mo-sum-total');
    var sumDetail = $('mo-sum-detail'), remain = $('mo-remaining'), expired = $('mo-expired');
    var amex = $('mo-amex'), formErr = $('mo-form-error'), cards = D.querySelector('.mo-cards');
    var errs = {o: $('cardOwner-error'), p: $('pan-error'), e: $('expiry-error'), c: $('cvv-error')};
    if ([form, pan, owner, month, year, cvv, pay, payText, sumTotal, sumDetail, remain, expired,
      amex, formErr, cards, errs.o, errs.p, errs.e, errs.c].indexOf(null) >= 0) { return; }
    var radios = form.querySelectorAll('input[name="installmentCount"]');
    var nowYm = form.dataset.nowYm || '', secs0 = parseInt(remain.dataset.seconds, 10);
    if (!radios.length || !/^\d{4}-\d{2}$/.test(nowYm) || !(secs0 >= 0)) { return; }

    var inputs = [owner, pan, month, year, cvv];
    var amountText = (sumTotal.textContent || '').trim();
    /* NEDEN: süre = sunucu saniyesi - monotonik fark (istemci saati kayabilir). */
    var t0 = performance.now();
    var ready = false, busy = false, isExpired = false, lastPan = '', timer = null;

    /* BIN (§4.7): koşullardan biri yoksa kapalı (A1 davranışı). snap: kartların açılış metni/data-*. */
    var binSt = $('mo-bin-status'), det = $('mo-detected'), note = $('mo-inst-note');
    var pid = +form.dataset.paymentId, want = '', cache = new Map(), snap = [], K = ['total', 'monthly', 'surcharge'];
    var binOn = form.dataset.bin === '1' && binSt && det && note && pid > 0;
    for (var i = 0; binOn && i < radios.length; i++) {
      var r = radios[i], c = r.closest('.mo-inst-card'), s = {r: r, c: c, d: {}, t: []};
      if (!c) { binOn = false; break; }
      K.forEach(function (k) { s.d[k] = r.dataset[k]; });
      ['amount', 'total', 'fee', 'networks'].forEach(function (k) {
        var el = c.querySelector('.mo-inst-' + k);
        if (el) { s.t.push([el, el.textContent, el.hidden, k]); }
      });
      snap.push(s);
    }
    function setD(d, k, v) { if (v) { d[k] = v; } else { delete d[k]; } }
    function reset() {
      snap.forEach(function (s) {
        s.c.hidden = false;
        for (var k in s.d) { setD(s.r.dataset, k, s.d[k]); }
        s.t.forEach(function (x) { x[0].textContent = x[1]; x[0].hidden = x[2]; });
      });
      det.textContent = binSt.textContent = note.textContent = '';
      onInst();
    }
    function apply(res) {
      var by = {}, sel = null, one = null;
      res.rows.forEach(function (w) { by[w.count] = w; });
      snap.forEach(function (s) {
        var n = +s.r.value, w = by[n];
        if (n === 1) { one = s.r; }
        if (s.r.checked) { sel = s; }
        /* NEDEN: Tek çekim hiç gizlenmez (seçilecek kart kalır); yeni kart üretilmez (R17). */
        s.c.hidden = !w && n !== 1;
        if (!w) { return; }
        K.forEach(function (k) { setD(s.r.dataset, k, w[k + '_text']); });
        s.t.forEach(function (x) {
          var k = x[3];
          if (k === 'networks') { x[0].hidden = true; return; }
          x[0].textContent = k === 'fee' ? (w.surcharge_text ? w.rate_text + ' · ' + w.surcharge_text : w.rate_text)
            : k === 'total' ? 'Toplam ' + w.total_text : (n > 1 ? w.monthly_text + ' / ay' : w.total_text);
        });
      });
      if (sel && sel.c.hidden && one) {
        sel.r.checked = false; one.checked = true;
        note.textContent = 'Bu kart ' + sel.r.value + ' taksiti desteklemiyor; tek çekim seçildi';
      }
      det.textContent = res.detected || '';
      binSt.textContent = res.note || '';
      onInst();
    }
    /* cache: 0 = istek sürüyor, nesne = başarılı yanıt. NEDEN: hata girmez, aynı BIN yeniden sorulur (S1). */
    function onBin(n) {
      var b = !isExpired && n.length >= 8 && !/^3[47]/.test(n) ? n.slice(0, 8) : '';
      if (!binOn || b === want) { return; }
      want = b;
      reset();
      if (!b) { return; }
      var v = cache.get(b);
      if (v) { apply(v); return; }
      binSt.textContent = 'Taksitler yükleniyor…';
      if (v === 0) { return; }
      cache.set(b, 0);
      var ac = new AbortController(), to = setTimeout(function () { ac.abort(); }, 6000);
      function end(j) {
        clearTimeout(to);
        j = j && j.ok === true && j.rows ? j : null;
        if (j) { cache.set(b, j); } else { cache.delete(b); }
        if (want !== b) { return; }   /* eski/geç yanıt uygulanmaz */
        if (j) { apply(j); } else {
          binSt.textContent = 'Kartın taksitleri doğrulanamadı; tüm seçenekler gösteriliyor, desteklenmeyen taksiti banka reddeder.';
        }
      }
      /* DIKKAT: tek ağ çağrısı; hedef sabit, gövde yalnız payment_id + 8 hane (KK-1.15/2.1). */
      fetch('/sanal_pos/mail_order/bin', {method: 'POST', credentials: 'same-origin', redirect: 'error',
        cache: 'no-store', referrerPolicy: 'no-referrer', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({payment_id: pid, bin: b}), signal: ac.signal})
        .then(function (q) { return q.ok ? q.json() : null; }).then(end, function () { end(null); });
    }

    function mark(key, fields, msg) {
      errs[key].textContent = msg;
      errs[key].hidden = !msg;
      for (var j = 0; j < fields.length; j++) {
        if (msg) { fields[j].setAttribute('aria-invalid', 'true'); } else { fields[j].removeAttribute('aria-invalid'); }
      }
      return !msg;
    }
    function chkOwner() { return mark('o', [owner], owner.value.trim() ? '' : 'Kart sahibinin adını girin'); }
    function chkPan() {
      var n = digits(pan.value);
      return mark('p', [pan], n.length < 12 || n.length > 19 ? 'Kart numarası 12-19 hane olmalı'
        : (luhn(n) ? '' : 'Kart numarası geçersiz (kontrol hanesi tutmuyor)'));
    }
    function chkExp() {
      var m = month.value, y = year.value;
      /* 'YYYY-MM' metin karşılaştırması; bu ay geçerli (KK-1.18). */
      return mark('e', [month, year], !m || !y ? 'Son kullanma ayını ve yılını seçin'
        : (y + '-' + m < nowYm ? 'Son kullanma tarihi geçmiş' : ''));
    }
    function chkCvv() { return mark('c', [cvv], cvv.validity.valid ? '' : 'CVV 3 hane olmalı'); }
    var checks = [chkOwner, chkPan, chkExp, chkExp, chkCvv];
    function checkAll() { return [chkOwner(), chkPan(), chkExp(), chkCvv()].indexOf(false) < 0; }
    function focusBad() {
      for (var j = 0; j < inputs.length; j++) {
        if (inputs[j].getAttribute('aria-invalid')) { inputs[j].focus(); return; }
      }
    }

    function onPan(e) {
      if (!ready) { return; }
      var v = pan.value, t = e && e.inputType;
      var before = digits(v.slice(0, pan.selectionStart == null ? v.length : pan.selectionStart)).length;
      var n = digits(v).slice(0, 19);
      /* NEDEN: silinen grup boşluğuysa yanındaki rakam silinir; yoksa imleç boşlukta takılır. */
      if (n === lastPan && t === 'deleteContentBackward' && before > 0) {
        n = n.slice(0, before - 1) + n.slice(before--);
      } else if (n === lastPan && t === 'deleteContentForward') {
        n = n.slice(0, before) + n.slice(before + 1);
      }
      lastPan = n;
      var g = n.replace(/(\d{4})(?=\d)/g, '$1 ');
      if (g !== v) {
        pan.value = g;
        var pos = 0;
        for (var seen = 0; pos < g.length && seen < before; pos++) { if (g.charAt(pos) !== ' ') { seen++; } }
        if (D.activeElement === pan) { pan.setSelectionRange(pos, pos); }
      }
      cards.dataset.brand = brand(n);
      amex.hidden = !/^3[47]/.test(n);   /* yalnız uyarı (S1.1); gönderimi engellemez */
      if (pan.getAttribute('aria-invalid')) { chkPan(); }
      onBin(n);
    }

    function onInst() {
      var r = null;
      for (var j = 0; j < radios.length; j++) { if (radios[j].checked) { r = radios[j]; } }
      if (!r || !r.dataset.total) { return; }
      var d = r.dataset, n = parseInt(r.value, 10);
      /* NEDEN: para hesabı yok; sunucu metni kopyalanır (KK-1.4). */
      payText.textContent = d.total + ' öde · 3D Secure';
      sumTotal.textContent = d.total;
      sumDetail.textContent = n > 1 ? 'Fatura tutarı ' + amountText + ' · ' +
        (d.surcharge ? 'Vade farkı ' + d.surcharge : 'Vade farkı yok') +
        ' · Çekilecek toplam ' + d.total + ' · ' + n + ' × ' + d.monthly : '';
      sumDetail.hidden = !(n > 1);
    }

    function tick() {
      var s = Math.max(0, secs0 - Math.floor((performance.now() - t0) / 1000));
      if (s > 0) { remain.textContent = Math.ceil(s / 60) + ' dk kaldı'; return; }
      isExpired = pay.disabled = true;
      expired.hidden = false;
      remain.textContent = 'Süre doldu';
      if (timer !== null) { clearInterval(timer); timer = null; }
    }

    /* DIKKAT: fail-closed (KK-1.16): ilk satır preventDefault, sonraki her hata gönderimi durdurur.
     * Prototip submit'i: 'submit' adlı alan gölgeleyemez, olay yeniden tetiklenmez. */
    function onSubmit(e) {
      e.preventDefault();
      try {
        if (busy) { return; }
        tick();
        if (isExpired) { return; }
        if (!checkAll()) { focusBad(); return; }
        pan.value = digits(pan.value);
        busy = pay.disabled = true;
        HTMLFormElement.prototype.submit.call(form);
      } catch (err) {
        formErr.textContent = 'Ödeme başlatılamadı; sayfayı yenileyip tekrar deneyin.';
        formErr.hidden = false;
      }
    }

    pan.addEventListener('input', onPan);
    form.addEventListener('change', function (e) {
      if (e.target && e.target.name === 'installmentCount') {
        if (binOn) { note.textContent = ''; }   /* KK-2.3 notu kullanıcı seçince bayatlar (S3) */
        onInst();
      }
    });
    inputs.forEach(function (el, k) {
      el.addEventListener('blur', function () { if (ready) { checks[k](); } });
      el.addEventListener(k === 2 || k === 3 ? 'change' : 'input', function () {
        if (ready && el.getAttribute('aria-invalid')) { checks[k](); }
      });
    });
    /* Yerel doğrulama submit'ten önce engeller; hata satırları görünsün (KK-1.9). NEDEN: satır
     * gösterildiyse yerel balon bastırılır (çift mesaj, G-6); engel kalkmaz, satır yoksa balon kalır. */
    form.addEventListener('invalid', function (e) {
      if (ready && !checkAll()) { e.preventDefault(); focusBad(); }
    }, true);
    window.addEventListener('pageshow', function (e) {
      if (e.persisted) { busy = false; tick(); pay.disabled = isExpired; }
    });
    D.addEventListener('visibilitychange', tick);
    form.addEventListener('submit', onSubmit);

    pan.setAttribute('pattern', '[0-9 ]{12,23}');
    pan.maxLength = 23;
    pan.placeholder = '0000 0000 0000 0000';
    ready = true;
    onPan(null);
    onInst();
    tick();
    if (!isExpired) { timer = setInterval(tick, 10000); }
    D.documentElement.classList.add('mo-js');
  }

  if (D.readyState === 'loading') { D.addEventListener('DOMContentLoaded', init); } else { init(); }
})();
