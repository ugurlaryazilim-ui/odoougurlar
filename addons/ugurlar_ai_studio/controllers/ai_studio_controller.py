import base64
import json
import logging

from odoo import _, fields, http
from odoo.http import request

_logger = logging.getLogger(__name__)


class AiStudioController(http.Controller):
    """AI Studio REST API endpointleri."""

    @http.route('/ai_studio/upload_photo', type='json', auth='user', methods=['POST'])
    def upload_photo(self, session_id, photo_type, image_data, detail_placement=None, **kwargs):
        """Mobil cihazdan fotograf yukle."""
        try:
            session = request.env['ai.studio.session'].browse(int(session_id))
            if not session.exists():
                return {'error': 'Oturum bulunamadi.'}

            # Kalite kontrol
            warnings = []
            score = 100.0
            try:
                image_bytes = base64.b64decode(image_data)
                size_kb = len(image_bytes) / 1024
                if size_kb < 50:
                    warnings.append('Dosya cok kucuk')
                    score -= 30
                elif size_kb > 10240:
                    warnings.append('Dosya cok buyuk (>10MB)')
                    score -= 5
            except Exception:
                score = 50.0

            quality = {
                'score': max(0, min(100, score)),
                'warnings': warnings,
                'is_acceptable': score >= 50,
            }

            photo_vals = {
                'session_id': session.id,
                'photo_type': photo_type,
                'image_original': image_data,
                'quality_score': quality['score'],
                'quality_warnings': json.dumps(quality['warnings'], ensure_ascii=False),
            }
            # Detay fotoğraflarında konum bilgisi
            if photo_type == 'detail' and detail_placement in ('front', 'back'):
                photo_vals['detail_placement'] = detail_placement

            set_line_id = kwargs.get('set_line_id')
            if set_line_id:
                photo_vals['set_line_id'] = int(set_line_id)

            photo = request.env['ai.studio.photo'].create(photo_vals)

            return {
                'success': True,
                'photo_id': photo.id,
                'quality': quality,
            }
        except Exception as e:
            _logger.exception('upload_photo hatasi: %s', e)
            return {'error': str(e)}

    @http.route('/ai_studio/create_session', type='json', auth='user', methods=['POST'])
    def create_session(self, product_id, **kwargs):
        """Yeni cekim oturumu olustur."""
        try:
            product = request.env['product.product'].browse(int(product_id))
            if not product.exists():
                return {'error': 'Urun bulunamadi.'}

            # Aynı renkteki varyantları bul
            current_color_id = None
            color_attr_names = {'renk', 'color', 'colour'}
            for ptav in product.product_template_attribute_value_ids:
                attr_name = ptav.attribute_id.name.lower().strip()
                if any(c in attr_name for c in color_attr_names):
                    current_color_id = ptav.id
                    break

            if current_color_id:
                color_variants = product.product_tmpl_id.product_variant_ids.filtered(
                    lambda v: current_color_id in v.product_template_attribute_value_ids.ids
                )
            else:
                color_variants = product

            # Güvenlik Kontrolü: Herhangi bir kullanıcı tarafından başlatılmış aktif oturum var mı? (sudo)
            existing_active_session = request.env['ai.studio.session'].sudo().search([
                ('product_id', 'in', color_variants.ids),
                ('state', 'in', ['photos_ready', 'processing', 'review', 'failed', 'saving'])
            ], limit=1)

            if existing_active_session:
                op_name = existing_active_session.create_uid.name or 'Başka bir operatör'
                return {
                    'error': f"Bu ürün ({product.display_name}) için {op_name} tarafından başlatılmış aktif bir oturum ({existing_active_session.name}) bulunmaktadır! Mükerrer çekim yapamazsınız."
                }

            # Kullanıcının daha önceden yarım bıraktığı kendi (Taslak) oturumlarını temizle
            abandoned_drafts = request.env['ai.studio.session'].sudo().search([
                ('create_uid', '=', request.env.user.id),
                ('state', '=', 'draft')
            ])
            if abandoned_drafts:
                abandoned_drafts.sudo().unlink()

            session = request.env['ai.studio.session'].create({
                'product_id': product.id,
            })

            return {
                'success': True,
                'session_id': session.id,
                'session_name': session.name,
            }
        except Exception as e:
            _logger.exception('create_session hatasi: %s', e)
            return {'error': str(e)}

    @http.route('/ai_studio/sibling_variants', type='json', auth='user', methods=['POST'])
    def sibling_variants(self, product_id):
        """Aynı ürün template'ının stokta olup görseli olmayan diğer renk varyantlarını döndürür."""
        try:
            product = request.env['product.product'].browse(int(product_id))
            if not product.exists():
                return {'variants': []}

            # Mevcut ürünün renk ID'sini bul
            current_color_id = None
            color_attr_names = {'renk', 'color', 'colour'}
            for ptav in product.product_template_attribute_value_ids:
                attr_name = ptav.attribute_id.name.lower().strip()
                if any(c in attr_name for c in color_attr_names):
                    current_color_id = ptav.id
                    break

            template = product.product_tmpl_id
            # Tüm varyantları al (gruplama yapacağımız için mevcut ürün dahil her şeyi tarayacağız ama active_session/image'larına bakacağız)
            all_variants = template.product_variant_ids.filtered(lambda v: v.active)

            if not all_variants:
                return {'variants': []}

            template_has_image = bool(template.image_1920)
            color_groups = {}

            for variant in all_variants:
                variant_color_id = None
                variant_color_name = ''
                variant_attrs = []
                for ptav in variant.product_template_attribute_value_ids:
                    attr_name = ptav.attribute_id.name.lower().strip()
                    variant_attrs.append(ptav.name)
                    if any(c in attr_name for c in color_attr_names):
                        variant_color_id = ptav.id
                        variant_color_name = ptav.name

                # Renk attribute'u yoksa varyant id'sine göre grupla (fallback)
                key = variant_color_id or f"no_color_{variant.id}"

                if key not in color_groups:
                    color_groups[key] = {
                        'color_name': variant_color_name,
                        'attributes': ', '.join(variant_attrs),
                        'has_image': False,
                        'has_active_session': False,
                        'total_stock': 0,
                        'representative_variant': None
                    }

                # Resim varsa tüm renk grubu tamamlanmış sayılır
                # NOT: Sadece varyantın KENDI resmini kontrol et (image_variant_1920).
                # Template'ten miras alınan resme (image_1920) bakma!
                # Böylece Siyah rengin resimleri template'e yazıldığında
                # Ekru/Biru gibi diğer renkler hâlâ "görselsiz" sayılır.
                if bool(variant.image_variant_1920):
                    color_groups[key]['has_image'] = True
                    
                active_session = request.env['ai.studio.session'].sudo().search([
                    ('product_id', '=', variant.id),
                    ('state', 'not in', ['cancelled', 'done']),
                ], limit=1)
                
                if active_session:
                    color_groups[key]['has_active_session'] = True

                qty = variant.qty_available or 0
                if qty > 0:
                    color_groups[key]['total_stock'] += qty
                    # Çekim için stoklu bir varyantı temsilci seç
                    if not color_groups[key]['representative_variant']:
                        color_groups[key]['representative_variant'] = variant

            missing_variants = []
            for key, group in color_groups.items():
                # Mevcut işlenen rengi atla
                if current_color_id and key == current_color_id:
                    continue
                    
                # Bu rengin herhangi bir bedeninde görsel veya aktif oturum varsa atla
                if group['has_image'] or group['has_active_session']:
                    continue
                    
                # Bu renkte hiç stok yoksa atla
                if group['total_stock'] <= 0:
                    continue
                    
                rep = group['representative_variant']
                if not rep:
                    continue

                missing_variants.append({
                    'id': rep.id,
                    'name': rep.display_name,
                    'barcode': rep.barcode or '',
                    'default_code': rep.default_code or '',
                    'color': group['color_name'],
                    'attributes': group['attributes'],
                    'qty_available': group['total_stock'],
                    'has_active_session': False,
                })

            return {'variants': missing_variants}
        except Exception as e:
            _logger.exception('sibling_variants hatasi: %s', e)
            return {'variants': []}

    @http.route('/ai_studio/find_product', type='json', auth='user', methods=['POST'])
    def find_product(self, query):
        """Barkod, SKU veya isim ile urun ara."""
        try:
            Product = request.env['product.product']
            query = query.strip()

            # 1. Barkod ile ara
            product = Product.search([('barcode', '=', query)], limit=1)
            if not product:
                # 2. Dahili referans ile ara
                product = Product.search([('default_code', '=', query)], limit=1)
            if not product:
                # 3. Isim ile ara
                product = Product.search([('name', 'ilike', query)], limit=5)

            if not product:
                return {'found': False, 'products': []}

            result = []
            for p in product:
                # image_128 binary alani icin guvenli decode
                img128 = False
                try:
                    raw = p.image_128
                    if raw:
                        if isinstance(raw, bytes):
                            img128 = raw.decode('ascii')
                        else:
                            img128 = str(raw)
                except Exception:
                    img128 = False

                # Ürünün cinsiyet attribute'unu bul
                # Ürünün cinsiyet ve vücut tipi attribute'larını bul
                product_gender = ''
                product_body_type = 'standard'
                try:
                    gender_attrs = {'cinsiyet', 'gender'}
                    reyon_attrs = {'reyon', 'department', 'bölüm'}
                    for ptal in p.product_tmpl_id.attribute_line_ids:
                        attr_name = ptal.attribute_id.name.lower().strip()
                        # Cinsiyet kontrolü
                        if any(a in attr_name for a in gender_attrs):
                            for val in ptal.value_ids:
                                val_lower = val.name.lower().strip()
                                if val_lower in ('kadın', 'kadin', 'female', 'women', 'woman', 'bayan'):
                                    product_gender = 'female'
                                elif val_lower in ('erkek', 'male', 'men', 'man', 'bay'):
                                    product_gender = 'male'
                                elif val_lower in ('çocuk', 'cocuk', 'child', 'kids', 'kid'):
                                    product_gender = 'child'
                                elif val_lower in ('unisex',):
                                    product_gender = 'unisex'
                        
                        # Reyon (Büyük Beden) kontrolü
                        if any(a in attr_name for a in reyon_attrs):
                            for val in ptal.value_ids:
                                val_lower = val.name.lower().strip()
                                if 'büyük beden' in val_lower or 'plus size' in val_lower:
                                    product_body_type = 'plus_size'
                                    
                except Exception:
                    product_gender = ''
                    product_body_type = 'standard'

                # Aynı renkteki varyantları bul
                current_color_id = None
                color_attr_names = {'renk', 'color', 'colour'}
                for ptav in p.product_template_attribute_value_ids:
                    attr_name = ptav.attribute_id.name.lower().strip()
                    if any(c in attr_name for c in color_attr_names):
                        current_color_id = ptav.id
                        break

                if current_color_id:
                    color_variants = p.product_tmpl_id.product_variant_ids.filtered(
                        lambda v: current_color_id in v.product_template_attribute_value_ids.ids
                    )
                else:
                    color_variants = p

                # Aktif oturum var mi kontrol et (Aynı renkteki TÜM bedenler taranır - Record Rule aşımı için sudo)
                active_session = request.env['ai.studio.session'].sudo().search([
                    ('product_id', 'in', color_variants.ids),
                    ('state', 'in', ['draft', 'photos_ready', 'processing', 'review', 'failed', 'saving'])
                ], limit=1)

                # Resim var mı kontrol et — aynı renkteki varyantların KENDİ resmine bak
                # Template'ten veya başka renkten miras alınan resme bakma!
                has_image = any(bool(v.image_variant_1920) for v in color_variants)
                
                # DEBUG: Hangi varyant has_image'ı tetikledi?
                if has_image:
                    for v in color_variants:
                        if bool(v.image_variant_1920):
                            _logger.info(
                                "AI Studio DEBUG: has_image=True tetiklendi! "
                                "Aranan barkod=%s, renk_grubu_id=%s, "
                                "image sahibi varyant: id=%d, barkod=%s, name=%s",
                                p.barcode, current_color_id, v.id, v.barcode, v.display_name
                            )

                result.append({
                    'id': p.id,
                    'name': p.display_name,
                    'barcode': p.barcode or '',
                    'default_code': p.default_code or '',
                    'image_128': img128,
                    'categ_id': p.categ_id.id,
                    'categ_name': p.categ_id.display_name,
                    'variant_count': p.product_tmpl_id.product_variant_count,
                    'has_image': has_image,
                    'gender': product_gender,
                    'body_type': product_body_type,
                    'has_active_session': bool(active_session),
                    'active_session_operator': active_session.create_uid.name if active_session else '',
                    'active_session_name': active_session.name if active_session else '',
                })

            return {
                'found': True,
                'products': result,
            }
        except Exception as e:
            _logger.exception('find_product hatasi: %s', e)
            return {'found': False, 'products': [], 'error': str(e)}

    @http.route('/ai_studio/generation_status/<int:session_id>',
                type='json', auth='user', methods=['POST'])
    def generation_status(self, session_id):
        """Oturumdaki AI uretimlerinin durumunu sorgula."""
        try:
            session = request.env['ai.studio.session'].browse(session_id)
            if not session.exists():
                return {'error': 'Oturum bulunamadi.'}

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
        except Exception as e:
            _logger.exception('generation_status hatasi: %s', e)
            return {'error': str(e)}

    @http.route('/ai_studio/approve_generation', type='json', auth='user', methods=['POST'])
    def approve_generation(self, generation_id, is_primary=False):
        """AI uretimini onayla. Sadece onaycı ve yönetici."""
        try:
            if not request.env.user.has_group('ugurlar_ai_studio.group_ai_studio_reviewer'):
                return {'error': 'Bu i\u015flemi yapmaya yetkiniz yok. Onayc\u0131 veya y\u00f6netici rol\u00fc gerekli.'}
            gen = request.env['ai.studio.generation'].browse(int(generation_id))
            if not gen.exists():
                return {'error': 'Uretim bulunamadi.'}

            gen.action_approve()
            if is_primary:
                gen.action_set_primary()

            return {'success': True}
        except Exception as e:
            _logger.exception('approve_generation hatasi: %s', e)
            return {'error': str(e)}

    @http.route('/ai_studio/unapprove_generation', type='json', auth='user', methods=['POST'])
    def unapprove_generation(self, generation_id):
        """AI uretim onayini geri al. Sadece onaycı ve yönetici."""
        try:
            if not request.env.user.has_group('ugurlar_ai_studio.group_ai_studio_reviewer'):
                return {'error': 'Bu işlemi yapmaya yetkiniz yok. Onaycı veya yönetici rolü gerekli.'}
            gen = request.env['ai.studio.generation'].browse(int(generation_id))
            if not gen.exists():
                return {'error': 'Uretim bulunamadi.'}

            gen.action_unapprove()
            return {'success': True}
        except Exception as e:
            _logger.exception('unapprove_generation hatasi: %s', e)
            return {'error': str(e)}

    @http.route('/ai_studio/toggle_exclude', type='json', auth='user', methods=['POST'])
    def toggle_exclude(self, generation_id):
        """AI uretimini haric tut / tekrar dahil et (toggle). Sadece onaycı ve yönetici."""
        try:
            if not request.env.user.has_group('ugurlar_ai_studio.group_ai_studio_reviewer'):
                return {'error': 'Bu işlemi yapmaya yetkiniz yok. Onaycı veya yönetici rolü gerekli.'}
            gen = request.env['ai.studio.generation'].browse(int(generation_id))
            if not gen.exists():
                return {'error': 'Uretim bulunamadi.'}

            gen.action_toggle_exclude()
            return {'success': True, 'is_excluded': gen.is_excluded}
        except Exception as e:
            _logger.exception('toggle_exclude hatasi: %s', e)
            return {'error': str(e)}

    @http.route('/ai_studio/reject_generation', type='json', auth='user', methods=['POST'])
    def reject_generation(self, generation_id, reason_id=None, revision_prompt='', revision_prompt_en=''):
        """AI uretimini reddet ve revizeye gonder. Sadece onaycı ve yönetici."""
        try:
            if not request.env.user.has_group('ugurlar_ai_studio.group_ai_studio_reviewer'):
                return {'error': 'Bu i\u015flemi yapmaya yetkiniz yok. Onayc\u0131 veya y\u00f6netici rol\u00fc gerekli.'}
            gen = request.env['ai.studio.generation'].browse(int(generation_id))
            if not gen.exists():
                return {'error': 'Uretim bulunamadi.'}

            vals = {'is_approved': False}
            if reason_id:
                vals['reject_reason_id'] = int(reason_id)
            if revision_prompt:
                vals['revision_prompt'] = revision_prompt
            if revision_prompt_en:
                vals['revision_prompt_en'] = revision_prompt_en
            gen.write(vals)

            max_rev = int(request.env['ir.config_parameter'].sudo().get_param(
                'ugurlar_ai_studio.max_revisions', '5'
            ))
            if gen.revision_number >= max_rev:
                return {
                    'success': False,
                    'error': 'Maksimum revize sayisina (%d) ulasildi.' % max_rev,
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
                # ═══ REVİZYON BİLGİLERİ — YENİ GEN'E AKTAR ═══
                'revision_prompt': revision_prompt or '',
                'revision_prompt_en': revision_prompt_en or '',
                # NOT: reject_reason_id yeni gen'e EKLENMEZ — review_data
                # reject_reason_id olan kayıtları filtreler (eski versiyon sayar)
            })

            gen.session_id._process_single_generation(new_gen)

            return {
                'success': True,
                'new_generation_id': new_gen.id,
                'revision_number': new_gen.revision_number,
            }
        except Exception as e:
            _logger.exception('reject_generation hatasi: %s', e)
            return {'error': str(e)}

    @http.route('/ai_studio/cancel_revision', type='json', auth='user', methods=['POST'])
    def cancel_revision(self, generation_id):
        """Devam eden veya takılı kalan bir revizyonu iptal et ve önceki haline döndür."""
        try:
            if not request.env.user.has_group('ugurlar_ai_studio.group_ai_studio_reviewer'):
                return {'error': 'Bu işlemi yapmaya yetkiniz yok. Onaycı veya yönetici rolü gerekli.'}
            
            gen = request.env['ai.studio.generation'].browse(int(generation_id))
            if not gen.exists():
                return {'error': 'Üretim bulunamadı.'}
            
            if gen.state not in ('pending', 'processing'):
                return {'error': 'Sadece bekleyen veya işlenen revizyonlar iptal edilebilir.'}

            parent = gen.parent_generation_id
            parent_id = parent.id if parent else False
            
            # Önce ebeveyni geri getir (unlink'ten ÖNCE, ORM cache sorunları önlenir)
            if parent and parent.exists():
                parent.write({
                    'reject_reason_id': False,
                    'revision_prompt': False,
                    'revision_prompt_en': False,
                    'state': 'done',  # Ebeveynin durumunu tamamlandı yap
                })
                _logger.info(
                    'cancel_revision: parent gen %s geri yüklendi (reject_reason temizlendi), child gen %s silinecek',
                    parent_id, gen.id
                )
            else:
                _logger.warning('cancel_revision: parent bulunamadı (gen=%s, parent_id=%s)', gen.id, parent_id)
            
            # Yeni üretimi sil
            gen.unlink()
                
            return {'success': True}
        except Exception as e:
            _logger.exception('cancel_revision hatasi: %s', e)
            return {'error': str(e)}

    @http.route('/ai_studio/translate_revision', type='json', auth='user', methods=['POST'])
    def translate_revision(self, text=''):
        """Türkçe revizyon metnini İngilizce'ye çevir.
        
        Öncelik: deep-translator (ücretsiz)
        Fallback: Gemini Flash (~$0.001)
        """
        if not text or not text.strip():
            return {'translated': ''}
        
        # YÖNTEM 1: deep-translator (ÜCRETSİZ)
        try:
            from deep_translator import GoogleTranslator
            translated = GoogleTranslator(source='tr', target='en').translate(text)
            if translated:
                return {'translated': translated}
        except ImportError:
            pass
        except Exception as e:
            _logger.warning('deep-translator hatasi: %s', e)
        
        # YÖNTEM 2: Gemini Flash (FALLBACK)
        try:
            gemini_key = request.env['ir.config_parameter'].sudo().get_param(
                'ugurlar_ai_studio.gemini_api_key', ''
            )
            if not gemini_key:
                return {'translated': text}
            
            import requests as _req
            prompt = (
                "Translate this fashion image editing instruction to clear, precise English. "
                "Context: This is an edit request for a fashion e-commerce photo. "
                "Return ONLY the English translation, nothing else.\n\n"
                f"Turkish instruction: {text}"
            )
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={gemini_key}"
            resp = _req.post(url, json={
                'contents': [{'parts': [{'text': prompt}]}],
            }, headers={'Content-Type': 'application/json'}, timeout=10)
            
            if resp.status_code == 200:
                data = resp.json()
                candidates = data.get('candidates', [])
                if candidates:
                    en_text = candidates[0].get('content', {}).get('parts', [{}])[0].get('text', '').strip()
                    if en_text:
                        return {'translated': en_text}
        except Exception as e:
            _logger.warning('Gemini ceviri hatasi: %s', e)
        
        return {'translated': text}

    @http.route('/ai_studio/retry_generation', type='json', auth='user', methods=['POST'])
    def retry_generation(self, generation_id):
        """Başarısız üretimi tekrar dene. Onaycı ve yönetici yetkili."""
        try:
            if not request.env.user.has_group('ugurlar_ai_studio.group_ai_studio_reviewer'):
                return {'error': 'Bu işlemi yapmaya yetkiniz yok.'}

            gen = request.env['ai.studio.generation'].browse(int(generation_id))
            if not gen.exists():
                return {'error': 'Üretim bulunamadı.'}
            if gen.state != 'failed':
                return {'error': 'Sadece başarısız üretimler tekrar denenebilir.'}

            gen.action_retry()
            return {
                'success': True,
                'generation_id': gen.id,
            }
        except Exception as e:
            _logger.exception('retry_generation hatasi: %s', e)
            return {'error': str(e)}

    @http.route('/ai_studio/complete_session', type='json', auth='user', methods=['POST'])
    def complete_session(self, session_id, approved_items=None):
        """Oturumu tamamla ve gorselleri urune kaydet. Sadece onaycı ve yönetici.
        
        Doğrudan senkron kaydetme yapar (cron'a bırakmaz).
        """
        import psycopg2
        try:
            if not request.env.user.has_group('ugurlar_ai_studio.group_ai_studio_reviewer'):
                return {'success': False, 'error': 'Bu işlemi yapmaya yetkiniz yok. Onaycı veya yönetici rolü gerekli.'}
            session = request.env['ai.studio.session'].browse(int(session_id))
            if not session.exists():
                return {'success': False, 'error': 'Oturum bulunamadı.'}

            # 1. is_primary değerlerini güncelle
            if approved_items:
                for item in approved_items:
                    gen_id = item.get('id')
                    is_primary = item.get('is_primary', False)
                    gen = request.env['ai.studio.generation'].browse(int(gen_id))
                    if gen.exists() and gen.session_id.id == session.id:
                        gen.write({'is_primary': is_primary})

            # 2. Onaylı görselleri bul
            approved = session.generation_ids.filtered(
                lambda g: g.is_approved and g.state == 'done' and not g.is_excluded
            )
            if not approved:
                return {'success': False, 'error': 'En az bir görsel onaylanmalı.'}

            # 3. Primary kontrolü & otomatik atama
            if not approved.filtered(lambda g: g.is_primary):
                front = approved.filtered(lambda g: g.photo_type == 'front')[:1]
                primary = front or approved[0]
                primary.is_primary = True

            # 4. Doğrudan ürüne kaydet (senkron)
            session._save_to_product(approved)

            # 5. Oturumu tamamlandı olarak işaretle
            session.reviewer_id = request.env.user
            session.state = 'done'
            session.date_done = fields.Datetime.now()
            session.message_post(
                body=_('%d onaylı görsel ürüne başarıyla kaydedildi.') % len(approved),
            )

            _logger.info("complete_session: %s (%s) başarıyla tamamlandı, %d görsel kaydedildi.",
                         session.name, session.id, len(approved))
            return {'success': True}

        except psycopg2.Error as e:
            if getattr(e, 'pgcode', '') in ('40001', '25P02'):
                raise
            _logger.exception('complete_session veritabanı hatası (session=%s): %s', session_id, e)
            return {'success': False, 'error': 'Veritabanı hatası: %s' % str(e)[:200]}
        except Exception as e:
            _logger.exception('complete_session hatasi (session=%s): %s', session_id, e)
            return {'success': False, 'error': 'Kaydetme hatası: %s' % str(e)[:200]}

    # ═══════════════════════════════════════════════════════════
    # İNCELEME KİLİDİ (Concurrency Control)
    # ═══════════════════════════════════════════════════════════
    REVIEW_LOCK_TIMEOUT_MINUTES = 5

    @http.route('/ai_studio/acquire_lock', type='json', auth='user', methods=['POST'])
    def acquire_review_lock(self, session_id, lock_token=''):
        """Oturumu inceleme için kilitle. Başka kullanıcı/sekme inceliyorsa engelle."""
        try:
            session = request.env['ai.studio.session'].browse(int(session_id))
            if not session.exists():
                return {'success': False, 'error': 'Oturum bulunamadı.'}

            now = fields.Datetime.now()
            current_user = request.env.user
            from datetime import timedelta

            # Mevcut kilit kontrolü
            if session.review_locked_by and session.review_lock_time:
                lock_age = now - session.review_lock_time
                if lock_age < timedelta(minutes=self.REVIEW_LOCK_TIMEOUT_MINUTES):
                    # Kilit aktif (5dk henüz dolmamış)
                    # 1. Eğer jeton ve kullanıcı tam eşleşiyorsa (aynı sekme/yenileme) -> kilit süresini uzat
                    if lock_token and session.review_lock_token == lock_token:
                        session.sudo().write({'review_lock_time': now})
                        return {'success': True, 'locked_by_self': True}
                    
                    # 2. Eğer kilit başka bir kullanıcıya veya farklı bir sekmeye aitse -> ENGELLE!
                    lock_minutes = int(lock_age.total_seconds() // 60)
                    lock_seconds = int(lock_age.total_seconds() % 60)
                    locker_name = session.review_locked_by.name or 'Başka bir kullanıcı'
                    _logger.warning('Oturum %s KİLİTLİ! İnceleyen: %s (token: %s). İsteyen: %s (token: %s)',
                                    session.id, locker_name, session.review_lock_token, current_user.name, lock_token)
                    return {
                        'success': False,
                        'locked': True,
                        'locked_by_name': locker_name,
                        'locked_by_id': session.review_locked_by.id,
                        'lock_duration': f'{lock_minutes}dk {lock_seconds}sn önce açtı',
                    }
                # Süresi dolmuş — kilidi devral

            # Kilidi al
            _logger.info('Oturum %s kilidi ALINDI: kullanıcı %s (token: %s)', session.id, current_user.name, lock_token)
            session.sudo().write({
                'review_locked_by': current_user.id,
                'review_lock_time': now,
                'review_lock_token': lock_token or '',
            })
            return {'success': True, 'locked_by_self': True}
        except Exception as e:
            _logger.exception('acquire_lock hatasi: %s', e)
            return {'success': False, 'error': str(e)}

    @http.route('/ai_studio/release_lock', type='json', auth='user', methods=['POST'])
    def release_review_lock(self, session_id, lock_token=''):
        """İnceleme kilidini bırak."""
        try:
            session = request.env['ai.studio.session'].browse(int(session_id))
            if not session.exists():
                return {'success': False}

            current_user = request.env.user
            # Token eşleşiyorsa VEYA aynı kullanıcıysa VEYA yöneticiyse kilidi kaldır
            if (lock_token and session.review_lock_token == lock_token) or \
               (session.review_locked_by and session.review_locked_by.id == current_user.id) or \
               current_user.has_group('ugurlar_ai_studio.group_ai_studio_manager'):
                _logger.info('Oturum %s kilidi BIRAKILDI: kullanıcı %s', session.id, current_user.name)
                session.sudo().write({
                    'review_locked_by': False,
                    'review_lock_time': False,
                    'review_lock_token': False,
                })
            return {'success': True}
        except Exception as e:
            _logger.exception('release_lock hatasi: %s', e)
            return {'success': False}

    @http.route('/ai_studio/heartbeat_lock', type='json', auth='user', methods=['POST'])
    def heartbeat_review_lock(self, session_id, lock_token=''):
        """Kilit heartbeat — her 2dk'da çağrılır, kilidi canlı tutar."""
        try:
            session = request.env['ai.studio.session'].browse(int(session_id))
            if not session.exists():
                return {'success': False}

            if (lock_token and session.review_lock_token == lock_token) or \
               (session.review_locked_by and session.review_locked_by.id == request.env.user.id):
                session.sudo().write({'review_lock_time': fields.Datetime.now()})
                return {'success': True}
            return {'success': False, 'error': 'Kilit size ait değil.'}
        except Exception as e:
            return {'success': False}

    @http.route('/ai_studio/review_data', type='json', auth='user', methods=['POST'])
    def get_review_data(self, session_id, lock_token=''):
        """Oturumun tum generation verilerini inceleme popup'i icin dondurur."""
        try:
            session = request.env['ai.studio.session'].browse(int(session_id))
            if not session.exists():
                return {'error': 'Oturum bulunamadı.'}

            # ═══ SERVER-SIDE LOCK CONTROL ═══
            now = fields.Datetime.now()
            from datetime import timedelta
            if session.review_locked_by and session.review_lock_time:
                lock_age = now - session.review_lock_time
                if lock_age < timedelta(minutes=self.REVIEW_LOCK_TIMEOUT_MINUTES):
                    # Kilit aktif
                    if lock_token and session.review_lock_token and session.review_lock_token != lock_token:
                        locker_name = session.review_locked_by.name or 'Başka bir kullanıcı'
                        return {
                            'error': f'⚠️ Bu oturum şu an {locker_name} tarafından başka bir ekranda/kullanıcıda inceleniyor. Lütfen tamamlanmasını bekleyin.'
                        }
                    elif not lock_token and session.review_locked_by.id != request.env.user.id:
                        locker_name = session.review_locked_by.name or 'Başka bir kullanıcı'
                        return {
                            'error': f'⚠️ Bu oturum şu an {locker_name} tarafından inceleniyor.'
                        }

            # Son versiyon generation'lari al (done, failed, pending, processing)
            # Reddedilmis olanlari haric tut (reject_reason_id var = eski versiyon)
            generations = session.generation_ids.filtered(
                lambda g: g.state in ('done', 'failed', 'pending', 'processing') and not g.reject_reason_id
            ).sorted(key=lambda g: (
                {'front': 0, 'back': 1, 'side': 2, 'detail': 3}.get(g.photo_type, 9),
                g.revision_number
            ))

            # Eğer hiçbir görsel ana görsel değilse varsayılan olarak ön görseli işaretle
            if generations and not any(g.is_primary for g in generations):
                front_gen = generations.filtered(lambda g: g.photo_type == 'front')[:1] or generations[:1]
                if front_gen:
                    front_gen.write({'is_primary': True})

            items = []
            for gen in generations:
                orig_url = ''
                if gen.source_photo_id:
                    orig_url = '/web/image/ai.studio.photo/%d/image_original' % gen.source_photo_id.id
                else:
                    orig_url = '/web/image/ai.studio.generation/%d/original_image' % gen.id

                gen_url = '/web/image/ai.studio.generation/%d/generated_image' % gen.id

                items.append({
                    'id': gen.id,
                    'photo_type': gen.photo_type,
                    'photo_type_label': dict(gen._fields['photo_type'].selection).get(gen.photo_type, gen.photo_type),
                    'state': gen.state,
                    'is_approved': gen.is_approved,
                    'is_primary': gen.is_primary,
                    'revision_number': gen.revision_number,
                    'original_url': orig_url,
                    'original_url_full': orig_url,
                    'generated_url': gen_url,
                    'generated_url_full': gen_url,
                    'error_message': gen.error_message or '',
                    'pending_revision': gen.state in ('pending', 'processing'),
                    'is_excluded': gen.is_excluded,
                })

            # Red sebepleri
            reasons = request.env['ai.studio.reject.reason'].search([])
            reason_list = [{'id': r.id, 'name': r.name} for r in reasons]

            # Sonraki review session
            next_session = request.env['ai.studio.session'].search([
                ('state', '=', 'review'),
                ('id', '!=', session.id),
            ], limit=1, order='id asc')

            # Kullanıcı rolünü belirle
            user = request.env.user
            if user.has_group('ugurlar_ai_studio.group_ai_studio_manager'):
                user_role = 'manager'
            elif user.has_group('ugurlar_ai_studio.group_ai_studio_reviewer'):
                user_role = 'reviewer'
            else:
                user_role = 'operator'

            # Özel ürün adı oluşturma (Renk her zaman parantez içinde gözüksün)
            product_name = ''
            if session.product_id:
                product_name = session.product_id.display_name
                color_name = ''
                color_attr_names = {'renk', 'color', 'colour'}
                for ptav in session.product_id.product_template_attribute_value_ids:
                    if any(c in ptav.attribute_id.name.lower().strip() for c in color_attr_names):
                        color_name = ptav.name
                        break
                
                # Eğer renk adı bulunmuşsa ve Odoo'nun display_name'inde geçmiyorsa ekle
                if color_name and color_name not in product_name:
                    if product_name.endswith(')'):
                        # Parantez içine ekle (Örn: "(L)" -> "(Siyah, L)")
                        product_name = product_name[:-1] + f" - {color_name})"
                    else:
                        product_name = f"{product_name} ({color_name})"

            return {
                'session_id': session.id,
                'session_name': session.name,
                'product_name': product_name,
                'items': items,
                'reject_reasons': reason_list,
                'next_session_id': next_session.id if next_session else False,
                'session_state': session.state,
                'user_role': user_role,
            }
        except Exception as e:
            _logger.exception('review_data hatasi: %s', e)
            return {'error': str(e)}

    @http.route('/ai_studio/get_presets', type='json', auth='user', methods=['POST'])
    def get_presets(self, garment_type=None, gender=None, body_type=None):
        """Aktif manken presetlerini getir. Opsiyonel cinsiyet ve vücut tipi filtresi."""
        try:
            domain = [('active', '=', True)]
            if garment_type:
                domain.append(('garment_type', '=', garment_type))
            
            # Vücut tipi filtresi (Büyük beden vs standart)
            domain.append(('body_type', '=', body_type or 'standard'))
            # Cinsiyet filtresi: ürün cinsiyetine göre uygun presetleri göster
            if gender and gender in ('female', 'male', 'child'):
                # Seçilen cinsiyete uygun + unisex presetleri göster
                domain.append(('gender', 'in', [gender, 'unisex']))
            elif gender == 'unisex':
                # Unisex ürünlerde tüm presetleri göster
                pass

            presets = request.env['ai.studio.model.preset'].search(domain)
            result = []
            for p in presets:
                # Safe base64 decoding for preview_image or model_image_front
                preview_data = False
                raw_preview = p.preview_image or p.model_image_front
                if raw_preview:
                    try:
                        if isinstance(raw_preview, bytes):
                            preview_data = raw_preview.decode('ascii')
                        else:
                            preview_data = str(raw_preview)
                    except Exception:
                        preview_data = False

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
                    'preview_image': preview_data,
                })

            return {'presets': result}
        except Exception as e:
            _logger.exception('get_presets hatasi: %s', e)
            return {'presets': []}

    @http.route('/ai_studio/get_reject_reasons', type='json', auth='user', methods=['POST'])
    def get_reject_reasons(self):
        """Aktif red sebeplerini getir."""
        try:
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
        except Exception as e:
            _logger.exception('get_reject_reasons hatasi: %s', e)
            return {'reasons': []}

    @http.route('/ai_studio/get_prompt_templates', type='json', auth='user', methods=['POST'])
    def get_prompt_templates(self, scope=None, category_id=None):
        """Prompt sablonlarini getir."""
        try:
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
        except Exception as e:
            _logger.exception('get_prompt_templates hatasi: %s', e)
            return {'templates': []}

    @http.route('/ai_studio/dashboard_stats', type='json', auth='user', methods=['POST'])
    def dashboard_stats(self):
        """Dashboard istatistikleri."""
        try:
            Session = request.env['ai.studio.session']
            Generation = request.env['ai.studio.generation']

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
                'user_role': 'manager' if request.env.user.has_group('ugurlar_ai_studio.group_ai_studio_manager')
                    else 'reviewer' if request.env.user.has_group('ugurlar_ai_studio.group_ai_studio_reviewer')
                    else 'operator',
            }
        except Exception as e:
            _logger.exception('dashboard_stats hatasi: %s', e)
            return {
                'month_sessions': 0,
                'month_generations': 0,
                'month_approval_rate': 0,
                'month_cost': 0,
                'today_sessions': 0,
            }

    @http.route('/ai_studio/analyze_garment', type='json', auth='user', methods=['POST'])
    def analyze_garment(self, image_data):
        """Kiyafet gorseli AI ile analiz et — tur, renk, kumas, detaylar."""
        try:
            api_key = request.env['ir.config_parameter'].sudo().get_param(
                'ugurlar_ai_studio.fal_api_key', ''
            )
            gemini_api_key = request.env['ir.config_parameter'].sudo().get_param(
                'ugurlar_ai_studio.gemini_api_key', ''
            )
            if not api_key and not gemini_api_key:
                return {'error': 'fal.ai veya Gemini API anahtarı tanımlanmamış. Ayarlar > AI Studio'}

            # Analiz yap
            from ..services.garment_analyzer import analyze_garment as do_analyze
            
            if gemini_api_key:
                # Direct Gemini supports base64/data URI/raw string directly
                analysis = do_analyze(api_key, image_data, gemini_api_key=gemini_api_key)
            else:
                # Base64 gorseli fal.ai'ya yukle
                from ..services.fal_provider import FalProvider
                provider = FalProvider(api_key)
                image_url = provider.upload_image(image_data)
                analysis = do_analyze(api_key, image_url)

            return {'success': True, 'analysis': analysis}
        except Exception as e:
            _logger.exception('analyze_garment hatasi: %s', e)
            return {'error': str(e)}

    @http.route('/ai_studio/build_prompt', type='json', auth='user', methods=['POST'])
    def build_prompt(self, analysis, preset_id=None, lock_ids=None, extra_prompt=''):
        """Analiz sonuclarina gore AI gorsel uretim promptu olustur."""
        try:
            # Preset bilgisi
            preset_data = {}
            if preset_id:
                preset = request.env['ai.studio.model.preset'].browse(int(preset_id))
                if preset.exists():
                    preset_data = {
                        'gender': preset.gender,
                        'body_type': preset.body_type,
                        'target_audience': preset.target_audience or '',
                    }

            # Prompt lock'lari
            prompt_locks = []
            if lock_ids:
                templates = request.env['ai.studio.prompt.template'].browse(lock_ids)
                for t in templates:
                    prompt_locks.append(t.prompt_text)
            else:
                # Varsayilan olarak tum global lock'lari kullan
                all_locks = request.env['ai.studio.prompt.template'].search([
                    ('scope', '=', 'global'),
                    ('active', '=', True),
                ])
                for t in all_locks:
                    prompt_locks.append(t.prompt_text)

            from ..services.garment_analyzer import build_generation_prompt
            result = build_generation_prompt(
                analysis, preset_data, prompt_locks, extra_prompt
            )

            return {'success': True, 'prompt': result}
        except Exception as e:
            _logger.exception('build_prompt hatasi: %s', e)
            return {'error': str(e)}

    @http.route('/ai_studio/generate_image', type='json', auth='user', methods=['POST'])
    def generate_image(self, session_id, photo_id, preset_id, prompt=None):
        """AI gorsel uretim — fal.ai FASHN virtual try-on."""
        try:
            api_key = request.env['ir.config_parameter'].sudo().get_param(
                'ugurlar_ai_studio.fal_api_key', ''
            )
            if not api_key:
                return {'error': 'fal.ai API anahtari tanimlanmamis.'}

            session = request.env['ai.studio.session'].browse(int(session_id))
            if not session.exists():
                return {'error': 'Oturum bulunamadi.'}

            photo = request.env['ai.studio.photo'].browse(int(photo_id))
            if not photo.exists():
                return {'error': 'Fotograf bulunamadi.'}

            preset = request.env['ai.studio.model.preset'].browse(int(preset_id))
            if not preset.exists():
                return {'error': 'Manken preseti bulunamadi.'}

            from ..services.fal_provider import FalProvider
            provider = FalProvider(api_key)

            # Gorsel yukle
            garment_url = provider.upload_image(photo.image_original)

            # Manken gorseli
            model_image = preset.model_image_front
            if photo.photo_type == 'back' and preset.model_image_back:
                model_image = preset.model_image_back

            if not model_image:
                return {'error': 'Manken gorseli bulunamadi.'}

            model_image_raw = model_image
            if isinstance(model_image_raw, bytes):
                model_image_raw = model_image_raw.decode('ascii')
            model_url = provider.upload_image(model_image_raw)

            # Kategori belirle
            category = session.category or 'tops'

            # Virtual try-on
            result = provider.virtual_tryon(
                model_image_url=model_url,
                garment_image_url=garment_url,
                category=category,
            )

            if result.get('image_url'):
                # Sonucu indir ve kaydet
                import requests as req_lib
                img_response = req_lib.get(result['image_url'], timeout=120)
                generated_b64 = base64.b64encode(img_response.content).decode()

                # Generation kaydı olustur
                gen = request.env['ai.studio.generation'].create({
                    'session_id': session.id,
                    'source_photo_id': photo.id,
                    'photo_type': photo.photo_type,
                    'original_image': photo.image_original,
                    'generated_image': generated_b64,
                    'state': 'done',
                    'cost': result.get('cost', 0.075),
                    'provider': 'fal',
                    'fal_request_id': result.get('request_id', ''),
                })

                return {
                    'success': True,
                    'generation_id': gen.id,
                    'cost': result.get('cost', 0.075),
                }

            return {'error': 'AI görsel üretilemedi.'}
        except Exception as e:
            from ..services.fal_error_handler import parse_fal_error
            parsed = parse_fal_error(e)
            _logger.exception('generate_image hatasi: %s', e)
            return {'error': parsed['message']}

