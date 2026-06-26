from . import models
from . import wizards
from . import controllers


def _post_init_hook(env):
    """
    Cron kaydını noupdate=1 olmasına rağmen programatik olarak güncelle.

    ir_cron.xml noupdate=1 ile tanımlı olduğu için modül upgrade sırasında
    XML'deki değişiklikler uygulanmaz. Bu hook cron kaydını yeni model
    referansıyla programatik olarak günceller.
    """
    cron = env.ref('ugurlar_images.ir_cron_fix_existing_images', raise_if_not_found=False)
    if cron:
        model = env['ir.model'].search([('model', '=', 'image.fix.job')], limit=1)
        if model:
            cron.write({
                'model_id': model.id,
                'code': 'model._cron_fix_images()',
            })
