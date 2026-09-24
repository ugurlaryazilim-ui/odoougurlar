# -*- coding: utf-8 -*-

import logging
import json
import re
from datetime import date, timedelta
from odoo.tools import html_escape

_logger = logging.getLogger(__name__)

class AdsAIEngine:
    """
    AI Orchestration Service for Ads Manager.
    Builds prompts, communicates with the AI provider, and parses responses.
    """

    def __init__(self, env):
        self.env = env
        self._provider = None

    @property
    def provider(self):
        if not self._provider:
            self._provider = self.env['ads.ai.provider'].search([('active', '=', True)], limit=1)
            if not self._provider:
                raise ValueError('No active AI provider configured.')
        return self._provider

    # --- Campaign Analysis ---

    def analyze_campaign(self, campaign, lookback_days=30):
        """Analyze a single campaign and return AI insights dict."""
        try:
            data = self._prepare_campaign_data(campaign, lookback_days)
            prompt = self._build_campaign_analysis_prompt(data)
            
            # Use sudo if provider is restricted, though typically it's model level
            response_text = self.provider.generate_response(prompt)
            
            if not response_text:
                _logger.warning("Empty AI response for campaign %s", campaign.id)
                return {}
                
            return self._parse_analysis_response(response_text)
            
        except Exception as e:
            _logger.error("Error analyzing campaign %s: %s", campaign.id, str(e))
            return {}

    def analyze_campaigns_batch(self, campaigns, lookback_days=30):
        """Analyze multiple campaigns in a single AI call (token-efficient)."""
        if not campaigns:
            return {}
            
        try:
            campaigns_data = [self._prepare_campaign_data(c, lookback_days) for c in campaigns]
            prompt = self._build_batch_analysis_prompt(campaigns_data)
            
            response_text = self.provider.generate_response(prompt)
            if not response_text:
                return {}
                
            # Parse batch response (assuming AI is prompted to return structured json or clear split)
            # A simple implementation splitting by Campaign Name:
            results = {}
            for c_data in campaigns_data:
                c_name = c_data['campaign']
                # Try to extract the block for this campaign
                pattern = f"KAMPANYA: {re.escape(c_name)}(.*?)(?=KAMPANYA:|$)"
                match = re.search(pattern, response_text, re.DOTALL | re.IGNORECASE)
                if match:
                    block_text = match.group(1).strip()
                    results[c_data['id']] = self._parse_analysis_response(block_text)
                else:
                    results[c_data['id']] = {}
                    
            return results
            
        except Exception as e:
            _logger.error("Error in batch analysis: %s", str(e))
            return {}

    # --- Data Preparation ---

    def _prepare_campaign_data(self, campaign, lookback_days=30):
        """Prepare campaign metrics data for AI analysis.
        Aggregates data to minimize token usage."""
        
        MetricDaily = self.env['ads.metric.daily']
        today = date.today()
        start_date = today - timedelta(days=lookback_days)
        
        # Current period (last X days)
        domain = [
            ('campaign_id', '=', campaign.id),
            ('date', '>=', start_date),
            ('date', '<=', today)
        ]
        
        metrics = MetricDaily._read_group(
            domain,
            [],
            ['spend:sum', 'impressions:sum', 'clicks:sum', 'conversions:sum', 'conversion_value:sum']
        )
        
        if metrics and metrics[0]:
            total_spend, total_imp, total_clicks, total_conv, total_val = metrics[0]
        else:
            total_spend = total_imp = total_clicks = total_conv = total_val = 0.0

        # Previous period (for WoW comparison, using last 7 days vs previous 7 days)
        w1_start = today - timedelta(days=7)
        w2_start = today - timedelta(days=14)
        
        w1_metrics = MetricDaily._read_group(
            [('campaign_id', '=', campaign.id), ('date', '>', w1_start), ('date', '<=', today)],
            [], ['spend:sum', 'conversions:sum', 'conversion_value:sum']
        )
        w2_metrics = MetricDaily._read_group(
            [('campaign_id', '=', campaign.id), ('date', '>', w2_start), ('date', '<=', w1_start)],
            [], ['spend:sum', 'conversions:sum', 'conversion_value:sum']
        )
        
        w1_spend = w1_metrics[0][0] if w1_metrics else 0.0
        w1_conv = w1_metrics[0][1] if w1_metrics else 0.0
        w1_val = w1_metrics[0][2] if w1_metrics else 0.0
        
        w2_spend = w2_metrics[0][0] if w2_metrics else 0.0
        w2_conv = w2_metrics[0][1] if w2_metrics else 0.0
        w2_val = w2_metrics[0][2] if w2_metrics else 0.0
        
        w1_roas = self._safe_div(w1_val, w1_spend)
        w2_roas = self._safe_div(w2_val, w2_spend)

        # Budget Pacing (placeholder logic if BudgetPacer isn't available)
        pacing_pct = 0.0
        if campaign.daily_budget:
            avg_daily_spend = self._safe_div(total_spend, lookback_days)
            pacing_pct = (avg_daily_spend / campaign.daily_budget) * 100

        data = {
            'id': campaign.id,
            'campaign': campaign.name,
            'platform': campaign.account_id.platform,
            'objective': campaign.objective or 'Bilinmiyor',
            'budget': {'daily': campaign.daily_budget, 'lifetime': getattr(campaign, 'lifetime_budget', 0.0)},
            'period': f'{lookback_days}g',
            'totals': {
                'spend': total_spend,
                'impressions': total_imp,
                'clicks': total_clicks,
                'conversions': total_conv,
                'conversion_value': total_val
            },
            'kpis': {
                'ctr': self._safe_div(total_clicks, total_imp) * 100,
                'cpc': self._safe_div(total_spend, total_clicks),
                'cpa': self._safe_div(total_spend, total_conv),
                'roas': self._safe_div(total_val, total_spend),
                'conv_rate': self._safe_div(total_conv, total_clicks) * 100
            },
            'wow_change': {
                'spend': self._calculate_wow_change(w1_spend, w2_spend),
                'conversions': self._calculate_wow_change(w1_conv, w2_conv),
                'roas': self._calculate_wow_change(w1_roas, w2_roas)
            },
            'pacing': pacing_pct,
        }
        return data

    # --- Prompt Building ---

    def _build_campaign_analysis_prompt(self, data):
        """Build a structured prompt for single campaign analysis."""
        return f"""Sen bir dijital reklam uzmanısın. Aşağıdaki kampanya verilerini analiz et ve Türkçe yanıt ver.

Kampanya: {data['campaign']} ({data['platform']})
Hedef: {data['objective']}
Bütçe: Günlük {self._format_number(data['budget']['daily'])} TL
Dönem: Son {data['period']}

Toplam Performans:
- Harcama: {self._format_number(data['totals']['spend'])} TL
- Gösterim: {self._format_number(data['totals']['impressions'], 0)}
- Tıklama: {self._format_number(data['totals']['clicks'], 0)}
- Dönüşüm: {self._format_number(data['totals']['conversions'], 0)}
- Dönüşüm Değeri: {self._format_number(data['totals']['conversion_value'])} TL

KPI'lar:
- CTR: %{self._format_number(data['kpis']['ctr'])}
- CPC: {self._format_number(data['kpis']['cpc'])} TL
- CPA: {self._format_number(data['kpis']['cpa'])} TL
- ROAS: {self._format_number(data['kpis']['roas'])}x
- Dönüşüm Oranı: %{self._format_number(data['kpis']['conv_rate'])}

Bütçe Kullanımı: %{self._format_number(data['pacing'])}

Haftalık Değişim (Son 7 Gün vs Önceki 7 Gün):
- Harcama: %{self._format_number(data['wow_change']['spend'])}
- Dönüşüm: %{self._format_number(data['wow_change']['conversions'])}
- ROAS: %{self._format_number(data['wow_change']['roas'])}

Lütfen şu formatta (başlıklara sadık kalarak) yanıt ver:
1. ÖZET: (2-3 cümle genel değerlendirme)
2. GÜÇLÜ YÖNLER: (madde işaretleri ile)
3. ZAYIF YÖNLER: (madde işaretleri ile)
4. ÖNERİLER: (somut, uygulanabilir öneriler)
5. RİSK SEVİYESİ: (düşük/orta/yüksek/kritik)
"""

    def _build_batch_analysis_prompt(self, campaigns_data):
        """Build a prompt for batch campaign analysis."""
        prompt_parts = ["Sen bir dijital reklam uzmanısın. Aşağıdaki kampanya verilerini analiz et ve her biri için Türkçe yanıt ver.\nLütfen her kampanyaya 'KAMPANYA: [Kampanya Adı]' başlığı ile başla ve sonrasında formatı uygula.\n"]
        for data in campaigns_data:
            c_prompt = f"""
KAMPANYA: {data['campaign']}
Hedef: {data['objective']} | Platform: {data['platform']}
Harcama: {self._format_number(data['totals']['spend'])} TL | ROAS: {self._format_number(data['kpis']['roas'])}x | CPA: {self._format_number(data['kpis']['cpa'])} TL
Değişim: Harcama %{self._format_number(data['wow_change']['spend'])}, Dönüşüm %{self._format_number(data['wow_change']['conversions'])}
"""
            prompt_parts.append(c_prompt)
            
        prompt_parts.append("""
Lütfen her kampanya için şu formatta yanıt ver:
1. ÖZET: (1-2 cümle)
2. GÜÇLÜ YÖNLER: (madde işaretleri)
3. ZAYIF YÖNLER: (madde işaretleri)
4. ÖNERİLER: (uygulanabilir kısa öneriler)
5. RİSK SEVİYESİ: (düşük/orta/yüksek/kritik)
""")
        return "\n".join(prompt_parts)

    def _build_weekly_report_prompt(self, report_data):
        """Build prompt for weekly performance report."""
        summary = f"Toplam Harcama: {report_data.get('total_spend', 0)} TL\nToplam Dönüşüm: {report_data.get('total_conv', 0)}\nOrtalama ROAS: {report_data.get('avg_roas', 0)}"
        return f"""Sen bir Dijital Pazarlama Yöneticisisin. Müşteriye sunulmak üzere aşağıdaki haftalık özet verilerine dayanarak Türkçe, profesyonel bir haftalık performans raporu hazırla.

Veriler:
{summary}

Rapor giriş, genel değerlendirme, öne çıkanlar ve haftaya dair planlar bölümlerini içermeli. HTML formatında ver, fakat sadece <div>, <b>, <i>, <p>, <ul>, <li> etiketlerini kullan."""

    def _build_recommendation_explanation_prompt(self, recommendation, metric_data):
        """Build prompt to generate AI explanation for a rule-triggered recommendation."""
        return f"""Bir otomatik kural şu öneriyi oluşturdu: "{recommendation.name}"
Kampanya: {recommendation.campaign_id.name}
Neden tetiklendi: {recommendation.description}

Kampanya metrikleri: {metric_data}

Lütfen reklam yöneticisinin anlayacağı dilde, bu önerinin neden önemli olduğunu ve ne yapması gerektiğini açıklayan, 2-3 cümlelik, insan dilinde bir açıklama yaz (Türkçe)."""

    # --- Response Parsing ---

    def _parse_analysis_response(self, response_text):
        """Parse AI response into structured dict."""
        parsed = {
            'summary': '',
            'strengths': [],
            'weaknesses': [],
            'recommendations': [],
            'risk_level': 'orta',
            'raw_response': response_text,
        }
        
        # Simple parsing logic using string splitting / regex
        sections = {
            'ÖZET': 'summary',
            'GÜÇLÜ YÖNLER': 'strengths',
            'ZAYIF YÖNLER': 'weaknesses',
            'ÖNERİLER': 'recommendations',
            'RİSK SEVİYESİ': 'risk_level'
        }
        
        current_section = None
        for line in response_text.split('\n'):
            line = line.strip()
            if not line:
                continue
                
            # Check for section headers
            matched_section = False
            for header, key in sections.items():
                if re.match(rf"^{header}:?", line, re.IGNORECASE) or re.match(rf"^\d+\.\s*{header}:?", line, re.IGNORECASE):
                    current_section = key
                    matched_section = True
                    # If content is on the same line after colon
                    parts = re.split(r':', line, maxsplit=1)
                    if len(parts) > 1 and parts[1].strip():
                        content = parts[1].strip()
                        if current_section == 'summary':
                            parsed['summary'] += content
                        elif current_section == 'risk_level':
                            parsed['risk_level'] = content.lower()
                        else:
                            parsed[current_section].append(content.lstrip('-*').strip())
                    break
            
            if matched_section:
                continue
                
            # Append content to current section
            if current_section == 'summary':
                parsed['summary'] += ' ' + line
            elif current_section in ['strengths', 'weaknesses', 'recommendations']:
                clean_line = line.lstrip('-*•1234567890. ').strip()
                if clean_line:
                    parsed[current_section].append(clean_line)
            elif current_section == 'risk_level':
                parsed['risk_level'] = line.lower()
                
        # Normalize risk level
        risk_str = parsed['risk_level']
        if 'kritik' in risk_str: parsed['risk_level'] = 'kritik'
        elif 'yüksek' in risk_str: parsed['risk_level'] = 'yüksek'
        elif 'düşük' in risk_str: parsed['risk_level'] = 'düşük'
        else: parsed['risk_level'] = 'orta'
            
        return parsed

    # --- Integration Methods ---

    def enrich_recommendation_with_ai(self, recommendation):
        """Add AI explanation to an existing recommendation."""
        if not recommendation.campaign_id:
            return False
            
        try:
            data = self._prepare_campaign_data(recommendation.campaign_id, lookback_days=7)
            metric_summary = f"ROAS: {data['kpis']['roas']:.2f}, CPA: {data['kpis']['cpa']:.2f}"
            prompt = self._build_recommendation_explanation_prompt(recommendation, metric_summary)
            
            explanation = self.provider.generate_response(prompt)
            if explanation:
                recommendation.ai_explanation = explanation.strip()
                return True
        except Exception as e:
            _logger.error("Failed to enrich recommendation %s: %s", recommendation.id, str(e))
        return False

    def generate_weekly_report(self, account=None, platform=None):
        """Generate a weekly AI-powered report for campaigns.
        Returns HTML string for embedding in email/chatter."""
        domain = [('status', '=', 'active')]
        if account:
            domain.append(('account_id', '=', account.id))
        if platform:
            domain.append(('account_id.platform', '=', platform))
            
        campaigns = self.env['ads.campaign'].search(domain)
        if not campaigns:
            return "<p>Aktif kampanya bulunamadı.</p>"
            
        total_spend = total_conv = total_val = 0.0
        for c in campaigns:
            c_data = self._prepare_campaign_data(c, lookback_days=7)
            total_spend += c_data['totals']['spend']
            total_conv += c_data['totals']['conversions']
            total_val += c_data['totals']['conversion_value']
            
        avg_roas = self._safe_div(total_val, total_spend)
        
        report_data = {
            'total_spend': self._format_number(total_spend),
            'total_conv': self._format_number(total_conv, 0),
            'avg_roas': self._format_number(avg_roas)
        }
        
        prompt = self._build_weekly_report_prompt(report_data)
        try:
            html_report = self.provider.generate_response(prompt)
            return html_report or "<p>Rapor oluşturulamadı.</p>"
        except Exception as e:
            _logger.error("Weekly report error: %s", str(e))
            return f"<p>Hata: {html_escape(str(e))}</p>"

    def run_deep_analysis(self):
        """Weekly deep analysis cron - analyze all campaigns and create recommendations."""
        campaigns = self.env['ads.campaign'].search([('status', '=', 'ACTIVE')])
        stats = {'analyzed': 0, 'high_risk': 0, 'recommendations_created': 0}
        
        Recommendation = self.env['ads.recommendation']
        
        for campaign in campaigns:
            insights = self.analyze_campaign(campaign)
            if not insights:
                continue
                
            stats['analyzed'] += 1
            risk = insights.get('risk_level', 'orta')
            
            # Post to chatter
            msg = f"<b>Haftalık AI Analizi</b><br/>"
            msg += f"<b>Özet:</b> {html_escape(insights.get('summary', ''))}<br/>"
            msg += f"<b>Risk:</b> {risk.upper()}"
            campaign.message_post(body=msg)
            
            if risk in ['yüksek', 'kritik']:
                stats['high_risk'] += 1
                for rec_text in insights.get('recommendations', []):
                    rec = Recommendation.create({
                        'campaign_id': campaign.id,
                        'name': f"AI Uyarısı ({risk.upper()}): {campaign.name}",
                        'description': rec_text,
                        'ai_explanation': insights.get('summary', ''),
                        'severity': 'critical' if risk == 'kritik' else 'warning',
                        'category': 'performance',
                        'status': 'new',
                    })
                    rec._notify_critical()
                    stats['recommendations_created'] += 1
                    
            self.env.cr.commit() # Commit progress
            
        return stats

    # --- Helper Methods ---

    def _safe_div(self, a, b, default=0.0):
        """Safe division helper."""
        return float(a) / float(b) if b and float(b) != 0 else default

    def _format_number(self, num, decimals=2):
        """Format number for display."""
        if num is None:
            return "0"
        return f"{float(num):,.{decimals}f}".replace(',', 'X').replace('.', ',').replace('X', '.')

    def _calculate_wow_change(self, current, previous):
        """Calculate week-over-week percentage change."""
        current = float(current) if current else 0.0
        previous = float(previous) if previous else 0.0
        
        if not previous:
            return 100.0 if current > 0 else 0.0
        return ((current - previous) / previous) * 100

