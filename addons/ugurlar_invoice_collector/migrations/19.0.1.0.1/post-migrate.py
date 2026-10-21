def migrate(cr, version):
    if not version:
        return
    # NEDEN: indirme cron'u noupdate=1 kayıtlı; XML'deki 5 dk, mevcut kuruluma yansımaz (J6: cron artık işin
    # sonunda kendini tetikler, dakikalık yoklama gereksiz). Yalnız eski varsayılan (1 dk) güncellenir;
    # kullanıcının elle verdiği başka aralığa dokunulmaz.
    cr.execute("""
        UPDATE ir_cron SET interval_number = 5
         WHERE interval_type = 'minutes' AND interval_number = 1
           AND id IN (SELECT res_id FROM ir_model_data
                       WHERE module = 'ugurlar_invoice_collector' AND model = 'ir.cron'
                         AND name = 'cron_process_invoice_collector_jobs')
    """)
