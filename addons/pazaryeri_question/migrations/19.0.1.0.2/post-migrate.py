def migrate(cr, version):
    if not version:
        return
    # NEDEN: question_date hem alan düzeyinde (index=True) hem models.Index ile indekslenmişti. Alandan
    # index=True kaldırıldı ama Odoo artık gerekmeyen alan indeksini düşürmez; yinelenen indeks burada
    # atılır (kalan: marketplace_question_question_date_idx). IF EXISTS: yeni kurulumda/tekrar -u'da zararsız.
    cr.execute("DROP INDEX IF EXISTS marketplace_question__question_date_index")
