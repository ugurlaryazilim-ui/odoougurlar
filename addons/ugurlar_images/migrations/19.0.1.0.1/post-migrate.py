"""
Migrate cron job from res.config.settings (TransientModel)
to image.fix.job (persistent Model).

post_init_hook only runs on first install — this migration script
ensures the cron record is updated during module upgrade as well.
"""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    _logger.info(
        "ugurlar_images migration %s: Updating cron to image.fix.job model...",
        version,
    )

    # 1. Get the ir.model ID for image.fix.job
    cr.execute(
        "SELECT id FROM ir_model WHERE model = 'image.fix.job' LIMIT 1"
    )
    row = cr.fetchone()
    if not row:
        _logger.warning("image.fix.job model not found — migration skipped.")
        return

    new_model_id = row[0]

    # 2. Find the cron's server action via the ir.model.data external ID
    cr.execute("""
        SELECT res_id FROM ir_model_data
        WHERE module = 'ugurlar_images'
          AND name = 'ir_cron_fix_existing_images'
        LIMIT 1
    """)
    cron_row = cr.fetchone()
    if not cron_row:
        _logger.warning("Cron record not found — migration skipped.")
        return

    cron_id = cron_row[0]

    # 3. Get the server action ID linked to the cron
    cr.execute(
        "SELECT ir_actions_server_id FROM ir_cron WHERE id = %s",
        (cron_id,)
    )
    action_row = cr.fetchone()
    if not action_row:
        _logger.warning("Cron action not found — migration skipped.")
        return

    server_action_id = action_row[0]

    # 4. Update the server action to point to the new model and code
    cr.execute("""
        UPDATE ir_act_server
           SET model_id = %s,
               code = 'model._cron_fix_images()'
         WHERE id = %s
    """, (new_model_id, server_action_id))

    # 5. Deactivate the cron (user will re-activate via the button)
    cr.execute("""
        UPDATE ir_cron
           SET active = FALSE
         WHERE id = %s
    """, (cron_id,))

    _logger.info(
        "ugurlar_images migration: Cron (id=%s, action=%s) updated to "
        "model_id=%s (image.fix.job), code='model._cron_fix_images()'",
        cron_id, server_action_id, new_model_id,
    )
