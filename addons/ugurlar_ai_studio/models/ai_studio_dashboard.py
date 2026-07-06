# -*- coding: utf-8 -*-
import datetime
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
    def calculate_monthly_stars(self):
        """Her ayın sonunda çalışarak o ayın en iyilerini belirler ve tabloya yazar (Cron)."""
        today = fields.Date.today()
        # Bir önceki ayın başlangıç ve bitişi
        first_day_last_month = (today.replace(day=1) - relativedelta(months=1))
        last_day_last_month = today.replace(day=1) - relativedelta(days=1)

        domain = [
            ('create_date', '>=', first_day_last_month),
            ('create_date', '<=', last_day_last_month),
            ('state', 'in', ['approved', 'rejected', 'revised'])
        ]
        
        # Operatör bazlı gruplama yap
        stats = self.env['ai.studio.session'].read_group(
            domain,
            ['user_id', 'state'],
            ['user_id', 'state'],
            lazy=False
        )

        user_stats = {}
        for stat in stats:
            user_id = stat['user_id'][0] if stat.get('user_id') else False
            if not user_id:
                continue
            
            if user_id not in user_stats:
                user_stats[user_id] = {'approved': 0, 'rejected': 0}
                
            state = stat['state']
            count = stat['__count']
            
            if state == 'approved':
                user_stats[user_id]['approved'] += count
            elif state in ['rejected', 'revised']:
                user_stats[user_id]['rejected'] += count

        # Puanlama Mantığı: Onaylanan * 10 Puan - Revize * 5 Puan
        leaderboard_records = []
        for user_id, data in user_stats.items():
            score = (data['approved'] * 10) - (data['rejected'] * 5)
            # Sadece puanı 0'dan büyük olanları listeye al
            if score > 0:
                leaderboard_records.append({
                    'user_id': user_id,
                    'date_month': first_day_last_month,
                    'score': score,
                    'approved_count': data['approved'],
                    'rejected_count': data['rejected'],
                })

        # Skora göre sırala ve ilk 3'ü kaydet (veya hepsini)
        leaderboard_records = sorted(leaderboard_records, key=lambda x: x['score'], reverse=True)
        
        # O ay için önceden hesaplanmış varsa sil (tekrar çalıştırılırsa diye)
        self.search([('date_month', '=', first_day_last_month)]).unlink()

        if leaderboard_records:
            # En iyi kişiye özel Unvan verilebilir
            leaderboard_records[0]['title'] = 'Altın Vizör - Ayın Fotoğrafçısı'
            if len(leaderboard_records) > 1:
                leaderboard_records[1]['title'] = 'Gümüş Vizör'
            if len(leaderboard_records) > 2:
                leaderboard_records[2]['title'] = 'Bronz Vizör'

            self.create(leaderboard_records)

    @api.model
    def get_dashboard_data(self):
        """OWL Dashboard için gerekli olan anlık verileri döndürür."""
        today = fields.Date.today()
        first_day_this_month = today.replace(day=1)
        
        Session = self.env['ai.studio.session']
        
        # 1. Genel İstatistikler (Bu Ay)
        this_month_domain = [('create_date', '>=', first_day_this_month)]
        
        total_sessions = Session.search_count(this_month_domain)
        approved_sessions = Session.search_count(this_month_domain + [('state', '=', 'approved')])
        rejected_sessions = Session.search_count(this_month_domain + [('state', 'in', ['rejected', 'revised'])])
        
        # 2. Operatör Leaderboard (Bu Ayın Anlık Sıralaması)
        stats = Session.read_group(
            this_month_domain + [('state', 'in', ['approved', 'rejected', 'revised'])],
            ['user_id', 'state'],
            ['user_id', 'state'],
            lazy=False
        )

        user_stats = {}
        for stat in stats:
            if not stat.get('user_id'):
                continue
            uid = stat['user_id'][0]
            uname = stat['user_id'][1]
            if uid not in user_stats:
                user_stats[uid] = {'id': uid, 'name': uname, 'approved': 0, 'rejected': 0, 'score': 0}
            
            if stat['state'] == 'approved':
                user_stats[uid]['approved'] += stat['__count']
            else:
                user_stats[uid]['rejected'] += stat['__count']

        leaderboard = []
        for uid, data in user_stats.items():
            data['score'] = (data['approved'] * 10) - (data['rejected'] * 5)
            leaderboard.append(data)
            
        leaderboard = sorted(leaderboard, key=lambda x: x['score'], reverse=True)

        # 3. Geçmiş Ayların Kazananları
        past_winners_recs = self.search([], order='date_month desc, score desc', limit=5)
        past_winners = [{
            'user_name': rec.user_id.name,
            'date': rec.date_month.strftime('%B %Y'),
            'score': rec.score,
            'title': rec.title,
            'approved': rec.approved_count
        } for rec in past_winners_recs]

        # 4. Mevcut Kullanıcı İstatistikleri
        uid = self.env.uid
        my_stats = next((u for u in leaderboard if u['id'] == uid), {'approved': 0, 'rejected': 0, 'score': 0})
        my_rank = next((i + 1 for i, u in enumerate(leaderboard) if u['id'] == uid), 0)

        return {
            'overview': {
                'total': total_sessions,
                'approved': approved_sessions,
                'rejected': rejected_sessions,
                'approval_rate': round((approved_sessions / total_sessions * 100) if total_sessions else 0, 1)
            },
            'leaderboard': leaderboard[:10],  # Top 10
            'past_winners': past_winners,
            'my_stats': {
                'rank': my_rank,
                'score': my_stats['score'],
                'approved': my_stats['approved'],
                'rejected': my_stats['rejected']
            }
        }
