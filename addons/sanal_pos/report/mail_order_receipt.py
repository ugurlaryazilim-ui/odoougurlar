# -*- coding: utf-8 -*-
"""Mail Order dekont raporu (Aşama 4, KK-4.1/4.4/4.5; tasarım §6.1).

Yetki ve durum denetimi şablonda değil burada yapılır: çekirdek ``group_ids``'i yalnız menü/eylem
bağlamasında uygular, ``/report/pdf/...`` rotası ve ``_render_qweb_*`` bunu denetlemez.
"""
from decimal import Decimal, InvalidOperation

from odoo import api, models
from odoo.exceptions import UserError

from ..tools import format_try

NOT_ELIGIBLE_MSG = 'Dekont yalnız ödemesi alınmış (Ödendi) Mail Order kayıtları için üretilebilir.'
NO_RECORD_MSG = 'Dekont için bir ödeme kaydı seçilmedi.'


class ReportMailOrderReceipt(models.AbstractModel):
    _name = 'report.sanal_pos.report_mail_order_receipt'
    _description = 'Mail Order dekont raporu'

    @api.model
    def _get_report_values(self, docids, data=None):
        Payment = self.env['sanal.pos.payment']
        # DIKKAT: bu denetim raporun TEK yetki kapısıdır. Çekirdek /report/pdf rotası ve
        # ir.actions.report._render_qweb_* ``group_ids``'e bakmaz (rapor sudo ile çözülür); denetim
        # ACL'e de bırakılamaz (ACL ileride gevşerse ya da sihirbaz/şablon yolu sudo ile gelirse
        # müşteri verisi dekonta düşer). AccessError -> HTTP 403 (KK-4.5). env.su (cron, e-posta
        # şablonu) geçer: ``_check_sanal_pos_user`` ile aynı kural.
        Payment._check_sanal_pos_user()
        # NEDEN: kayıtlar çağıranın haklarıyla okunur (sudo yok): ACL/kayıt kuralı ikinci katman.
        docs = Payment.browse(docids or []).exists()
        if not docs:
            raise UserError(NO_RECORD_MSG)
        # NEDEN: durum denetimi okumadan SONRA, şablondan ÖNCE; kısmi iade/iptal dahil paid dışı
        # her durumda dekont yok (KK-4.4) ve hata istemci hatasıdır (UserError -> 4xx, 5xx değil).
        if any(doc.payment_method != 'mail_order' or doc.state != 'paid' for doc in docs):
            raise UserError(NOT_ELIGIBLE_MSG)
        return {
            'doc_ids': docs.ids,
            'doc_model': 'sanal.pos.payment',
            'docs': docs,
            'receipts': {doc.id: self._receipt_values(doc) for doc in docs},
        }

    @api.model
    def _receipt_values(self, doc):
        """Şablona yalnız basılacak metinler gider; kart için yalnız son 4 hane (PAN/BIN yok)."""
        paid = doc.paid_amount or doc.amount
        try:
            surcharge = Decimal(str(paid or 0)) - Decimal(str(doc.amount or 0))
        except InvalidOperation:
            surcharge = Decimal('0')
        # NEDEN: onay kodu yalnız dekontun işlem numarasıyla eşleşen onaylı denemeden alınır;
        # başka denemenin kodunu yazmak, kodsuz dekonttan kötüdür.
        approved = doc.attempt_ids.filtered(
            lambda a: a.status == 'approved' and a.approval_code and doc.provider_tran_ref
            and a.tran_ref == doc.provider_tran_ref).sorted('tran_time', reverse=True)
        last4 = (doc.card_last4 or '')[-4:]
        return {
            'amount_text': format_try(doc.amount),
            'paid_text': format_try(paid),
            # 0,01 TL'den küçük fark yuvarlama artığıdır, vade farkı sayılmaz
            'surcharge_text': format_try(surcharge) if surcharge >= Decimal('0.01') else False,
            'installments': doc.installment_count or 1,
            'paid_local': doc._format_local(doc.paid_at),
            'tran_ref': doc.provider_tran_ref or False,
            'approval_code': approved[:1].approval_code or False,
            # DIKKAT: yalnız 4 rakam basılır; alana ileride fazlası yazılsa bile dekonta çıkmaz.
            'card_mask': '**** **** **** %s' % last4 if len(last4) == 4 and last4.isdigit() else False,
        }
