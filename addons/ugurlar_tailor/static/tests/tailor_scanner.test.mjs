// KK-B9 / KK-B10: TailorBarcodeScanner okutma kuyruğu.
// Çalıştırma: node --test addons/ugurlar_tailor/static/tests
// Süreler ölçeklidir (gerçek: dinleyici 500 ms / aralık 100 ms; burada 50 ms / 10 ms).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const source = readFileSync(resolve(here, '../src/js/tailor_scanner.js'), 'utf8');
const { TailorBarcodeScanner } = await import(
    'data:text/javascript;base64,' + Buffer.from(source, 'utf8').toString('base64'));

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const quiet = () => {
    const original = console.error;
    console.error = () => {};
    return () => { console.error = original; };
};
const codes = (n) => Array.from({ length: n }, (_, i) => `BRK${String(i).padStart(4, '0')}`);

test('KK-B9: yavaş dinleyici, hızlı okutma: 20 okutma sırasıyla işlenir, kayıp yok', async () => {
    const scanner = new TailorBarcodeScanner();
    const seen = [];
    scanner.onScan(async (code) => { await sleep(50); seen.push(code); });
    const list = codes(20);
    for (const code of list) {
        scanner.manualScan(code);
        await sleep(10);
    }
    await sleep(20 * 50 + 600);
    assert.deepEqual(seen, list);
});

test('KK-B9: 100 eşzamanlı okutma kayıpsız ve sıralı işlenir', async () => {
    const scanner = new TailorBarcodeScanner();
    const seen = [];
    scanner.onScan(async (code) => { await sleep(1); seen.push(code); });
    const list = codes(100);
    for (const code of list) scanner.manualScan(code);
    await sleep(100 * 1 + 1500);
    assert.deepEqual(seen, list);
});

test('KK-B9: senkron dinleyici ile 100 okutma sıralı', async () => {
    const scanner = new TailorBarcodeScanner();
    const seen = [];
    scanner.onScan((code) => { seen.push(code); });
    const list = codes(100);
    for (const code of list) scanner.manualScan(code);
    await sleep(1500);
    assert.deepEqual(seen, list);
});

test('KK-B9: dinleyiciler her okutmada okutma sırasıyla, her biri bir kez çağrılır', async () => {
    const scanner = new TailorBarcodeScanner();
    const a = [];
    const b = [];
    scanner.onScan(async (c) => { await sleep(5); a.push(c); });
    scanner.onScan((c) => { b.push(c); });
    const list = codes(5);
    for (const code of list) scanner.manualScan(code);
    await sleep(1000);
    assert.deepEqual(a, list);
    assert.deepEqual(b, list);
});

test('KK-B10: dinleyici hata fırlatsa da sonraki okutma işlenir', async () => {
    const restore = quiet();
    try {
        const scanner = new TailorBarcodeScanner();
        const seen = [];
        scanner.onScan((code) => {
            seen.push(code);
            if (code === 'BAD0001') throw new Error('patladı');
        });
        scanner.manualScan('BAD0001');
        scanner.manualScan('OKK0002');
        scanner.manualScan('OKK0003');
        await sleep(1000);
        assert.deepEqual(seen, ['BAD0001', 'OKK0002', 'OKK0003']);
    } finally {
        restore();
    }
});

test('KK-B10: asenkron reddeden dinleyici de kuyruğu tıkamaz', async () => {
    const restore = quiet();
    try {
        const scanner = new TailorBarcodeScanner();
        const seen = [];
        scanner.onScan(async (code) => {
            seen.push(code);
            if (code === 'BAD0001') throw new Error('reddedildi');
        });
        scanner.manualScan('BAD0001');
        scanner.manualScan('OKK0002');
        await sleep(1000);
        assert.deepEqual(seen, ['BAD0001', 'OKK0002']);
    } finally {
        restore();
    }
});

test('KK-B10: tek okutmada dinleyici tam 1 kez çağrılır', async () => {
    const scanner = new TailorBarcodeScanner();
    const seen = [];
    scanner.onScan((code) => { seen.push(code); });
    scanner.manualScan('TEK00001');
    await sleep(800);
    assert.deepEqual(seen, ['TEK00001']);
});

test('KK-B10: kuyruk boşaldıktan sonra yeni okutma işlenir ve abonelik iptali çalışır', async () => {
    const scanner = new TailorBarcodeScanner();
    const seen = [];
    const off = scanner.onScan((code) => { seen.push(code); });
    scanner.manualScan('ILK00001');
    await sleep(800);
    scanner.manualScan('IKI00002');
    await sleep(800);
    assert.deepEqual(seen, ['ILK00001', 'IKI00002']);
    off();
    scanner.manualScan('UCU00003');
    await sleep(500);
    assert.deepEqual(seen, ['ILK00001', 'IKI00002']);
});
