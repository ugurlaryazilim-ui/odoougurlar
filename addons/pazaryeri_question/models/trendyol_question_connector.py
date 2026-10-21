import logging
from datetime import datetime, timedelta, timezone
from odoo import api, models, fields, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

class TrendyolQuestionConnector(models.AbstractModel):
    _name = 'trendyol.question.connector'
    _description = 'Trendyol Soru Connector'

    @api.model
    def sync_questions_for_store(self, store):
        """Belirli bir mağazanın tüm sorularını çek."""
        _logger.info("Trendyol soru sync başlıyor — mağaza: %s, seller_id: %s", store.name, store.seller_id)
        
        api = store.get_api()
        
        # Son 2 haftayı çek (API limiti)
        now = datetime.now()
        start_date = now - timedelta(days=14)
        
        page = 0
        total_created = 0
        total_updated = 0
        
        while True:
            params = {
                'startDate': int(start_date.timestamp() * 1000),
                'endDate': int(now.timestamp() * 1000),
                'page': page,
                'size': 50,
                'orderByField': 'CreatedDate',
                'orderByDirection': 'DESC',
            }
            
            _logger.info("API çağrısı: page=%d, startDate=%s, endDate=%s", 
                        page, start_date.isoformat(), now.isoformat())
            
            result = api._request('GET', f'/qna/sellers/{store.seller_id}/questions/filter', params=params)
            
            if not result.get('success'):
                _logger.error("Trendyol soru çekme hatası: %s", result.get('error'))
                break
            
            data = result.get('data', {})
            
            # API yanıt yapısını logla
            if page == 0:
                _logger.info("API yanıt anahtarları: %s", list(data.keys()) if isinstance(data, dict) else type(data))
                _logger.info("totalElements: %s, totalPages: %s", 
                           data.get('totalElements', 'N/A'), data.get('totalPages', 'N/A'))
            
            content = data.get('content', [])
            
            if not content:
                _logger.info("Sayfa %d: İçerik boş, döngü sonlandırılıyor.", page)
                break
            
            _logger.info("Sayfa %d: %d soru işleniyor...", page, len(content))
            
            # NEDEN: soru başına 2-3 search yerine sayfa başına 2 toplu sorgu (mevcut sorular + cevap geçmişi).
            cache = self._prefetch_existing([str(q.get('id', '')) for q in content])
            for question_data in content:
                try:
                    with self.env.cr.savepoint():
                        res = self._process_question(question_data, store, cache=cache)
                        if res == 'created':
                            total_created += 1
                        elif res == 'updated':
                            total_updated += 1
                except Exception as e:
                    _logger.error("Soru işleme hatası (ID: %s): %s", 
                                question_data.get('id'), e, exc_info=True)
            
            total_pages = data.get('totalPages', 0)
            if page >= total_pages - 1:
                break
            page += 1
        
        # last_question_sync — ayrı cursor ile güncelle
        # REPEATABLE READ'de savepoint+retry çalışmıyor çünkü tüm
        # retry'lar aynı stale snapshot'ı kullanıyor.
        # Ayrı cursor kullanarak ana transaction'dan bağımsız, kısa
        # bir transaction ile güncelliyoruz. Sipariş sync ve finansal
        # sync de aynı pattern'i kullanıyor, böylece hiçbiri çakışmıyor.
        store_id = store.id
        try:
            with self.pool.cursor() as new_cr:
                new_cr.execute(
                    "UPDATE trendyol_store SET last_question_sync = %s, write_date = %s WHERE id = %s",
                    (fields.Datetime.now(), fields.Datetime.now(), store_id)
                )
        except Exception as e:
            _logger.warning("last_question_sync güncellenemedi (mağaza: %s): %s", store.name, e)
        
        _logger.info("Trendyol soru sync tamamlandı (mağaza: %s) | Yeni: %d | Güncellenen: %d",
                     store.name, total_created, total_updated)
        
        return {'created': total_created, 'updated': total_updated}

    @staticmethod
    def _ts(millis):
        """Trendyol ms zaman damgası → Odoo'nun UTC naive, saniye hassasiyetli datetime'ı.

        NEDEN: fromtimestamp() sunucu saat dilimine bağlıydı ve mikrosaniye taşıyordu; Odoo alanı
        mikrosaniyeyi atınca her karşılaştırma 'değişti' çıkıyordu (sahte güncelleme)."""
        return datetime.fromtimestamp(millis / 1000, tz=timezone.utc).replace(tzinfo=None, microsecond=0)

    @api.model
    def _prefetch_existing(self, ext_ids):
        """Verilen pazaryeri soru ID'leri için mevcut kayıtları ve cevap geçmişini toplu getir."""
        Question = self.env['marketplace.question'].sudo()
        ext_ids = [i for i in ext_ids if i]
        questions = Question.search([
            ('marketplace_type', '=', 'trendyol'),
            ('external_question_id', 'in', ext_ids),
        ]) if ext_ids else Question
        by_ext = {}
        for q in questions:
            by_ext.setdefault(q.external_question_id, q)  # eski davranış: limit=1
        sent, rejected = {}, {}
        if questions:
            for a in self.env['marketplace.question.answer'].sudo().search_read(
                    [('question_id', 'in', questions.ids)],
                    ['question_id', 'answer_type', 'external_answer_id', 'answer_text']):
                qid = a['question_id'][0]
                if a['answer_type'] == 'rejected':
                    rejected.setdefault(qid, set()).add(a['answer_text'])
                elif a['external_answer_id']:
                    sent.setdefault(qid, set()).add(a['external_answer_id'])
        return {'questions': by_ext, 'sent': sent, 'rejected': rejected}

    @staticmethod
    def _differs(rec, vals):
        """vals içinde kayıttan gerçekten farklı olan alan var mı (tip bilinçli karşılaştırma)."""
        for key, new_val in vals.items():
            field = rec._fields[key]
            old_val = rec[key]
            if field.type == 'many2one':
                old_val = old_val.id
            elif field.type == 'boolean':
                old_val, new_val = bool(old_val), bool(new_val)
            elif field.type in ('char', 'text'):
                old_val, new_val = old_val or '', new_val or ''
            if old_val != new_val:
                return True
        return False

    def _process_question(self, data, store, cache=None):
        """Tek bir soruyu işle — oluştur veya güncelle. Dönüş: created / updated / unchanged / skipped."""
        Question = self.env['marketplace.question'].sudo()
        question_id = str(data.get('id', ''))

        if not question_id:
            _logger.warning("Soru ID boş, atlanıyor: %s", data)
            return 'skipped'

        if cache is None:
            cache = self._prefetch_existing([question_id])
        existing = cache['questions'].get(question_id) or Question

        # Status mapping
        status_map = {
            'WAITING_FOR_ANSWER': 'waiting',
            'ANSWERED': 'answered',
            'REPORTED': 'reported',
            'REJECTED': 'rejected',
            'UNANSWERED': 'unanswered',
        }
        
        # Müşteri adı: showUserName=false ise Trendyol boş döner
        customer_name = data.get('userName', '')
        show_user_name = data.get('showUserName', True)
        if not customer_name and not show_user_name:
            show_name_setting = self.env['ir.config_parameter'].sudo().get_param(
                'pazaryeri_question.show_hidden_customer_name', 'True'
            )
            if show_name_setting == 'True':
                customer_name = 'Gizli Müşteri'

        raw_status = data.get('status', '')
        mapped_status = status_map.get(raw_status, 'waiting')
        
        vals = {
            'marketplace_type': 'trendyol',
            'store_id': store.id,
            'external_question_id': question_id,
            'question_text': data.get('text', ''),
            'customer_name': customer_name,
            'customer_id_external': str(data.get('customerId', '')),
            'product_name': data.get('productName', ''),
            'product_image_url': data.get('imageUrl', ''),
            'product_web_url': data.get('webUrl', ''),
            'product_main_id': data.get('productMainId', ''),
            'status': mapped_status,
            'is_public': data.get('public', True),
            'show_user_name': show_user_name,
            'answered_date_message': data.get('answeredDateMessage', ''),
        }
        
        # Question date from timestamp
        creation_date = data.get('creationDate')
        if creation_date:
            vals['question_date'] = self._ts(creation_date)
        
        # Answer data
        answer = data.get('answer')
        if answer and answer.get('text'):
            vals['answer_text'] = answer.get('text', '')
            vals['external_answer_id'] = str(answer.get('id', ''))
            if answer.get('creationDate'):
                vals['answer_date'] = self._ts(answer['creationDate'])
        
        # Rejected answer data
        rejected = data.get('rejectedAnswer')
        if rejected and rejected.get('text'):
            vals['rejected_answer_text'] = rejected.get('text', '')
            vals['rejection_reason'] = rejected.get('reason', '')
            if rejected.get('creationDate'):
                vals['rejected_answer_date'] = self._ts(rejected['creationDate'])
        
        # Root-level reason (soru red sebebi)
        if data.get('reason') and not vals.get('rejection_reason'):
            vals['rejection_reason'] = data.get('reason', '')

        # Report data
        if data.get('reportReason'):
            vals['report_reason'] = data.get('reportReason', '')
        if data.get('reportedDate'):
            vals['reported_date'] = self._ts(data['reportedDate'])
        if data.get('rejectedDate'):
            vals['rejected_answer_date'] = self._ts(data['rejectedDate'])
        
        if existing:
            old_status = existing.status
            new_status = vals.get('status', old_status)
            
            # Don't overwrite user's answer_text if they typed one and question is still waiting
            if old_status == 'waiting' and existing.answer_text and new_status == 'waiting':
                vals.pop('answer_text', None)
            
            # Gereksiz update'leri atla — sadece gerçekten değişen alanlar varsa güncelle
            changed = self._differs(existing, vals)
            if changed:
                existing.write(vals)
                # Hemen flush et — ORM'in dirty record biriktirmesini önle
                self.env.flush_all()
            # NEDEN: 'Güncellenen' sayacı yalnız gerçek değişikliği saysın (alan farkı, yeni cevap/red kaydı).
            modified = changed
            
            # Cevap geçmişi — yeni veya mevcut cevaplanmış sorular için
            AnswerModel = self.env['marketplace.question.answer'].sudo()
            answer_data = data.get('answer')
            if answer_data and answer_data.get('text'):
                ext_answer_id = str(answer_data.get('id', ''))
                # Aynı external_answer_id ile kayıt var mı kontrol et
                existing_answer = ext_answer_id and ext_answer_id in cache['sent'].get(existing.id, ())

                if not existing_answer:
                    modified = True
                    cache['sent'].setdefault(existing.id, set()).add(ext_answer_id)
                    answer_date = None
                    if answer_data.get('creationDate'):
                        answer_date = self._ts(answer_data['creationDate'])
                    AnswerModel.create({
                        'question_id': existing.id,
                        'answer_text': answer_data['text'],
                        'answer_type': 'sent',
                        'external_answer_id': ext_answer_id,
                        'sent_date': answer_date or fields.Datetime.now(),
                    })
                    self.env.flush_all()
                    # Sadece waiting→answered geçişinde chatter bildirimi
                    if old_status == 'waiting' and new_status == 'answered':
                        existing.message_post(
                            body="📣 Bu soru Trendyol panelinden cevaplanmış ve otomatik güncellendi.",
                        )
            
            # Reddedilen cevap geçmişi
            rejected_data = data.get('rejectedAnswer')
            if rejected_data and rejected_data.get('text'):
                # Reddedilen cevap kayıt var mı?
                has_rejected = rejected_data['text'] in cache['rejected'].get(existing.id, ())
                if not has_rejected:
                    modified = True
                    cache['rejected'].setdefault(existing.id, set()).add(rejected_data['text'])
                    rejected_date = None
                    if rejected_data.get('creationDate'):
                        rejected_date = self._ts(rejected_data['creationDate'])
                    AnswerModel.create({
                        'question_id': existing.id,
                        'answer_text': rejected_data['text'],
                        'answer_type': 'rejected',
                        'rejection_reason': rejected_data.get('reason', ''),
                        'sent_date': rejected_date or fields.Datetime.now(),
                    })
                    self.env.flush_all()
            
            # Reddedildiyse chatter bildirimi
            if old_status != 'rejected' and new_status == 'rejected':
                existing.message_post(
                    body="❌ Bu sorunun cevabı Trendyol tarafından reddedildi.\n"
                         f"Sebep: {vals.get('rejection_reason', 'Belirtilmemiş')}",
                )
            
            return 'updated' if modified else 'unchanged'
        else:
            _logger.info("Yeni soru oluşturuluyor: ID=%s, status=%s, ürün=%s", 
                        question_id, mapped_status, data.get('productName', ''))
            new_question = Question.create(vals)
            self.env.flush_all()
            cache['questions'][question_id] = new_question  # aynı sayfada tekrar gelen ID çift kayıt açmasın
            
            # Yeni soru zaten cevaplanmışsa → cevap geçmişine kaydet
            AnswerModel = self.env['marketplace.question.answer'].sudo()
            answer = data.get('answer')
            if answer and answer.get('text'):
                ext_answer_id = str(answer.get('id', ''))
                answer_date = None
                if answer.get('creationDate'):
                    answer_date = self._ts(answer['creationDate'])
                AnswerModel.create({
                    'question_id': new_question.id,
                    'answer_text': answer['text'],
                    'answer_type': 'sent',
                    'external_answer_id': ext_answer_id,
                    'sent_date': answer_date or fields.Datetime.now(),
                })
            
            # Reddedilen cevap varsa → cevap geçmişine "rejected" olarak kaydet
            rejected = data.get('rejectedAnswer')
            if rejected and rejected.get('text'):
                rejected_date = None
                if rejected.get('creationDate'):
                    rejected_date = self._ts(rejected['creationDate'])
                AnswerModel.create({
                    'question_id': new_question.id,
                    'answer_text': rejected['text'],
                    'answer_type': 'rejected',
                    'rejection_reason': rejected.get('reason', ''),
                    'sent_date': rejected_date or fields.Datetime.now(),
                })
            
            self.env.flush_all()
            
            # Bildirim: seçili müşteri temsilcilerine bildirim gönder
            if mapped_status == 'waiting':
                self._notify_representatives(new_question)
            return 'created'

    def send_answer(self, question):
        """Trendyol'a cevap gönder."""
        if not question.store_id:
            return {'success': False, 'error': 'Mağaza bilgisi bulunamadı'}
        
        api = question.store_id.get_api()
        result = api._request(
            'POST',
            f'/qna/sellers/{question.store_id.seller_id}/questions/{question.external_question_id}/answers',
            data={'text': question.answer_text},
        )
        
        if result.get('success'):
            answer_data = result.get('data', {})
            return {
                'success': True,
                'answer_id': answer_data.get('answerId', ''),
            }
        else:
            return {
                'success': False,
                'error': result.get('error', 'Bilinmeyen hata'),
            }

    def sync_single_question(self, question):
        """Tek soruyu güncel bilgilerle güncelle."""
        if not question.store_id:
            raise UserError(_('Mağaza bilgisi bulunamadı!'))
        
        api = question.store_id.get_api()
        result = api._request(
            'GET',
            f'/qna/sellers/{question.store_id.seller_id}/questions/{question.external_question_id}',
        )
        
        if result.get('success'):
            self._process_question(result.get('data', {}), question.store_id)
        else:
            raise UserError(_('Soru güncellenemedi: %s') % result.get('error', 'Bilinmeyen hata'))

    def _notify_representatives(self, question):
        """Yeni soru geldiğinde seçili müşteri temsilcilerine bildirim gönder."""
        try:
            company = self.env.company
            users = company.pq_notification_user_ids
            if not users:
                return

            # Kullanıcıları takipçi olarak ekle
            partners = users.mapped('partner_id')
            question.message_subscribe(partner_ids=partners.ids)

            # Bildirim mesajı gönder
            product_info = question.product_name or 'Bilinmeyen Ürün'
            store_name = question.store_id.name or ''
            question.message_post(
                body=f"🔔 <b>Yeni müşteri sorusu!</b><br/>"
                     f"<b>Mağaza:</b> {store_name}<br/>"
                     f"<b>Ürün:</b> {product_info}<br/>"
                     f"<b>Soru:</b> {question.question_text[:200]}",
                subject=f"Yeni Soru: {product_info}",
                partner_ids=partners.ids,
                message_type='notification',
                subtype_xmlid='mail.mt_comment',
            )
        except Exception as e:
            _logger.warning("Soru bildirim hatası (ID: %s): %s", question.id, e)
