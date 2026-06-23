import base64
import json
import logging

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class AiStudioController(http.Controller):
    """AI Stüdyo REST API endpoint'leri.

    Mobil arayüzden fotoğraf yükleme, AI durumu sorgulama ve
    geçici public URL oluşturma işlemlerini yönetir.
    """

    @http.route('/ai_studio/upload_photo', type='json', auth='user', methods=['POST'])
    def upload_photo(self, session_id, photo_type, image_data):
        """Mobil cihazdan fotoğraf yükle.

        Args:
            session_id: Oturum ID
            photo_type: 'front', 'back', veya 'detail'
            image_data: base64 encoded görsel
        """
        session = request.env['ai.studio.session'].browse(int(session_id))
        if not session.exists():
            return {'error': 'Oturum bulunamadı.'}

        # Kalite kontrol
        from ..services.image_processor import check_image_quality
        quality = check_image_quality(image_data)

        photo = request.env['ai.studio.photo'].create({
            'session_id': session.id,
            'photo_type': photo_type,
            'image_original': image_data,
            'quality_score': quality['score'],
            'quality_warnings': json.dumps(quality['warnings'], ensure_ascii=False),
        })

        return {
            'success': True,
            'photo_id': photo.id,
            'quality': quality,
        }

    @http.route('/ai_studio/create_session', type='json', auth='user', methods=['POST'])
    def create_session(self, product_id, **kwargs):
        """Yeni çekim oturumu oluştur.

        Args:
            product_id: Ürün varyant ID
        """
        product = request.env['product.product'].browse(int(product_id))
        if not product.exists():
            return {'error': 'Ürün bulunamadı.'}

        session = request.env['ai.studio.session'].create({
            'product_id': product.id,
        })

        return {
            'success': True,
            'session_id': session.id,
            'session_name': session.name,
        }

    @http.route('/ai_studio/find_product', type='json', auth='user', methods=['POST'])
    def find_product(self, query):
        """Barkod, SKU veya isim ile ürün ara.

        Args:
            query: Arama terimi (barkod, default_code veya isim)
        """
        Product = request.env['product.product']
        query = query.strip()

        # 1. Barkod ile ara
        product = Product.search([('barcode', '=', query)], limit=1)
        if not product:
            # 2. Dahili referans ile ara
            product = Product.search([('default_code', '=', query)], limit=1)
        if not product:
            # 3. İsim ile ara
            product = Product.search([('name', 'ilike', query)], limit=5)

        if not product:
            return {'found': False, 'products': []}

        result = []
        for p in product:
            result.append({
                'id': p.id,
                'name': p.display_name,
                'barcode': p.barcode or '',
                'default_code': p.default_code or '',
                'image_128': p.image_128 or False,
                'categ_id': p.categ_id.id,
                'categ_name': p.categ_id.display_name,
                'variant_count': p.product_tmpl_id.product_variant_count,
                'has_image': bool(p.image_variant_1920),
            })

        return {
            'found': True,
            'products': result,
        }

    @http.route('/ai_studio/generation_status/<int:session_id>',
                type='json', auth='user', methods=['POST'])
    def generation_status(self, session_id):
        """Oturumdaki AI üretimlerinin durumunu sorgula.

        Args:
            session_id: Oturum ID
        """
        session = request.env['ai.studio.session'].browse(session_id)
        if not session.exists():
            return {'error': 'Oturum bulunamadı.'}

        generations = []
        for gen in session.generation_ids:
            generations.append({
                'id': gen.id,
                'photo_type': gen.photo_type,
                'state': gen.state,
                'is_approved': gen.is_approved,
                'is_primary': gen.is_primary,
                'revision_number': gen.revision_number,
                'error_message': gen.error_message or '',
                'has_generated': bool(gen.generated_image),
            })

        return {
            'session_state': session.state,
            'generations': generations,
            'total_cost': session.total_cost,
        }

    @http.route('/ai_studio/approve_generation', type='json', auth='user', methods=['POST'])
    def approve_generation(self, generation_id, is_primary=False):
        """AI üretimini onayla.

        Args:
            generation_id: Üretim ID
            is_primary: Ana resim olarak işaretle
        """
        gen = request.env['ai.studio.generation'].browse(int(generation_id))
        if not gen.exists():
            return {'error': 'Üretim bulunamadı.'}

        gen.action_approve()
        if is_primary:
            gen.action_set_primary()

        return {'success': True}

    @http.route('/ai_studio/reject_generation', type='json', auth='user', methods=['POST'])
    def reject_generation(self, generation_id, reason_id=None, revision_prompt=''):
        """AI üretimini reddet ve revizeye gönder.

        Args:
            generation_id: Üretim ID
            reason_id: Red sebebi ID
            revision_prompt: Ek revizyon talimatı
        """
        gen = request.env['ai.studio.generation'].browse(int(generation_id))
        if not gen.exists():
            return {'error': 'Üretim bulunamadı.'}

        # Red sebebini kaydet
        vals = {'is_approved': False}
        if reason_id:
            vals['reject_reason_id'] = int(reason_id)
        if revision_prompt:
            vals['revision_prompt'] = revision_prompt
        gen.write(vals)

        # Yeni revizyon generation oluştur
        max_rev = int(request.env['ir.config_parameter'].sudo().get_param(
            'ugurlar_ai_studio.max_revisions', '5'
        ))
        if gen.revision_number >= max_rev:
            return {
                'success': False,
                'error': f'Maksimum revize sayısına ({max_rev}) ulaşıldı.',
                'needs_supervisor': True,
            }

        new_gen = request.env['ai.studio.generation'].create({
            'session_id': gen.session_id.id,
            'source_photo_id': gen.source_photo_id.id,
            'photo_type': gen.photo_type,
            'original_image': gen.original_image,
            'state': 'pending',
            'revision_number': gen.revision_number + 1,
            'parent_generation_id': gen.id,
            'provider': gen.provider,
        })

        # Yeniden işlemeyi başlat
        gen.session_id._process_single_generation(new_gen)

        return {
            'success': True,
            'new_generation_id': new_gen.id,
            'revision_number': new_gen.revision_number,
        }

    @http.route('/ai_studio/complete_session', type='json', auth='user', methods=['POST'])
    def complete_session(self, session_id):
        """Oturumu tamamla ve görselleri ürüne kaydet."""
        session = request.env['ai.studio.session'].browse(int(session_id))
        if not session.exists():
            return {'error': 'Oturum bulunamadı.'}

        try:
            session.action_mark_done()
            return {'success': True}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    @http.route('/ai_studio/get_presets', type='json', auth='user', methods=['POST'])
    def get_presets(self, garment_type=None):
        """Aktif manken presetlerini getir.

        Args:
            garment_type: Opsiyonel filtre (tops, bottoms, vb.)
        """
        domain = [('active', '=', True)]
        if garment_type:
            domain.append(('garment_type', '=', garment_type))

        presets = request.env['ai.studio.model.preset'].search(domain)
        result = []
        for p in presets:
            result.append({
                'id': p.id,
                'name': p.name,
                'gender': p.gender,
                'body_type': p.body_type,
                'garment_type': p.garment_type,
                'target_audience': p.target_audience or '',
                'has_front': bool(p.model_image_front),
                'has_back': bool(p.model_image_back),
                'background_type': p.background_type,
                'usage_count': p.usage_count,
                'approval_rate': p.approval_rate,
                'preview_image': p.preview_image or p.model_image_front or False,
            })

        return {'presets': result}

    @http.route('/ai_studio/get_reject_reasons', type='json', auth='user', methods=['POST'])
    def get_reject_reasons(self):
        """Aktif red sebeplerini getir."""
        reasons = request.env['ai.studio.reject.reason'].search([
            ('active', '=', True),
        ], order='sequence')

        return {
            'reasons': [{
                'id': r.id,
                'name': r.name,
                'code': r.code or '',
                'suggested_prompt': r.suggested_prompt or '',
            } for r in reasons],
        }

    @http.route('/ai_studio/get_prompt_templates', type='json', auth='user', methods=['POST'])
    def get_prompt_templates(self, scope=None, category_id=None):
        """Prompt şablonlarını getir."""
        domain = [('active', '=', True)]
        if scope:
            domain.append(('scope', '=', scope))
        if category_id:
            domain.append(('category_id', '=', int(category_id)))

        templates = request.env['ai.studio.prompt.template'].search(domain)
        return {
            'templates': [{
                'id': t.id,
                'name': t.name,
                'scope': t.scope,
                'prompt_text': t.prompt_text,
                'usage_count': t.usage_count,
                'success_rate': t.success_rate,
            } for t in templates],
        }

    @http.route('/ai_studio/dashboard_stats', type='json', auth='user', methods=['POST'])
    def dashboard_stats(self):
        """Dashboard istatistikleri."""
        Session = request.env['ai.studio.session']
        Generation = request.env['ai.studio.generation']

        # Bu ay
        from datetime import date
        today = date.today()
        month_start = today.replace(day=1)

        month_sessions = Session.search_count([
            ('create_date', '>=', month_start.isoformat()),
        ])
        month_gens = Generation.search([
            ('create_date', '>=', month_start.isoformat()),
            ('state', '=', 'done'),
        ])
        approved = month_gens.filtered('is_approved')
        total_cost = sum(month_gens.mapped('cost'))

        # Bugün
        today_sessions = Session.search_count([
            ('create_date', '>=', today.isoformat()),
        ])

        return {
            'month_sessions': month_sessions,
            'month_generations': len(month_gens),
            'month_approval_rate': (
                (len(approved) / len(month_gens)) * 100 if month_gens else 0
            ),
            'month_cost': total_cost,
            'today_sessions': today_sessions,
        }
