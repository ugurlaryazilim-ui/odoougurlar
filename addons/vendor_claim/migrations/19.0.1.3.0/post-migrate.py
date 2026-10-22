"""19.0.1.3.0: "Kullanıcı" grubu geldi; erişim artık base.group_user'a değil bu gruba bağlı.
Yükseltmede mevcut TÜM aktif iç kullanıcılar BİR KEZ gruba alınır (erişimleri kesilmesin). Sonradan
kaldırılanlara tekrar eklenmez: migrate yalnız bir kez çalışır. Taze kurulumda çalışmaz (yönetici atar)."""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def grant_internal_users(env):
    group = env.ref('vendor_claim.group_vendor_claim_user')
    users = env['res.users'].with_context(active_test=True).search([('share', '=', False)]) - group.user_ids
    if users:
        # DIKKAT: implied_ids ile base.group_user'a bağlamak değil, tek seferlik ekleme bilinçli (ayrım için)
        group.write({'user_ids': [(4, uid) for uid in users.ids]})
    _logger.info('vendor_claim: %s iç kullanıcı "Kullanıcı" grubuna eklendi', len(users))
    return users


def migrate(cr, version):
    grant_internal_users(api.Environment(cr, SUPERUSER_ID, {}))
