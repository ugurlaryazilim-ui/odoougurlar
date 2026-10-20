// Yer tutucu ekleme mantığı. Çalıştırma: node --test "addons/sms_system/static/tests/*.test.mjs"
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const source = readFileSync(resolve(here, '../src/js/placeholder_utils.js'), 'utf8');
const { insertToken } = await import(
    'data:text/javascript;base64,' + Buffer.from(source, 'utf8').toString('base64'));

test('imleç ortadaysa tam oraya eklenir ve imleç yer tutucunun sonuna gider', () => {
    assert.deepEqual(insertToken('Sayın , merhaba', '{ad}', 6, 6), { value: 'Sayın {ad}, merhaba', caret: 10 });
});

test('imleç bilgisi yoksa (alana hiç tıklanmamış) sona eklenir', () => {
    assert.deepEqual(insertToken('Sayın ', '{ad}'), { value: 'Sayın {ad}', caret: 10 });
    assert.deepEqual(insertToken('Sayın ', '{ad}', null, null), { value: 'Sayın {ad}', caret: 10 });
});

test('seçili metin yer tutucuyla değişir', () => {
    assert.deepEqual(insertToken('Merhaba X!', '{ad}', 8, 9), { value: 'Merhaba {ad}!', caret: 12 });
});

test('boş metne eklenir', () => {
    assert.deepEqual(insertToken('', '{ad}', 0, 0), { value: '{ad}', caret: 4 });
    assert.deepEqual(insertToken(null, '{ad}'), { value: '{ad}', caret: 4 });
});

test('taşan ya da ters konumlar metne sıkıştırılır', () => {
    assert.deepEqual(insertToken('abc', '{ad}', 99, 120), { value: 'abc{ad}', caret: 7 });
    assert.deepEqual(insertToken('abc', '{ad}', -5, -1), { value: '{ad}abc', caret: 4 });
    assert.deepEqual(insertToken('abc', '{ad}', 2, 1), { value: 'ab{ad}c', caret: 6 });
});

test('satır sonu ve Türkçe karakterli metinde konum karakter sayısıdır', () => {
    assert.deepEqual(insertToken('Şükrü\nGüle', '{ad}', 6, 6), { value: 'Şükrü\n{ad}Güle', caret: 10 });
});
