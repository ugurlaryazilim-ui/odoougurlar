/* Mail Order kart sayfası betiği (K-16, tasarım §3.5).
 * DIKKAT: assets'e eklenmez; tools.mail_order_script() satır içi basar, sha256'sı CSP'dedir. Her
 * değişiklik kod incelemesi + SCRIPT_SHA256 (test_mail_order_pci) ister. Ağ/depolama/console/HTML
 * yazımı yok; CVV değeri okunmaz. Desen gevşetme ve mo-js EN SONDA (yarım kurulum = script'siz). */
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
        if (!checkAll()) {
          for (var j = 0; j < inputs.length; j++) {
            if (inputs[j].getAttribute('aria-invalid')) { inputs[j].focus(); break; }
          }
          return;
        }
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
      if (e.target && e.target.name === 'installmentCount') { onInst(); }
    });
    inputs.forEach(function (el, k) {
      el.addEventListener('blur', function () { if (ready) { checks[k](); } });
      el.addEventListener(k === 2 || k === 3 ? 'change' : 'input', function () {
        if (ready && el.getAttribute('aria-invalid')) { checks[k](); }
      });
    });
    /* Yerel doğrulama submit'ten önce engeller; hata satırları yine görünsün (KK-1.9). */
    form.addEventListener('invalid', function () { if (ready) { checkAll(); } }, true);
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
