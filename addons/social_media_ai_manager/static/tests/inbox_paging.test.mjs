// K4: Inbox sayfalama (görüşme 100 / mesaj 200 ilk sayfa; "daha fazla yükle" ile devamı).
// Çalıştırma: node --test addons/social_media_ai_manager/static/tests/inbox_paging.test.mjs
// NEDEN: OWL/Odoo içe aktarmaları (@odoo/owl, @web/...) düğümde yok; import satırları silinip yerine aşağıdaki
// sahte sürümler konur. Sahte orm.searchRead sunucunun "en yeni önce + limit" davranışını taklit eder.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const raw = readFileSync(resolve(here, '../src/components/inbox/inbox.js'), 'utf8');
const stubs = `
const Component = class {};
const useState = (x) => x;
const onWillStart = () => {}, onMounted = () => {}, onWillUnmount = () => {};
const onPatched = (cb) => { globalThis.__onPatched = cb; };
const useRef = () => globalThis.__ref;
const registry = { category: () => ({ add: () => {} }) };
const useService = () => globalThis.__orm;
const _t = (s) => s;
const user = { lang: 'tr_TR' };
const openCameraScanner = () => {};
`;
const source = stubs + raw.replace(/^import .*$/gm, '');
const { SocialInbox } = await import('data:text/javascript;base64,' + Buffer.from(source, 'utf8').toString('base64'));

// En yeni kayıt önce (id azalan); gerçek sorgunun "date desc, id desc" sırasını temsil eder.
function fakeOrm(convCount, msgCount) {
    const convs = Array.from({ length: convCount }, (_, i) => ({ id: i + 1, name: `C${i + 1}` })).reverse();
    const msgs = Array.from({ length: msgCount }, (_, i) => ({ id: i + 1, content: `M${i + 1}` })).reverse();
    return {
        searchRead: async (model, domain, fields, opts) =>
            (model === 'social.media.conversation' ? convs : msgs).slice(0, opts.limit),
        call: async () => true,
    };
}
const make = (convCount, msgCount) => {
    globalThis.__ref = { el: null };
    globalThis.__orm = fakeOrm(convCount, msgCount);
    const inbox = new SocialInbox();
    inbox.setup();
    return inbox;
};

test('K4: 100 görüşmede ilk sayfa aynı, "daha fazla" yok (limit+1 sınırı)', async () => {
    const inbox = make(100, 0);
    await inbox.loadConversations();
    assert.equal(inbox.state.conversations.length, 100);
    assert.equal(inbox.state.hasMoreConvs, false);
});

test('K4: 250 görüşme: 100 → 200 → 250; yoklama yüklenmiş sayfayı korur; en eskiye ulaşılır', async () => {
    const inbox = make(250, 0);
    await inbox.loadConversations();
    assert.equal(inbox.state.conversations.length, 100);
    assert.equal(inbox.state.hasMoreConvs, true);
    await inbox.loadMoreConversations();
    assert.equal(inbox.state.conversations.length, 200);
    assert.equal(inbox.state.hasMoreConvs, true);
    await inbox.loadConversations();   // 10 sn'lik yoklama
    assert.equal(inbox.state.conversations.length, 200, 'yoklama yüklenmiş sayfayı kaybetti');
    await inbox.loadMoreConversations();
    assert.equal(inbox.state.conversations.length, 250);
    assert.equal(inbox.state.hasMoreConvs, false);
    assert.ok(inbox.state.conversations.some((c) => c.id === 1), 'en eski görüşmeye ulaşılamadı');
});

test('K4: 450 mesaj: son 200 artan sırada, sonra 400, sonra 450; en eski mesaj görünür', async () => {
    const inbox = make(1, 450);
    await inbox.loadMessages(1);
    assert.equal(inbox.state.messages.length, 200);
    assert.equal(inbox.state.hasMoreMsgs, true);
    assert.equal(inbox.state.messages.at(-1).id, 450, 'en yeni mesaj sonda olmalı');
    assert.ok(inbox.state.messages[0].id < inbox.state.messages.at(-1).id, 'artan sıra');
    inbox.state.activeConversation = { id: 1 };
    await inbox.loadMoreMessages();
    assert.equal(inbox.state.messages.length, 400);
    await inbox.loadMoreMessages();
    assert.equal(inbox.state.messages.length, 450);
    assert.equal(inbox.state.hasMoreMsgs, false);
    assert.equal(inbox.state.messages[0].id, 1);
});

test('K4: tam 200 mesajlı görüşmede "önceki mesajlar" düğmesi çıkmaz', async () => {
    const inbox = make(1, 200);
    await inbox.loadMessages(1);
    assert.equal(inbox.state.messages.length, 200);
    assert.equal(inbox.state.hasMoreMsgs, false);
});

test('K4: başka görüşmeye geçince mesaj sayfalaması baştan başlar', async () => {
    const inbox = make(2, 450);
    inbox.state.conversations = [{ id: 1, unread_count: 0 }, { id: 2, unread_count: 0 }];
    await inbox.selectConversation(1);
    await inbox.loadMoreMessages();
    assert.equal(inbox.state.messages.length, 400);
    await inbox.selectConversation(2);
    assert.equal(inbox.state.messages.length, 200);
});

// A5 B1/B2: kaydırma konumu. Sahte sohbet kutusu: her mesaj 100 px, yükseklik state.messages'tan türer (yama = DOM büyümesi).
function withBox(inbox) {
    const el = {
        scrollTop: 0,
        clientHeight: 400,
        get scrollHeight() { return inbox.state.messages.length * 100; },
    };
    globalThis.__ref.el = el;
    return el;
}
const patched = () => globalThis.__onPatched();

test('B1: "önceki mesajları yükle" sonrası okunan konum korunur, alta atlamaz', async () => {
    const inbox = make(1, 450);
    const el = withBox(inbox);
    inbox.state.activeConversation = { id: 1 };
    await inbox.loadMessages(1);
    patched();                       // ilk çizim: en alta
    assert.equal(el.scrollTop, 20000);
    el.scrollTop = 0;                // kullanıcı en üste kaydırdı
    await inbox.loadMoreMessages();  // 200 → 400 mesaj (üste 200 mesaj = 20000 px eklendi)
    patched();
    assert.equal(el.scrollTop, 20000, 'okunan satır yerinde kalmalı (yeni - eski yükseklik)');
    assert.notEqual(el.scrollTop, el.scrollHeight, 'en alta atlamamalı');
});

test('B1: araya giren görüşme listesi yaması kaydırma niyetini harcamaz', async () => {
    const inbox = make(1, 450);
    const el = withBox(inbox);
    inbox.state.activeConversation = { id: 1 };
    await inbox.loadMessages(1);
    patched();
    el.scrollTop = 0;
    const pending = inbox.loadMoreMessages();
    patched();                       // mesajlar gelmeden başka bir yama (örn. yoklamanın görüşme listesi)
    assert.equal(el.scrollTop, 0, 'mesajlar gelmeden konuma dokunulmamalı');
    await pending;
    patched();
    assert.equal(el.scrollTop, 20000);
});

test('B2: yoklama, kullanıcı alttaysa yeni mesajda alta kaydırır', async () => {
    const inbox = make(1, 50);
    const el = withBox(inbox);
    inbox.state.activeConversation = { id: 1 };
    await inbox.loadMessages(1);
    patched();
    assert.equal(el.scrollTop, 5000);
    el.scrollTop = 4600;             // alt sınırda (yükseklik 5000 - görünür 400)
    inbox.orm = fakeOrm(1, 51);
    await inbox._pollOnce();
    patched();
    assert.equal(el.scrollTop, 5100, 'alttaki kullanıcı yeni mesajı görmeli');
});

test('B2: yoklama, geçmişi okuyan kullanıcının konumunu bozmaz', async () => {
    const inbox = make(1, 50);
    const el = withBox(inbox);
    inbox.state.activeConversation = { id: 1 };
    await inbox.loadMessages(1);
    patched();
    el.scrollTop = 1000;
    inbox.orm = fakeOrm(1, 51);   // yeni mesaj geldi
    await inbox._pollOnce();
    patched();
    assert.equal(el.scrollTop, 1000);
    await inbox._pollOnce();             // yeni mesaj yok
    patched();
    assert.equal(el.scrollTop, 1000);
    patched();                           // niyet yokken yama (örn. başka state) konuma dokunmaz
    assert.equal(el.scrollTop, 1000);
});
