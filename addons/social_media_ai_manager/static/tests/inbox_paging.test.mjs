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
const onWillStart = () => {}, onMounted = () => {}, onPatched = () => {}, onWillUnmount = () => {};
const useRef = () => ({ el: null });
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
