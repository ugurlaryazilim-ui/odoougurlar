def migrate(cr, version):
    if not version:
        return
    # NEDEN: soru cron'u noupdate=1 kayıtlı; XML'deki 5 dk varsayılanı mevcut kuruluma yansımaz. Prod'da
    # dakikalık çalışan cron (TODO-23) 5 dk'ya çekilir; elle 5 dk ve üstü verilmiş aralığa dokunulmaz.
    cr.execute("""
        UPDATE ir_cron SET interval_number = 5
         WHERE interval_type = 'minutes' AND interval_number < 5
           AND id IN (SELECT res_id FROM ir_model_data
                       WHERE module = 'pazaryeri_question' AND model = 'ir.cron'
                         AND name = 'cron_sync_marketplace_questions')
    """)
