def migrate(cr, version):
    if not version:
        return
    # NEDEN: split_package_ids alanı btree'den trigram'a geçti; Odoo aynı adlı indeks varsa yenisini
    # kurmaz (ad indeks türünden bağımsız). Eski btree silinir; modül yükseltmesindeki indeks kontrolü
    # (bu betikten sonra) trigram'ı kurar. Ad sürümden sürüme değişebildiği için tanımdan bulunur.
    cr.execute("""
        SELECT indexname FROM pg_indexes
         WHERE schemaname = current_schema AND tablename = 'trendyol_order'
           AND indexdef ILIKE '%%USING btree (split_package_ids)%%'
    """)
    for (name,) in cr.fetchall():
        cr.execute('DROP INDEX IF EXISTS "%s"' % name.replace('"', ''))
