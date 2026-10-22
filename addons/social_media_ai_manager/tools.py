# -*- coding: utf-8 -*-
import re

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
