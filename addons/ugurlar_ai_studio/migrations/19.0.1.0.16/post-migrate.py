import logging

_logger = logging.getLogger(__name__)

REJECT_REASONS_EN = {'reject_fabric_wrong': 'Render the fabric texture exactly as in the product photo, with realistic weave and structure', 'reject_color_mismatch': 'Match the garment color exactly to the product photo, same hue and saturation', 'reject_pose_unnatural': 'Use a natural, relaxed standing pose', 'reject_hand_error': 'Hands are natural with five correctly shaped fingers each', 'reject_face_issue': 'Natural, calm and professional facial expression', 'reject_detail_lost': 'Preserve every product detail, print and embellishment exactly as in the product photo', 'reject_background_issue': 'Clean, uniform white studio background', 'reject_proportion_wrong': 'Garment length, fit and proportions exactly match the product photo', 'reject_low_quality': 'Sharp, high-detail professional catalog photo'}


def migrate(cr, version):
    """cron.xml noupdate=1 olduğu için liderlik tablosu cron kodunu elle düzelt."""
    cr.execute("""
        UPDATE ir_act_server SET code = 'model._cron_calculate_leaderboard()'
         WHERE id = (SELECT ias.id FROM ir_cron c
                       JOIN ir_act_server ias ON ias.id = c.ir_actions_server_id
                       JOIN ir_model_data d ON d.res_id = c.id AND d.model = 'ir.cron'
                      WHERE d.module = 'ugurlar_ai_studio' AND d.name = 'cron_monthly_leaderboard')
    """)
    _logger.info('Leaderboard cron kodu güncellendi (%s satır)', cr.rowcount)

    # reject_reasons.xml noupdate=1 — İngilizce önerilen promptları doldur
    for xmlid, text in REJECT_REASONS_EN.items():
        cr.execute("""
            UPDATE ai_studio_reject_reason r SET suggested_prompt_en = %s
              FROM ir_model_data d
             WHERE d.module = 'ugurlar_ai_studio' AND d.name = %s
               AND d.model = 'ai.studio.reject.reason' AND d.res_id = r.id
               AND COALESCE(r.suggested_prompt_en, '') = ''
        """, (text, xmlid))
