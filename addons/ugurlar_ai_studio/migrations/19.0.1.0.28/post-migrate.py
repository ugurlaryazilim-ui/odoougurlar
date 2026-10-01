import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)

# İlk sürümlerden kalan lock'lar. noupdate="1" yüklendikleri için data dosyasındaki
# active=False güncellemesi hiç uygulanmadı: canlıda hepsi prompta ekleniyor ve
# 60-90 kelimelik şablonu ~1500 kelimeye, birbirini tutmayan talimatlarla şişiriyordu.
OBSOLETE_LOCKS = (
    'prompt_anatomy_lock', 'prompt_garment_lock', 'prompt_anti_hallucination',
    'prompt_full_outfit_lock', 'prompt_negative_unified', 'prompt_studio_env_lock',
    'prompt_color_lock', 'prompt_fabric_lock', 'prompt_button_lock',
    'prompt_idealization_lock', 'prompt_identity_lock', 'prompt_editorial_style',
    'prompt_back_view_lock', 'prompt_detail_view_lock', 'prompt_capture_lock',
    'prompt_anti_plastic_lock', 'prompt_hair_lock', 'prompt_shoulder_drape_lock',
    'prompt_social_identity_lock',
)
REALISM_TEXT = ('Photorealistic editorial fashion photograph, natural skin texture, '
                'true-to-life fabric detail.')


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    Template = env['ai.studio.prompt.template'].with_context(active_test=False)
    imd = env['ir.model.data'].sudo()

    rows = imd.search([('module', '=', 'ugurlar_ai_studio'),
                       ('model', '=', 'ai.studio.prompt.template'),
                       ('name', 'in', list(OBSOLETE_LOCKS))])
    # Kayıtlar artık XML'de yok: noupdate=True kalmalı ki güncelleme sonunda silinmesin
    # (pasif dururlar, "Prompt Şablonları" menüsünden gerekirse yeniden açılabilir)
    rows.write({'noupdate': True})
    locks = Template.browse(rows.mapped('res_id')).exists()
    active = locks.filtered('active')
    if active:
        _logger.info('ugurlar_ai_studio: %d eski prompt lock pasifleştiriliyor: %s',
                     len(active), ', '.join(active.mapped('name')))
        active.write({'active': False})

    realism = env.ref('ugurlar_ai_studio.prompt_realism_lock', raise_if_not_found=False)
    if realism:
        realism = realism.with_context(active_test=False)
        if (realism.prompt_text or '').strip() != REALISM_TEXT or not realism.active:
            _logger.info('ugurlar_ai_studio: fotorealizm lock kısa metne çevrildi (eski %d karakter)',
                         len(realism.prompt_text or ''))
            realism.write({'prompt_text': REALISM_TEXT, 'active': True})

    # Elle eklenmiş başka global lock varsa dokunma, yalnızca bildir
    others = env['ai.studio.prompt.template'].search([('scope', '=', 'global')]) - realism
    if others:
        _logger.warning('ugurlar_ai_studio: elle eklenmiş %d aktif global lock prompta eklenmeye devam edecek: %s',
                        len(others), ', '.join(others.mapped('name')))
