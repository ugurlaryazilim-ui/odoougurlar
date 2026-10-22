# -*- coding: utf-8 -*-
import hmac as _hmac
import re
import secrets as _secrets
import time

from werkzeug.exceptions import Forbidden

from odoo.tools.misc import hmac as odoo_hmac


def require_system_user(env):
    """OAuth login/callback uçları: hesaba jeton yazan akış yalnız sistem yöneticisine açıktır (A5 O1)."""
    if not env.user.has_group('base.group_system'):
        raise Forbidden()

# NEDEN (A5 O1): OAuth `state` eskiden düz hesap id'siydi; herhangi bir kullanıcı (ya da kullanıcıya
# tıklatılan bağlantı, login CSRF) kendi Google/TikTok kodunu şirket hesabına yazdırabiliyordu.
# state = hesap.uid.zaman.nonce.imza; imza database.secret ile (odoo.tools.misc.hmac), kapsam sağlayıcıya özel.
OAUTH_STATE_TTL = 900  # sn: giriş akışı bu sürede tamamlanmalı


def make_oauth_state(env, provider, account_id):
    payload = '%d.%d.%d.%s' % (int(account_id), env.uid, int(time.time()), _secrets.token_hex(8))
    return '%s.%s' % (payload, odoo_hmac(env(su=True), 'social_oauth_' + provider, payload))


def check_oauth_state(env, provider, state):
    """Geçerli ve bu kullanıcıya ait state ise hesap id'sini, değilse None döndürür."""
    try:
        account_id, uid, issued, nonce, sig = str(state or '').split('.')
        account_id, uid, issued = int(account_id), int(uid), int(issued)
    except ValueError:
        return None
    payload = '%d.%d.%d.%s' % (account_id, uid, issued, nonce)
    expected = odoo_hmac(env(su=True), 'social_oauth_' + provider, payload)
    if not _hmac.compare_digest(expected, sig) or uid != env.uid:
        return None
    if not 0 <= time.time() - issued <= OAUTH_STATE_TTL:
        return None
    return account_id

# NEDEN: requests'in ConnectionError metni urllib3 MaxRetryError'ı içerir ve sorgu dizesini (access_token=..., client_secret=...)
# aynen taşır. Sırlar gövdeye (data=) / başlığa taşınsa da eski/dış kaynaklı metinler için ikinci savunma olarak maskelenir.
_SECRET_QS = re.compile(
    r'(?i)\b(access_token|client_secret|fb_exchange_token|refresh_token|client_key|apikey)=[^&\s\'"<>)]+')


def mask_secrets(text, *secrets):
    """Metindeki bilinen sır değerlerini ve URL sorgu dizesindeki token/secret parametrelerini '***' yapar."""
    text = str(text)
    for secret in secrets:
        if secret and len(secret) >= 4:
            text = text.replace(secret, '***')
    return _SECRET_QS.sub(r'\1=***', text)
