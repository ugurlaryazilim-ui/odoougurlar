# -*- coding: utf-8 -*-
import datetime
from datetime import timedelta
from odoo import api, fields, models
from dateutil.relativedelta import relativedelta

class AiStudioLeaderboard(models.Model):
    _name = 'ai.studio.leaderboard'
    _description = 'Ayın Stüdyo Yıldızı Geçmişi'
    _order = 'date_month desc, score desc'

    user_id = fields.Many2one('res.users', string='Operatör', required=True)
    date_month = fields.Date(string='Ay', required=True, help="Hangi ayın yıldızı olduğu (Ayın ilk günü olarak kaydedilir)")
    score = fields.Float(string='Performans Puanı')
    approved_count = fields.Integer(string='Onaylanan Çekim Sayısı')
    rejected_count = fields.Integer(string='Revize Edilen Çekim Sayısı')
    title = fields.Char(string='Unvan', default='Ayın Fotoğrafçısı (Stüdyo Yıldızı)')

    @api.model
    def _cron_calculate_leaderboard(self):
        """Her ayın 1'inde gece çalışarak geçen ayın kazananlarını tabloya yazar."""
        today = fields.Date.today()
        # Geçen ayın 1'i ve son günü
        first_day_this_month = today.replace(day=1)
        last_day_last_month = first_day_this_month - timedelta(days=1)
        first_day_last_month = last_day_last_month.replace(day=1)

        domain = [
            ('create_date', '>=', first_day_last_month),
            ('create_date', '<', first_day_this_month),
            ('state', 'in', ['done', 'cancelled'])
        ]

        sessions = self.env['ai.studio.session'].search(domain)

        user_stats = {}
        for sess in sessions:
            user_id = sess.user_id.id
            if not user_id:
                continue
            
            if user_id not in user_stats:
                user_stats[user_id] = {'approved': 0, 'rejected': 0, 'revisions': 0}
                
            if sess.state == 'done':
                user_stats[user_id]['approved'] += 1
                user_stats[user_id]['revisions'] += sess.revision_count
            elif sess.state == 'cancelled':
                user_stats[user_id]['rejected'] += 1

        # Puanlama Mantığı: Onaylanan * 10 Puan - İptal * 5 Puan - Revize * 2 Puan
        leaderboard_records = []
        for user_id, data in user_stats.items():
            score = (data['approved'] * 10) - (data['rejected'] * 5) - (data['revisions'] * 2)
            if score > 0:
                leaderboard_records.append({
                    'user_id': user_id,
                    'date_month': first_day_last_month,
                    'score': score,
                    'approved_count': data['approved'],
                    'rejected_count': data['rejected'] + data['revisions'],
                })

        # Skora göre sırala
        leaderboard_records = sorted(leaderboard_records, key=lambda x: x['score'], reverse=True)
        
        self.search([('date_month', '=', first_day_last_month)]).unlink()

        if leaderboard_records:
            leaderboard_records[0]['title'] = 'Altın Vizör - Ayın Fotoğrafçısı'
            if len(leaderboard_records) > 1:
                leaderboard_records[1]['title'] = 'Gümüş Vizör'
            if len(leaderboard_records) > 2:
                leaderboard_records[2]['title'] = 'Bronz Vizör'

            self.create(leaderboard_records)

    @api.model
    def get_dashboard_data(self, period='this_month'):
        """OWL Dashboard için gerekli olan anlık verileri döndürür."""
        today = fields.Date.today()
        first_day_this_month = today.replace(day=1)
        
        # Dönem filtrelemesi
        domain = []
        if period == 'this_month':
            domain = [('create_date', '>=', first_day_this_month)]
        elif period == 'last_month':
            last_day_last_month = first_day_this_month - timedelta(days=1)
            first_day_last_month = last_day_last_month.replace(day=1)
            domain = [('create_date', '>=', first_day_last_month), ('create_date', '<=', last_day_last_month)]
        elif period == 'this_year':
            first_day_this_year = today.replace(month=1, day=1)
            domain = [('create_date', '>=', first_day_this_year)]
        # all için boş bırakıyoruz
        
        Session = self.env['ai.studio.session']
        
        # 1. Genel İstatistikler
        total_sessions = Session.search_count(domain)
        approved_sessions = Session.search_count(domain + [('state', '=', 'done')])
        rejected_sessions = Session.search_count(domain + [('state', '=', 'cancelled')])
        
        # Revizyonları da sayalım
        all_done_sessions = Session.search(domain + [('state', '=', 'done')])
        total_revisions = sum(all_done_sessions.mapped('revision_count'))
        
        rejected_sessions += total_revisions
        
        # 2. Operatör Leaderboard
        sessions = Session.search(domain + [('state', 'in', ['done', 'cancelled'])])

        user_stats = {}
        for sess in sessions:
            if not sess.user_id:
                continue
            uid = sess.user_id.id
            uname = sess.user_id.name
            if uid not in user_stats:
                user_stats[uid] = {'id': uid, 'name': uname, 'approved': 0, 'rejected': 0, 'revisions': 0, 'score': 0}
            
            if sess.state == 'done':
                user_stats[uid]['approved'] += 1
                user_stats[uid]['revisions'] += sess.revision_count
            elif sess.state == 'cancelled':
                user_stats[uid]['rejected'] += 1

        for uid, data in user_stats.items():
            data['score'] = (data['approved'] * 10) - (data['rejected'] * 5) - (data['revisions'] * 2)
            data['rejected'] += data['revisions'] # UI'da birleşik göstermek için

        # Puanı 0'dan büyük olanları sırala
        leaderboard = [data for data in user_stats.values() if data['score'] > 0]
        leaderboard = sorted(leaderboard, key=lambda x: x['score'], reverse=True)
        
        # İlk 10
        leaderboard = leaderboard[:10]

        # Benim sıramı bul (Aktif Kullanıcı)
        my_uid = self.env.user.id
        my_rank = '-'
        my_stats = {'score': 0, 'approved': 0, 'rejected': 0}
        
        for idx, lb in enumerate(leaderboard):
            if lb['id'] == my_uid:
                my_rank = idx + 1
                break
        
        if my_uid in user_stats:
            my_stats = user_stats[my_uid]

        # 3. Geçmiş Ayların Kazananları
        past_winners_records = self.search([], order='date_month desc, score desc', limit=20)
        past_winners = []
        for r in past_winners_records:
            past_winners.append({
                'month': r.date_month.strftime('%Y %B') if r.date_month else '',
                'user_name': r.user_id.name,
                'score': r.score,
                'title': r.title,
            })

        # 4. Red Nedenleri İstatistikleri
        Generation = self.env['ai.studio.generation']
        
        # Domain based on create_date for generations
        gen_domain = [('state', '=', 'done'), ('is_approved', '=', False), ('reject_reason_id', '!=', False)]
        if period == 'this_month':
            gen_domain.append(('create_date', '>=', first_day_this_month))
        elif period == 'last_month':
            gen_domain.append(('create_date', '>=', first_day_last_month))
            gen_domain.append(('create_date', '<=', last_day_last_month))
        elif period == 'this_year':
            first_day_this_year = today.replace(month=1, day=1)
            gen_domain.append(('create_date', '>=', first_day_this_year))
            
        rejected_gens = Generation._read_group(
            gen_domain,
            ['reject_reason_id'],
            ['__count']
        )
        
        reject_reasons = []
        for reason, count in rejected_gens:
            if reason:
                reject_reasons.append({
                    'id': reason.id,
                    'name': reason.display_name,
                    'count': count
                })
                
        # Sort by count desc
        reject_reasons = sorted(reject_reasons, key=lambda x: x['count'], reverse=True)

        # 5. Maliyet Analizi (Sadece Yöneticiler Görecek Şekilde UI'da Kısıtlanacak)
        all_gens_domain = [('state', 'in', ['done', 'failed', 'processing'])]
        if period == 'this_month':
            all_gens_domain.append(('create_date', '>=', first_day_this_month))
        elif period == 'last_month':
            all_gens_domain.append(('create_date', '>=', first_day_last_month))
            all_gens_domain.append(('create_date', '<=', last_day_last_month))
        elif period == 'this_year':
            all_gens_domain.append(('create_date', '>=', first_day_this_year))
            
        all_gens = Generation.search(all_gens_domain)
        total_cost = sum(all_gens.mapped('cost'))
        
        is_manager = self.env.user.has_group('ugurlar_ai_studio.group_ai_studio_manager')

        return {
            'overview': {
                'total': total_sessions,
                'approved': approved_sessions,
                'rejected': rejected_sessions,
                'approval_rate': round((approved_sessions / total_sessions * 100) if total_sessions else 0, 1)
            },
            'leaderboard': leaderboard,
            'past_winners': past_winners,
            'reject_reasons': reject_reasons,
            'cost_data': {
                'show': is_manager,
                'total_cost': round(total_cost, 2),
                'currency': self.env.user.company_id.currency_id.symbol or '$'
            },
            'my_stats': {
                'rank': my_rank,
                'score': my_stats.get('score', 0),
                'approved': my_stats.get('approved', 0),
                'rejected': my_stats.get('rejected', 0)
            }
        }
