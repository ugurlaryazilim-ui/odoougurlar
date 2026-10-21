import logging
import base64
import hashlib
import time
import json
import uuid
import io
import os
import random
import re
import sys
import requests
from datetime import timedelta
from PIL import Image, ImageDraw, Image as PILImage

from odoo import models, fields, api, _
from odoo.exceptions import AccessError, UserError, ValidationError

from ..services.garment_analyzer import (
    clear_usage_recorder, design_hint, set_usage_context, set_usage_recorder,
)
from .ai_studio_usage import GEMINI_INPUT_PRICE, GEMINI_OUTPUT_PRICE

_logger = logging.getLogger(__name__)

# AI işleri HTTP/cron worker'ı içinde thread açılarak DEĞİL, kuyruk cron'larıyla
# işlenir (data/cron.xml). Her slot cron'u aynı anda tek iş yürütür; slot numarası
# concurrent_limit'i aşan cron çalışmaz → eşzamanlılık tüm worker'lar için globaldir.
AI_QUEUE_CRONS = ('ugurlar_ai_studio.cron_ai_queue_1', 'ugurlar_ai_studio.cron_ai_queue_2')
# NEDEN: cron worker'ı limit_time_real (2400 sn) aşarsa süreç öldürülür. Odoo 19'da
# ir_cron._process_jobs_loop bir turda hazır TÜM cron işlerini sırayla koşar ve watchdog
# yalnız turlar arasında sıfırlanır; iki kuyruk slotu aynı turda art arda koşabilir. Bu
# yüzden bütçe iş başına değil tur başınadır (bkz. _cron_round_cursor): bütçe dolduktan
# sonra yeni iş alınmaz, oturum işi yeni görünüme başlamaz. Tek görünüm (hazırlık +
# try-on 180 sn + denetim/yeniden üretim) en kötü ~15 dk → AI işleri turda ≤ 600 + 900 =
# 1500 sn. Turdaki diğer cron'ların (Nebim vb.) süresi bu bütçeye dahil DEĞİL; onlara kalan
# pay 2400 - 1500 = 900 sn. Bütçeyi büyütmek bu payı yer (pay için limit_time_real_cron).
QUEUE_JOB_BUDGET_SECONDS = 600
_queue_limit_warned = False


def _cron_round_cursor():
    """Şu an koşan ir.cron turunun cron_cr'ı (tur kimliği); cron dışında None."""
    # DIKKAT: Odoo 19 çekirdek iç yapısına bağlı (base/models/ir_cron.py
    # _process_jobs_loop(cron_cr, ...)). Metot kaldırılır/yeniden adlandırılır/sarmalanırsa
    # (__code__ yok) ya da çerçeve bulunamazsa None döner ve bütçe iş başına uygulanır; burada
    # istisna kuyruğu tümden durdururdu. test_round_cursor_found_in_core_loop değişikliği yakalar.
    from odoo.addons.base.models.ir_cron import IrCron
    code = getattr(getattr(IrCron, '_process_jobs_loop', None), '__code__', None)
    if code is None:
        return None
    frame = sys._getframe(1)
    while frame is not None:
        if frame.f_code is code:
            return frame.f_locals.get('cron_cr')
        frame = frame.f_back
    return None

# Oturum kirası: bir kuyruk işi oturumu işlerken her adımda yenilenir. Süresi
# dolmuş kira = ölü iş → cron devralabilir.
LEASE_MINUTES = 10
# fal'e gönderilmiş ama bu süre içinde sonuçlanmamış iş başarısız sayılır
SUBMITTED_TIMEOUT_MINUTES = 30
# Manken üretimi (3 görünüm, her biri ≤ ~2 dk fal çağrısı) bu süreyi aşarsa iş ölmüş sayılır
MANNEQUIN_STUCK_MINUTES = 60
_UTC_NOW_SQL = "(now() at time zone 'UTC')"
# Oturum işinin görünüm sırası (_process_ai_thread_body: ordered_gens)
VIEW_ORDER = ('front', 'back', 'side', 'detail')


def _lease_owner():
    import socket
    # NEDEN: workers=0 modunda birden çok cron thread'i aynı süreçte koşar; uuid her işi ayırır
    return '%s:%s:%s' % (socket.gethostname(), os.getpid(), uuid.uuid4().hex[:12])


def _try_acquire_lease(cr, session_id, owner):
    """Kira yoksa / süresi dolmuşsa / zaten bizdeyse al (commit etmez)."""
    cr.execute(
        "UPDATE ai_studio_session SET ai_lease_owner = %s, "
        "ai_lease_until = " + _UTC_NOW_SQL + " + make_interval(mins => %s) "
        "WHERE id = %s AND (ai_lease_until IS NULL OR ai_lease_until < " + _UTC_NOW_SQL +
        " OR ai_lease_owner = %s) RETURNING id",
        (owner, LEASE_MINUTES, session_id, owner),
    )
    return bool(cr.fetchone())


def _renew_session_lease(cr, session_id, owner):
    """Kirayı thread'in kendi cursor'ı ile uzat (commit çağıranın sorumluluğunda)."""
    cr.execute(
        "UPDATE ai_studio_session SET ai_lease_until = " + _UTC_NOW_SQL +
        " + make_interval(mins => %s) WHERE id = %s AND ai_lease_owner = %s",
        (LEASE_MINUTES, session_id, owner),
    )


def _release_session_lease(pool, session_id, owner):
    try:
        with pool.cursor() as lcr:
            lcr.execute(
                "UPDATE ai_studio_session SET ai_lease_until = NULL, ai_lease_owner = NULL "
                "WHERE id = %s AND ai_lease_owner = %s", (session_id, owner))
            lcr.commit()
    except Exception as e:
        _logger.warning('Oturum kirası bırakılamadı (session_id=%s): %s', session_id, e)


def _make_enqueue_recorder(pool, gen_id):
    """fal request_id'yi kuyruğa girer girmez ayrı transaction'da kaydeden callback.

    lock_timeout: ana cursor satırı kilitli tutuyorsa thread kendini beklemesin.
    """
    def _on_enqueue(request_id, app):
        try:
            with pool.cursor() as rcr:
                rcr.execute("SET LOCAL lock_timeout = '5s'")
                rcr.execute(
                    "UPDATE ai_studio_generation SET fal_request_id = %s, fal_app = %s, "
                    "submitted_at = " + _UTC_NOW_SQL + " WHERE id = %s",
                    (request_id, app, gen_id),
                )
                rcr.commit()
            _logger.info('fal isteği kuyrukta (gen=%s, request_id=%s)', gen_id, request_id)
        except Exception as e:
            _logger.warning('fal request_id kaydedilemedi (gen=%s): %s', gen_id, e)
    return _on_enqueue


def _make_usage_recorder(pool, uid, input_price, output_price):
    """AI çağrısının kullanımını ayrı transaction'da ai_studio_usage'a yazan callback.

    Ayrı cursor: ana işlem geri alınsa da harcama kaydı kalır. Yalnızca INSERT olduğundan
    ana cursor'ın güncellediği satırlarla çakışmaz. Fiyatlar USD / 1M token.
    """
    def _record(vals):
        cost = vals.get('cost')
        if cost is None:
            cost = ((vals.get('input_tokens') or 0) * input_price
                    + (vals.get('output_tokens') or 0) * output_price) / 1e6
        try:
            with pool.cursor() as rcr:
                rcr.execute("SET LOCAL lock_timeout = '5s'")
                rcr.execute(
                    "INSERT INTO ai_studio_usage (session_id, generation_id, product_id, user_id, provider, "
                    "step, model, input_tokens, output_tokens, image_count, duration, status, cost, "
                    "create_uid, write_uid, create_date, write_date) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, "
                    + _UTC_NOW_SQL + ", " + _UTC_NOW_SQL + ")",
                    (vals.get('session_id') or None, vals.get('generation_id') or None,
                     vals.get('product_id') or None, vals.get('user_id') or None,
                     vals.get('provider'), vals.get('step') or 'other', vals.get('model') or '',
                     vals.get('input_tokens') or 0, vals.get('output_tokens') or 0,
                     vals.get('image_count') or 0, vals.get('duration') or 0.0,
                     vals.get('status') or 'ok', cost, uid, uid),
                )
                rcr.commit()
        except Exception as e:
            _logger.warning('AI kullanım kaydı yazılamadı (%s/%s): %s', vals.get('provider'), vals.get('step'), e)
    return _record


def _start_usage_recording(env, session, generation=None):
    """Bu thread'deki Gemini / fal çağrılarını oturuma (ve üretime) yazan kaydediciyi kurar.

    session boş olabilir (manken üretimi, oturumsuz çeviri): kayıt oturumsuz yazılır.
    """
    get_param = env['ir.config_parameter'].sudo().get_param

    def _price(key, default):
        try:
            return float(get_param('ugurlar_ai_studio.' + key) or default)
        except (TypeError, ValueError):
            return default

    set_usage_recorder(
        _make_usage_recorder(env.registry, env.uid,
                             _price('gemini_input_price', GEMINI_INPUT_PRICE),
                             _price('gemini_output_price', GEMINI_OUTPUT_PRICE)),
        session_id=session.id if session else None,
        generation_id=generation.id if generation else None,
        product_id=session.product_id.id if session else None,
        user_id=(session.user_id.id if session else None) or env.uid,
    )


# Yeni bir deneme başlarken önceki fal isteğinin izi silinir; aksi halde cron bu
# üretim için ÖNCEKİ isteğin sonucunu "kurtarır".
CLEAR_FAL_REQUEST = {'fal_request_id': False, 'fal_app': False, 'submitted_at': False}

# Kuyruğun hangi ürün(ler)e yazacağını belirler; yetkisiz değişim onayları düşürür (J10 KK2).
APPROVAL_TARGET_FIELDS = frozenset({'product_id', 'apply_to_siblings', 'session_type'})


def _is_client_timeout(exc):
    """fal SDK istemci zaman aşımı mı? (iş fal tarafında sürmeye ve ücretlenmeye devam eder)"""
    name = exc.__class__.__name__.lower()
    return 'timeout' in name


def _get_request_id(cr, gen_id):
    cr.execute("SELECT fal_request_id FROM ai_studio_generation WHERE id = %s", (gen_id,))
    row = cr.fetchone()
    return row and row[0]


def _failure_vals(exc, message=None):
    """Hata için generation değerleri (mesaj + tip + yeniden denenebilirlik)."""
    from ..services.fal_error_handler import parse_fal_error
    parsed = parse_fal_error(exc)
    return {
        'state': 'failed',
        'error_message': (message or parsed['message'])[:500],
        'error_type': parsed.get('error_type') or 'unknown',
        'is_retryable': bool(parsed.get('is_retryable', True)),
    }


def _convert_to_jpeg(img_data_bytes, quality=92):
    """PNG/WebP gibi büyük formatları JPEG'e çevir.
    
    AI üretilen görseller genelde PNG formatında gelir (2-5 MB).
    JPEG'e çevirmek boyutu 5-10x küçültür (~200-400 KB).
    Zaten JPEG ise dokunmaz.
    
    Args:
        img_data_bytes: Ham görsel verisi (bytes)
        quality: JPEG kalitesi (1-100), 92 fotoğraf için ideal
    Returns:
        bytes: JPEG formatında görsel verisi
    """
    try:
        from PIL import Image as PILImage
        img = PILImage.open(io.BytesIO(img_data_bytes))
        
        # Zaten JPEG ise dokunma
        if img.format == 'JPEG':
            return img_data_bytes
        
        # RGBA → RGB dönüşümü (JPEG alfa kanalı desteklemez)
        if img.mode in ('RGBA', 'LA', 'P'):
            background = PILImage.new('RGB', img.size, (255, 255, 255))
            if img.mode == 'P':
                img = img.convert('RGBA')
            background.paste(img, mask=img.split()[-1] if 'A' in img.mode else None)
            img = background
        elif img.mode != 'RGB':
            img = img.convert('RGB')
        
        buf = io.BytesIO()
        img.save(buf, format='JPEG', quality=quality, optimize=True)
        result = buf.getvalue()
        
        _logger.info(
            "Görsel JPEG'e çevrildi: %s → JPEG, %d KB → %d KB (%%%.0f küçülme)",
            'PNG', len(img_data_bytes) // 1024, len(result) // 1024,
            (1 - len(result) / len(img_data_bytes)) * 100 if img_data_bytes else 0
        )
        return result
    except Exception as e:
        _logger.warning("JPEG dönüşümü başarısız, orijinal kullanılıyor: %s", e)
        return img_data_bytes

def _is_db_conflict(exc):
    """Hata (veya sarmaladığı hata) bir DB eşzamanlılık/kilit çakışması mı?"""
    from psycopg2 import errors as pg_errors
    conflict_types = (pg_errors.SerializationFailure, pg_errors.LockNotAvailable,
                      pg_errors.DeadlockDetected)
    seen = set()
    while exc is not None and id(exc) not in seen:
        if isinstance(exc, conflict_types):
            return True
        seen.add(id(exc))
        exc = getattr(exc, 'orig', None) or exc.__cause__ or exc.__context__
    return False


def _get_seedream_image_size(env):
    """Ayarlardaki Seedream çıktı boyutunu fal image_size dict'i olarak döndür."""
    from ..services.fal_provider import FalProvider
    key = env['ir.config_parameter'].sudo().get_param('ugurlar_ai_studio.seedream_image_size', 'hd')
    return FalProvider.SEEDREAM_IMAGE_SIZES.get(key, FalProvider.SEEDREAM_IMAGE_SIZES['hd'])


# Ayar değeri → virtual_tryon model_name. v4 Edit seed alır/döndürür (ön görünüm seed'i
# arka/yan çekimlere aktarılır); v5 Pro Edit seed desteklemez.
TRYON_MODELS = {
    'seedream_v4': 'seedream/v4/edit',
    'seedream_v5_pro': 'seedream/v5/pro/edit',
    # Özel try-on modeli: ürün piksellerini taşır, istem almaz (A/B karşılaştırma için)
    'fashn_v16': 'fashn/tryon/v1.6',
}


def _get_tryon_model(env):
    """Ayarlardaki fal try-on modeli (varsayılan: Seedream v4 Edit)."""
    key = env['ir.config_parameter'].sudo().get_param('ugurlar_ai_studio.fal_tryon_model', 'seedream_v4')
    return TRYON_MODELS.get(key, TRYON_MODELS['seedream_v4'])


# Görsel denetimin bulduğu ve tek görsellik düzenlemeyle giderilebilen hatalar
# Düzeltilebilir hatalar. Etiket türü hatalar KONUMLA maskeli silinir (istem yok);
# pantolon için Seedream'e yalnızca olumlu tarif gider: görsel modeller olumsuzlanan
# nesneyi ("remove the trousers") çizmeye meyillidir.
AUTO_FIX_INSTRUCTIONS = {
    'added_label': None,
    'store_tag_visible': None,
    'detail_added': None,  # uydurulan fermuar/halka: kutusu çevredeki kumaşla doldurulur
    'pants_under_dress': (
        "Below the hem of the dress or skirt the model has natural bare legs and wears "
        "simple nude high-heeled pumps."
    ),
}


# Uydurma detay silmesinde kutu üst sınırı (görsel alanının oranı): büyük bölge silinmez, yeniden üretilir
ADDED_DETAIL_MAX_AREA = 0.06


def _added_detail_boxes(boxes):
    """Denetimin 'detail_added' kutularından silinebilecek kadar küçük olanlar."""
    out = []
    for b in boxes or []:
        if b.get('code') != 'detail_added':
            continue
        try:
            y1, x1, y2, x2 = (float(v) for v in b['box_2d'][:4])
        except (TypeError, ValueError, KeyError):
            continue
        if y2 > y1 and x2 > x1 and (y2 - y1) * (x2 - x1) <= ADDED_DETAIL_MAX_AREA * 1e6:
            out.append({'box_2d': [y1, x1, y2, x2], 'label': 'alarm_tag', 'confidence': 1.0})
    return out


def _auto_fix_defects(env, generated_b64, codes, boxes=None, garment_hint='', design_details='',
                      erase_added=True):
    """Denetimin bulduğu düzeltilebilir hataları gider.

    - Elbise altı pantolon: Seedream düzenlemesi (bütünsel değişiklik)
    - Görünür etiket: sonuçta kutular tespit edilip maskeli FLUX Fill ile silinir
      (maskesiz düzenleme bel bandındaki alarmı çoğu zaman tasarım sanıp korur);
      kutu bulunamazsa Seedream düzenlemesi yedek olarak denenir.
    - Üründe olmayan detay (silinmiş alarmın yerine çizilen fermuar gibi): denetimin kutusu
      maskeli silinir (erase_added=False: referans başka açıdan, silme yapılmaz).

    Returns:
        (bytes base64, float cost, list fixed_codes) veya (None, 0.0, [])
    """
    fixable = [c for c in codes if c in AUTO_FIX_INSTRUCTIONS]  # None = maskeli silme
    added_boxes = _added_detail_boxes(boxes) if erase_added and 'detail_added' in fixable else []
    if not added_boxes and 'detail_added' in fixable:
        fixable.remove('detail_added')
    icp = env['ir.config_parameter'].sudo()
    fal_key = icp.get_param('ugurlar_ai_studio.fal_api_key')
    if not fixable or not fal_key:
        return None, 0.0, []
    from ..services.fal_provider import FalProvider
    provider = FalProvider(fal_key)
    current, total_cost, fixed = generated_b64, 0.0, []

    def _seedream(instructions):
        prompt = ("Image 1 is a fashion e-commerce photo. " + ' '.join(instructions)
                  + " Keep everything else exactly the same: the model, face, pose, garment shape "
                    "and details, background and lighting.")
        return provider.single_image_edit(current, prompt)

    try:
        if 'pants_under_dress' in fixable:
            data, cost = _seedream([AUTO_FIX_INSTRUCTIONS['pants_under_dress']])
            if data:
                current, total_cost = base64.b64encode(_convert_to_jpeg(data)), total_cost + cost
                fixed.append('pants_under_dress')
        tag_codes = [c for c in ('store_tag_visible', 'added_label') if c in fixable]
        if tag_codes:
            data, cost = _erase_result_tags(
                provider, current, icp.get_param('ugurlar_ai_studio.gemini_api_key', ''),
                # Denetimin kutuları ORİJİNAL görsele aittir; pantolon düzeltmesi görseli
                # yeniden ürettiyse konumlar kaymıştır — yalnız yeni tespit kullanılır
                qc_boxes=[] if 'pants_under_dress' in fixed else [
                    b for b in (boxes or []) if b.get('code') in tag_codes],
                garment_hint=garment_hint, design_details=design_details)
            total_cost += cost
            if data:
                current = data
                fixed.extend(tag_codes)
        # Pantolon düzeltmesi görseli yeniden çizdiyse denetimin kutuları geçersizdir
        if added_boxes and 'pants_under_dress' not in fixed:
            data, cost = provider.erase_regions(current, added_boxes, pad_ratio=0.15)
            if data:
                current, total_cost = base64.b64encode(_convert_to_jpeg(data)), total_cost + cost
                fixed.append('detail_added')
                _logger.info('Üründe olmayan %d detay silindi', len(added_boxes))
    except Exception as e:
        _logger.warning('Otomatik düzeltme başarısız (%s): %s', fixable, e)
    if not fixed:
        return None, 0.0, []
    return current, total_cost, fixed


def _erase_result_tags(provider, image_b64, gemini_api_key, qc_boxes=None, passes=(0.35, 0.7),
                       garment_hint='', design_details=''):
    """AI sonucundaki alarm/etiket/pimi maskeli silip DOĞRULA; kalıntı varsa daha geniş maskeyle tekrarla.

    Denetimin (iki görselli, genel) kutuları ile etikete özel tespitin kutuları birleştirilir;
    her geçişten sonra etikete özel tespit yeniden çalışır. İstemli düzenleme kullanılmaz:
    model "remove the tag" denince etiketi yeniden çizmeye meyillidir.

    Returns:
        (base64 veya None, float cost)
    """
    from ..services.garment_analyzer import detect_image_tags
    current, total_cost, changed = image_b64, 0.0, False
    boxes = [dict(b, confidence=1.0, label='alarm_tag') for b in (qc_boxes or [])]
    boxes += detect_image_tags(None, current, gemini_api_key=gemini_api_key, generated=True,
                               garment_hint=garment_hint, design_details=design_details)
    for attempt, pad in enumerate(passes, start=1):
        if not boxes:
            break
        data, cost = provider.erase_regions(current, boxes, pad_ratio=pad)
        if not data:
            break
        current, total_cost, changed = base64.b64encode(_convert_to_jpeg(data)), total_cost + cost, True
        remaining = detect_image_tags(None, current, gemini_api_key=gemini_api_key, generated=True,
                                      garment_hint=garment_hint, design_details=design_details)
        if not remaining:
            _logger.info('Sonuçtaki etiket silindi ve doğrulandı (geçiş %d)', attempt)
            break
        _logger.warning('Sonuçta silme sonrası %d etiket kaldı (geçiş %d)', len(remaining), attempt)
        boxes = remaining
    return (current if changed else None), total_cost


# Ürün görseli temizleme (arka plan + etiket silme) mantığı değişince artırılır
GARMENT_CLEAN_VERSION = 'v8'  # v8: düğme adayları yakın planda doğrulanır (alarm iğnesi başı silinir)


_SET_RE = re.compile(r'(?<!\w)(?:takim\w*|set|setler|co-ord|coord)(?!\w)')


def _mark_coord_set(session, analysis):
    """Takım ürünü (üst + alt tek ürün): ürün adı / Reyon / Ürün Grubu ya da analiz 'takım' diyorsa işaretle."""
    if not isinstance(analysis, dict):
        return analysis
    if analysis.get('isSet') or session._is_coord_set():
        analysis['isSet'] = True
        analysis['clothingCategory'] = 'tops'  # elbiseye çevrilmesin
        _logger.info('Takım ürünü: üst ve alt parça birlikte giydirilecek (session=%s)', session.id)
    return analysis


def _needs_bare_legs(session, analysis=None):
    """Elbise / etek / şort: manken bacakları açık olmalı (tulum hariç)."""
    from ..services.garment_analyzer import _detect_sub_type
    analysis = analysis if isinstance(analysis, dict) else {}
    if analysis.get('isSet'):
        return False  # takımın alt parçası ürünün kendisi
    category = analysis.get('clothingCategory', '')
    if session._detect_garment_type() == 'one_piece' and category not in ('dress', 'one_piece'):
        category = 'dress'
    text = ' '.join(filter(None, [analysis.get('garmentType'), analysis.get('garmentTypeEn'),
                                  session.product_id.product_tmpl_id.name, category]))
    return _detect_sub_type(category, text) in ('dress', 'skirt', 'shorts')


def _garment_text(analysis):
    """Segmentasyon istemi: analizdeki İngilizce ürün türü (ör. "pleated trousers")."""
    analysis = analysis if isinstance(analysis, dict) else {}
    if analysis.get('isSet'):
        return 'clothing set, top and bottom'
    return str(analysis.get('garmentTypeEn') or '').strip() or 'garment'


def _mannequin_variant(session, analysis=None):
    """Manken sürümü: 'legs' (elbise/etek/şort), 'plain' (pantolon/tulum/takım) veya None (üst giyim)."""
    if _needs_bare_legs(session, analysis):
        return 'legs'
    from ..services.garment_analyzer import _detect_sub_type
    analysis = analysis if isinstance(analysis, dict) else {}
    if analysis.get('isSet'):
        return 'plain'
    text = ' '.join(filter(None, [analysis.get('garmentType'), analysis.get('garmentTypeEn'),
                                  session.product_id.product_tmpl_id.name]))
    category = analysis.get('clothingCategory', '')
    if not category and session._detect_garment_type() == 'bottoms':
        category = 'bottoms'
    return 'plain' if _detect_sub_type(category, text.lower()) in ('bottoms', 'jumpsuit') else None


def _get_mannequin_image(session, preset, photo_type, variant):
    """Görünüme uygun manken görseli: elbise/etekte pantolonsuz, pantolonda düz taytlı sürüm.

    Returns:
        (base64, float cost) — cost: bu çağrıda türetme yapıldıysa ücreti
    """
    view = photo_type if photo_type in ('front', 'back', 'side') else 'front'
    icp = session.env['ir.config_parameter'].sudo()
    if variant == 'legs':
        return preset.sudo()._get_bare_leg_mannequin(
            view, icp.get_param('ugurlar_ai_studio.gemini_api_key', ''),
            icp.get_param('ugurlar_ai_studio.fal_api_key', ''))
    if variant == 'plain':
        return preset.sudo()._get_plain_bottoms_mannequin(
            view, icp.get_param('ugurlar_ai_studio.fal_api_key', ''))
    return (getattr(preset, 'model_image_%s' % view) or preset.model_image_front), 0.0


def _run_quality_check(env, source_image, generated_b64, gemini_api_key='', analysis=None,
                       category='', gen=None, base_cost=0.0, reference_image=None,
                       photo_type='front', check_missing=True, view_construction=None,
                       removed_boxes=None):
    """Kalite skoru + (ayar açıksa) Gemini görsel denetimi + görünür etiketi otomatik silme.

    Returns:
        dict: generation'a yazılacak değerler. Etiket silindiyse 'generated_image' ve
        'cost' (= base_cost + silme maliyeti) da içerir.
    """
    from ..services.quality_checker import compute_quality_score
    icp = env['ir.config_parameter'].sudo()
    vals = {}
    visual_qc = None
    enabled = icp.get_param('ugurlar_ai_studio.visual_qc', 'True') == 'True'
    if enabled and gemini_api_key:
        from ..services.garment_analyzer import closure_state_hint, design_hint, visual_quality_check
        analysis = analysis if isinstance(analysis, dict) else {}
        # Analiz ön fotoğraftandır: ön detaylar yalnız ön görünümde "ürüne ait" sayılır.
        # Kapama durumu biliniyorsa denetime ayrıca verilir ve "hiç raporlama" listesinden çıkar:
        # açığa çıkan gizli fermuar / açılan ön "ürünün kendi detayı" sayılıp kaçıyordu
        closure_state = closure_state_hint(analysis) if photo_type == 'front' else ''
        details = design_hint(analysis, include_closure=not closure_state) if photo_type == 'front' else ''
        # Silme tespiti gerçek kapamayı (fermuar, düğme) silmesin: ona tam liste gider
        fix_details = design_hint(analysis) if photo_type == 'front' else ''
        hint = ' '.join(filter(None, [analysis.get('primaryColorEn') or analysis.get('primaryColor'),
                                      analysis.get('garmentTypeEn') or analysis.get('garmentType')]))
        hint = f"{hint} ({category})".strip()
        visual_qc = visual_quality_check(gemini_api_key, generated_b64, garment_hint=hint,
                                         reference_image=reference_image, design_details=details,
                                         check_missing=check_missing, view_construction=view_construction,
                                         removed_boxes=removed_boxes, original_image=source_image,
                                         closure_state=closure_state)

        auto_fix = icp.get_param('ugurlar_ai_studio.auto_tag_fix', 'True') == 'True'
        if visual_qc and auto_fix:
            fixed_b64, fix_cost, fixed_codes = _auto_fix_defects(
                env, generated_b64, visual_qc.get('codes', []), visual_qc.get('boxes'),
                garment_hint=(gen.session_id.product_id.display_name or '') if gen else '',
                design_details=fix_details, erase_added=check_missing)
            if fixed_b64:
                _logger.info('Otomatik düzeltildi %s (gen=%s)', fixed_codes, gen.id if gen else '?')
                # Silme sonrası yeniden denetle: etiket hâlâ duruyorsa reviewer görsün
                fixed_qc = visual_quality_check(gemini_api_key, fixed_b64, garment_hint=hint,
                                                reference_image=reference_image, design_details=details,
                                                check_missing=check_missing,
                                                view_construction=view_construction,
                                                removed_boxes=removed_boxes,
                                                original_image=source_image,
                                                closure_state=closure_state) or visual_qc
                # Pantolon düzeltmesi görseli referanssız yeniden çizer: ürünü bozduysa atılır.
                # Uydurma detay silmesi kusuru artırdıysa (gerçek detay silindi) atılır; aynı kalırsa
                # silinmiş hâli tutulur — denetim izli referansta parçayı "üründe var" sanabiliyor
                old_fid = visual_qc.get('fidelity') or 0
                new_fid = fixed_qc.get('fidelity') or 0
                if ('pants_under_dress' in fixed_codes and new_fid > old_fid) or \
                        ('detail_added' in fixed_codes and new_fid > old_fid):
                    _logger.warning('Otomatik düzeltme ürün detayını bozdu, orijinal korunuyor (gen=%s)',
                                    gen.id if gen else '?')
                    vals['cost'] = (base_cost or 0.0) + fix_cost
                else:
                    generated_b64 = fixed_b64
                    vals['generated_image'] = fixed_b64
                    vals['cost'] = (base_cost or 0.0) + fix_cost
                    visual_qc = fixed_qc
    # Renk karşılaştırması temizlenmiş ürün görseliyle (ham mağaza fotoğrafında duvar/zemin var)
    qc = compute_quality_score(reference_image or source_image, generated_b64, visual_qc=visual_qc)
    vals.update({'quality_score': qc['score'], 'quality_details': qc['details']})
    if 'generated_image' in vals:
        vals['quality_details'] = 'Otomatik düzeltildi | ' + vals['quality_details']
    # Çağıran _fidelity_retry ile yeniden üretim kararı verir; gen.write'a gitmeden çıkarılır
    vals['_fidelity'] = (visual_qc or {}).get('fidelity') or 0
    vals['_fix'] = (visual_qc or {}).get('fix') or ''
    return vals


def _with_fix(prompt, fix):
    """Yeniden üretim istemine denetimin olumlu düzeltme cümlesini ekle (ürün kısmının gerçek hâli)."""
    fix = ' '.join(str(fix or '').split()).strip()
    if not fix or not prompt:
        return prompt
    return f"{prompt} {fix if fix.endswith('.') else fix + '.'}"


FASHN_FALLBACK_MODEL = 'fashn/tryon/v1.6'
FIDELITY_FAILED_PREFIX = '⛔ Ürün değişmiş — dikkatle inceleyin | '


def _fidelity_retry(env, gen, gen_b64, qc_vals, first_cost, regenerate, check, fallback=None):
    """Sonuç ürünü değiştirdiyse yeniden üret, en doğru sonucu seç.

    Sıra: aynı modelle, denetimin düzeltme cümlesiyle bir deneme daha; o da ürünü değiştirdiyse
    (ayar açıksa) FASHN v1.6 — metin istemi kullanmaz, ürün piksellerini taşır. Hepsi kusurluysa en
    az kusurlu görsel tutulur ve fidelity_failed işaretlenir (incelemede ve Toplu Onay listesinde
    kırmızı rozet).

    regenerate(fix) / fallback(fix) -> (b64, seed, cost); cost yalnız o denemenin üretim maliyeti
    (hazırlık maliyeti first_cost'ta bir kez sayılır). check(b64, base_cost) -> _run_quality_check
    değerleri.

    Returns:
        (b64, vals) — vals gen.write'a hazır ('_fidelity' çıkarılmış)
    """
    bad = qc_vals.pop('_fidelity', 0) or 0
    fix = qc_vals.pop('_fix', '') or ''
    first_b64 = qc_vals.get('generated_image') or gen_b64
    icp = env['ir.config_parameter'].sudo()
    if not bad:
        qc_vals['fidelity_failed'] = False
        return first_b64, qc_vals
    if icp.get_param('ugurlar_ai_studio.fidelity_retry', 'True') != 'True':
        qc_vals['fidelity_failed'] = True
        qc_vals['quality_details'] = FIDELITY_FAILED_PREFIX + (qc_vals.get('quality_details') or '')
        return first_b64, qc_vals
    gen_id = gen.id if gen else '?'
    attempts = [('2. deneme', regenerate)]
    if fallback and icp.get_param('ugurlar_ai_studio.fashn_fallback', 'True') == 'True':
        attempts.append(('FASHN', fallback))
    total = qc_vals.get('cost', first_cost) or 0.0
    best_bad, best_b64, best_vals, best_label, best_seed = bad, first_b64, qc_vals, '', False
    scores = [str(bad)]
    for label, fn in attempts:
        if not best_bad:
            break
        _logger.info('Doğruluk: %d ürün kusuru, %s üretiliyor (gen=%s, düzeltme=%s)',
                     best_bad, label, gen_id, fix or '-')
        new_cost = 0.0
        try:
            new_b64, new_seed, new_cost = fn(fix)
            new_vals = check(new_b64, new_cost or 0.0) if new_b64 else None
        except Exception as e:
            _logger.warning('Doğruluk %s başarısız (gen=%s): %s', label, gen_id, e)
            total += new_cost or 0.0
            continue
        if new_vals is None:
            total += new_cost or 0.0
            continue
        new_bad = new_vals.pop('_fidelity', 0) or 0
        new_vals.pop('_fix', None)
        total += new_vals.get('cost', new_cost) or 0.0
        scores.append(str(new_bad))
        _logger.info('Doğruluk: %s %d kusur (gen=%s)', label, new_bad, gen_id)
        if new_bad < best_bad:
            best_bad, best_vals, best_label, best_seed = new_bad, new_vals, label, new_seed
            best_b64 = new_vals.get('generated_image') or new_b64
    vals = best_vals
    vals['cost'] = total
    if best_label:
        vals['generated_image'] = best_b64
        if best_seed:
            vals['seed'] = best_seed
        note = 'Doğruluk: %s seçildi (kusur %s)' % (best_label, '→'.join(scores))
    else:
        note = 'Doğruluk: yeniden denemeler daha iyi değildi (kusur %s)' % '→'.join(scores)
    vals['quality_details'] = note + ' | ' + (vals.get('quality_details') or '')
    vals['fidelity_failed'] = bool(best_bad)
    if best_bad:
        vals['quality_details'] = FIDELITY_FAILED_PREFIX + vals['quality_details']
    return best_b64, vals


def _make_regenerators(provider, tryon_kwargs, download, refresh, provider_type, photo_type):
    """Doğruluk yeniden üretimi için (regenerate, fallback) döndürür.

    regenerate: aynı model, denetimin düzeltme cümlesiyle. fallback: fal'de Seedream ön/arka
    görünümü için FASHN v1.6 (istem almaz, ürün görselini olduğu gibi giydirir); yoksa None.
    refresh(): kira yenileme + commit (uzun çağrı öncesi/sonrası).
    """
    def regenerate(fix=''):
        refresh()
        # Aynı seed aynı sonucu verir (v4); ikinci kayıt cron kurtarmasına karışmasın
        res = provider.virtual_tryon(**dict(
            tryon_kwargs, seed=False, on_enqueue=None, num_samples=1,
            prompt=_with_fix(tryon_kwargs.get('prompt'), fix)))
        refresh()
        b64, seed = download(res or {})
        return b64, seed, (res or {}).get('cost', 0.05)

    model = tryon_kwargs.get('model_name') or ''
    if provider_type != 'fal' or photo_type not in ('front', 'back') or 'fashn' in model:
        return regenerate, None

    def fallback(fix=''):
        refresh()
        res = provider.virtual_tryon(**dict(
            tryon_kwargs, model_name=FASHN_FALLBACK_MODEL, endpoint=None, seed=False, on_enqueue=None,
            num_samples=1, garment_photo_type='flat-lay', prompt='', negative_prompt=''))
        refresh()
        b64, _seed = download(res or {})
        return b64, False, (res or {}).get('cost', 0.075)

    return regenerate, fallback


def _get_extra_prompt_en(session):
    """Operatörün "İlave Talimat" metni İngilizce prompta girmeden önce çevrilir (oturum başına bir kez)."""
    text = (session.extra_prompt or '').strip()
    if not text:
        return ''
    if session.extra_prompt_en and session.extra_prompt_en_source == text:
        return session.extra_prompt_en
    try:
        translated = session.env['ai.studio.generation']._translate_prompt(text) or text
    except Exception as e:
        _logger.warning('İlave talimat çevirisi başarısız (session=%s): %s', session.id, e)
        translated = text
    session.write({'extra_prompt_en': translated, 'extra_prompt_en_source': text})
    return translated


def _get_candidate_count(env, photo_type, provider_type):
    """Her görünümde tek aday üretilir.

    Ön görünümde birden fazla aday üretilince arka/yan çekimler 1. aday referans alınarak
    üretiliyordu; sonradan başka aday seçilince görünümler uyuşmuyordu. Tutarlılık için
    ön görünüm de tek görsel üretir ve o görsel (ve seed'i) diğer açılara iletilir."""
    return 1


def _store_candidates(gen, image_urls):
    """İlk görsel dışındaki çıktıları aday olarak kaydet (indirme hatası üretimi bozmaz)."""
    import requests as req_lib
    vals = []
    for seq, url in enumerate(image_urls, start=1):
        try:
            data = req_lib.get(url, timeout=60).content
            vals.append({'generation_id': gen.id, 'sequence': seq,
                         'image': base64.b64encode(_convert_to_jpeg(data))})
        except Exception as e:
            _logger.warning('Aday görsel indirilemedi (gen=%s): %s', gen.id, e)
    if vals:
        gen.env['ai.studio.generation.candidate'].create(vals)


def _build_revision_instruction(gen):
    """Red sonrası revizyon talimatını İngilizce tek cümle olarak kur."""
    parts = []
    if gen.revision_prompt_en:
        parts.append(gen.revision_prompt_en.strip().rstrip('.'))
    elif gen.revision_prompt:
        parts.append(gen.revision_prompt.strip().rstrip('.'))
    reason = gen.reject_reason_id
    if reason:
        suggested = (reason.suggested_prompt_en or '').strip().rstrip('.')
        if suggested:
            parts.append(suggested)
    if not parts:
        return ''
    return "Reviewer correction, highest priority: %s." % '. '.join(parts)


def _safe_write_and_commit(cr, record, vals, max_retries=5):
    """Concurrent update (SerializationFailure) hatalarını önlemek için güvenli DB yazma."""
    import time, random
    for attempt in range(max_retries):
        try:
            record.write(vals)
            cr.commit()
            return True
        except Exception as e:
            cr.rollback()
            if _is_db_conflict(e) and attempt < max_retries - 1:
                time.sleep(random.uniform(0.2, 1.5))
                continue
            raise e


class AiStudioSession(models.Model):
    """Ana çekim oturumu modeli.

    Barkod tarama → fotoğraf çekimi → AI işleme → onay/red → ürüne kaydetme
    akışının merkezi yönetim noktası. mail.thread ile bildirim desteği sağlar.
    """
    _name = 'ai.studio.session'
    _description = 'AI Stüdyo Çekim Oturumu'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc'
    _rec_name = 'name'
    # NEDEN: chatter varsayılanı 'write' erişimi ister; onay kilidi kuralı operatörün 'saving'/'done' oturuma
    # yazmasını kapatınca kendi oturumuna not yazması da kapanırdı. Not ürüne yazılan içeriği etkilemez.
    _mail_post_access = 'read'

    name = fields.Char(
        string='Oturum No',
        readonly=True,
        default='/',
        copy=False,
    )
    product_id = fields.Many2one(
        'product.product',
        string='Ürün Varyantı',
        required=True,
        tracking=True,
        index=True,
    )
    product_barcode = fields.Char(
        related='product_id.barcode',
        string='Barkod',
        store=True,
        index=True,
    )
    product_image = fields.Image(
        related='product_id.image_128',
        string='Mevcut Ürün Resmi',
    )

    # --- Pivot & Filtreleme Bilgileri ---
    category_id = fields.Many2one(
        'product.category', string='Kategori',
        related='product_id.categ_id', store=True
    )
    # NEDEN: store=True, her stok hareketinde product.qty_available'ı yeniden hesaplatıp
    # oturum satırlarına yazdırıyordu (anlık değer zaten ürün üzerinde). Eski kolon DB'de
    # kalır (Odoo saklanmayan alanın kolonunu düşürmez; veri silen temizlik yok).
    qty_available = fields.Float(
        string='Stok Miktarı',
        related='product_id.qty_available',
    )
    color_value_ids = fields.Many2many(
        'product.attribute.value', 'ai_session_color_rel', string='Renk',
        compute='_compute_attributes', store=True
    )
    size_value_ids = fields.Many2many(
        'product.attribute.value', 'ai_session_size_rel', string='Beden',
        compute='_compute_attributes', store=True
    )
    brand_value_ids = fields.Many2many(
        'product.attribute.value', 'ai_session_brand_rel', string='Marka',
        compute='_compute_attributes', store=True
    )
    season_value_ids = fields.Many2many(
        'product.attribute.value', 'ai_session_season_rel', string='Sezon',
        compute='_compute_attributes', store=True
    )
    gender_value_ids = fields.Many2many(
        'product.attribute.value', 'ai_session_gender_rel', string='Cinsiyet',
        compute='_compute_attributes', store=True
    )

    # Attribute isim eşleştirme sabitleri (gelecekte ir.config_parameter'a taşınabilir)
    ATTR_COLOR_NAMES = {'renk', 'color', 'colour'}
    ATTR_SIZE_NAMES = {'beden', 'size', 'numara', 'boyut'}
    ATTR_BRAND_NAMES = {'marka', 'brand'}
    ATTR_SEASON_NAMES = {'sezon', 'sezon/yıl', 'season'}
    ATTR_GENDER_NAMES = {'cinsiyet', 'gender'}

    @api.depends('product_id', 'product_id.product_template_attribute_value_ids', 'product_id.product_tmpl_id.attribute_line_ids')
    def _compute_attributes(self):
        color_attrs = self.ATTR_COLOR_NAMES
        size_attrs = self.ATTR_SIZE_NAMES
        brand_attrs = self.ATTR_BRAND_NAMES
        season_attrs = self.ATTR_SEASON_NAMES
        gender_attrs = self.ATTR_GENDER_NAMES

        products = self.mapped('product_id')
        if products:
            products.mapped('product_template_attribute_value_ids.attribute_id')
            products.mapped('product_tmpl_id.attribute_line_ids.attribute_id')

        for session in self:
            c_ids, s_ids, b_ids, se_ids, g_ids = [], [], [], [], []
            if session.product_id:
                for ptav in session.product_id.product_template_attribute_value_ids:
                    attr_name = ptav.attribute_id.name.lower().strip()
                    if any(a in attr_name for a in color_attrs):
                        c_ids.append(ptav.product_attribute_value_id.id)
                    elif any(a in attr_name for a in size_attrs):
                        s_ids.append(ptav.product_attribute_value_id.id)
                
                for ptal in session.product_id.product_tmpl_id.attribute_line_ids:
                    attr_name = ptal.attribute_id.name.lower().strip()
                    if any(a in attr_name for a in brand_attrs):
                        b_ids.extend(ptal.value_ids.ids)
                    elif any(a in attr_name for a in season_attrs):
                        se_ids.extend(ptal.value_ids.ids)
                    elif any(a in attr_name for a in gender_attrs):
                        g_ids.extend(ptal.value_ids.ids)

            session.color_value_ids = [(6, 0, c_ids)]
            session.size_value_ids = [(6, 0, s_ids)]
            session.brand_value_ids = [(6, 0, b_ids)]
            session.season_value_ids = [(6, 0, se_ids)]
            session.gender_value_ids = [(6, 0, g_ids)]

    # --- Varyant Grubu ---
    apply_to_siblings = fields.Boolean(
        string='Tüm Bedenlere Uygula',
        help='Aynı kesimin tüm beden varyantlarına uygula',
        default=True,
    )
    sibling_product_ids = fields.Many2many(
        'product.product',
        string='Kardeş Varyantlar',
        compute='_compute_siblings',
    )

    # --- Durum ---
    state = fields.Selection([
        ('draft', 'Taslak'),
        ('photos_ready', 'Fotoğraflar Hazır'),
        ('preprocessing', 'Ön İşlem'),
        ('processing', 'AI İşliyor'),
        ('failed', 'Başarısız'),
        ('review', 'Onay Bekliyor'),
        ('saving', 'Ürüne Kaydediliyor'),
        ('done', 'Tamamlandı'),
        ('cancelled', 'İptal'),
    ], string='Durum', default='draft', tracking=True, index=True)

    # --- Zaman Damgaları (Bottleneck Analizi) ---
    date_photos_ready = fields.Datetime(string='Fotoğraflar Hazır', readonly=True)
    date_processing_start = fields.Datetime(string='AI Başlama', readonly=True)
    date_review_start = fields.Datetime(string='Onaya Düşme', readonly=True)
    date_done = fields.Datetime(string='Tamamlanma', readonly=True)

    # --- Otomatik Yeniden Deneme Sayacı (Cron Kuyruk Yönetimi) ---
    retry_count = fields.Integer('Otomatik Deneme Sayısı', default=0, readonly=True,
                                 help='Cron tarafından otomatik yeniden deneme sayısı. Maksimum 3 deneme sonrası durur.')

    # --- AI işleme kirası (worker'lar arası tekillik) ---
    ai_lease_until = fields.Datetime('AI Kira Bitişi', readonly=True, copy=False,
                                     help='Bir arka plan thread\'i oturumu işlerken dolu; süresi geçmişse thread ölmüştür.')
    ai_lease_owner = fields.Char('AI Kira Sahibi', readonly=True, copy=False)

    # --- İnceleme Kilidi (Concurrency Control) ---
    review_locked_by = fields.Many2one(
        'res.users',
        string='İnceleyen Kullanıcı',
        readonly=True,
        copy=False,
    )
    review_lock_time = fields.Datetime(
        string='Kilit Zamanı',
        readonly=True,
        copy=False,
    )
    review_lock_token = fields.Char(
        string='Kilit Jetonu',
        readonly=True,
        copy=False,
    )

    # --- AI Ayarları ---
    model_preset_id = fields.Many2one(
        'ai.studio.model.preset',
        string='Manken Preseti',
        tracking=True,
    )
    scene_id = fields.Many2one(
        'ai.studio.scene',
        string='Sahne / Konsept',
        domain="[('active', '=', True)]",
        tracking=True,
    )
    category = fields.Selection([
        ('tops', 'Üst Giyim'),
        ('bottoms', 'Alt Giyim'),
        ('one_piece', 'Tek Parça / Elbise'),
        ('shoes', 'Ayakkabı'),
        ('bags', 'Çanta'),
        ('accessories', 'Aksesuar'),
        ('auto', 'Otomatik'),
    ], string='Giyim Kategorisi', default='auto')
    quality_mode = fields.Selection([
        ('performance', 'Hızlı'),
        ('balanced', 'Dengeli'),
        ('quality', 'Kaliteli'),
    ], string='Kalite Modu', default='balanced')
    extra_prompt = fields.Text(string='İlave Talimat')
    extra_prompt_en = fields.Text(string='İlave Talimat (İngilizce)', readonly=True, copy=False,
                                  help='AI modeline gönderilen çeviri; ilave talimat değişince yenilenir.')
    extra_prompt_en_source = fields.Text(readonly=True, copy=False)
    prompt_template_id = fields.Many2one(
        'ai.studio.prompt.template',
        string='Prompt Şablonu',
    )

    # --- İlişkiler ---
    photo_ids = fields.One2many(
        'ai.studio.photo',
        'session_id',
        string='Fotoğraflar',
    )
    generation_ids = fields.One2many(
        'ai.studio.generation',
        'session_id',
        string='AI Üretimler',
    )

    # --- Takım (Set) Çekimi ---
    session_type = fields.Selection([
        ('single', 'Tekli Çekim'),
        ('set', 'Takım Çekimi'),
    ], string='Çekim Tipi', default='single', tracking=True)
    set_line_ids = fields.One2many(
        'ai.studio.set.line',
        'session_id',
        string='Takım Parçaları',
    )

    def action_review_generations(self):
        """Profesyonel inceleme popup'ini acar."""
        self.ensure_one()
        # Eğer oturum işleniyor durumunda kalmış ama tüm generation'lar bittiyse otomatik onaya geçir
        if self.state in ('preprocessing', 'processing') and self.generation_ids and all(g.state == 'done' for g in self.generation_ids):
            self.sudo().write({
                'state': 'review',
                'date_review_start': fields.Datetime.now(),
            })
        now = fields.Datetime.now()
        from datetime import timedelta
        if self.review_locked_by and self.review_lock_time:
            lock_age = now - self.review_lock_time
            if lock_age < timedelta(minutes=5) and self.review_locked_by.id != self.env.uid:
                lock_minutes = int(lock_age.total_seconds() // 60)
                lock_seconds = int(lock_age.total_seconds() % 60)
                raise UserError(_(
                    "⚠️ Bu oturum şu an %s tarafından inceleniyor (%ddk %dsn önce açtı).\n"
                    "Lütfen tamamlamasını bekleyin veya 5 dakika sonra tekrar deneyin."
                ) % (self.review_locked_by.name, lock_minutes, lock_seconds))

        return {
            'type': 'ir.actions.client',
            'tag': 'ugurlar_ai_studio.review_popup',
            'params': {
                'session_id': self.id,
            },
            'target': 'new',
        }

    # -------------------------------------------------------------------------
    # FAL.AI API ENTEGRASYONU
    # -------------------------------------------------------------------------

    # --- Kullanıcılar ---
    user_id = fields.Many2one(
        'res.users',
        string='Operatör',
        default=lambda self: self.env.user,
        tracking=True,
    )
    reviewer_id = fields.Many2one(
        'res.users',
        string='Onayıcı',
        copy=False,  # NEDEN: kopyayı kopyalayan (operatör) onaycı atamış olamaz; yazımı yalnız yetkili (A4 Y1)
    )

    # --- İstatistikler ---
    # Saklanmaz (okunurken hesaplanır): stored olduklarında her generation yazımı oturum
    # satırını da güncelliyor, kira/kilit güncellemeleriyle "concurrent update" çakışması
    # üretiyordu. Hiçbiri aramada/sıralamada kullanılmıyor.
    total_cost = fields.Monetary(
        string='Toplam Maliyet',
        compute='_compute_stats',
        currency_field='currency_id',
    )
    revision_count = fields.Integer(
        string='Toplam Revizyon',
        compute='_compute_stats',
    )
    approval_rate = fields.Float(
        string='Onay Oranı (%)',
        compute='_compute_stats',
        digits=(5, 1),
    )
    review_status_display = fields.Char(
        string='İnceleme Durumu',
        compute='_compute_review_status',
    )
    photo_count = fields.Integer(
        string='Fotoğraf Sayısı',
        compute='_compute_photo_count',
    )
    generation_count = fields.Integer(
        string='Üretim Sayısı',
        compute='_compute_photo_count',
    )
    # --- AI kullanımı (Gemini token'ları + fal) ---
    usage_ids = fields.One2many('ai.studio.usage', 'session_id', string='AI Kullanımı')
    gemini_cost = fields.Float(
        string='Gemini Maliyeti (USD)',
        compute='_compute_usage_stats',
        digits=(16, 4),
    )
    gemini_call_count = fields.Integer(
        string='Gemini Çağrı Sayısı',
        compute='_compute_usage_stats',
    )
    net_cost = fields.Float(
        string='Net Maliyet (USD)',
        compute='_compute_usage_stats',
        digits=(16, 4),
        help='Üretimlerin fal maliyeti + Gemini + silinen üretimlerin maliyeti',
    )
    currency_id = fields.Many2one(
        'res.currency',
        string='Para Birimi',
        default=lambda self: self.env.ref('base.USD', raise_if_not_found=False),
    )
    company_id = fields.Many2one(
        'res.company',
        string='Şirket',
        default=lambda self: self.env.company,
    )
    
    @api.model_create_multi
    def create(self, vals_list):
        """Otomatik sıra numarası ata."""
        for vals in vals_list:
            if vals.get('name', '/') == '/':
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'ai.studio.session'
                ) or '/'
        records = super().create(vals_list)
        # NEDEN: denetim OLUŞAN kayıtta yapılır; vals'a bakmak context['default_state'] /
        # default_reviewer_id ile atlatılıyordu (varsayılanlar super().create içinde uygulanır). A4 Y1.
        records._check_approval_gate_created()
        return records

    @api.depends('product_id')
    def _compute_siblings(self):
        """Aynı template'in diğer varyantlarını bul (Sadece aynı renk olanlar)."""
        for session in self:
            if session.product_id and session.product_id.product_tmpl_id:
                tmpl = session.product_id.product_tmpl_id
                all_siblings = tmpl.product_variant_ids - session.product_id
                
                # Varyantın renk özelliklerini bul
                color_ptavs = session.product_id.product_template_attribute_value_ids.filtered(
                    lambda v: v.attribute_id.display_type == 'color' or 'renk' in v.attribute_id.name.lower() or 'color' in v.attribute_id.name.lower()
                )
                
                valid_siblings = all_siblings
                if color_ptavs:
                    # Renk özelliği varsa, sadece aynı renge sahip varyantları filtrele
                    for color_ptav in color_ptavs:
                        valid_siblings = valid_siblings.filtered(
                            lambda s: color_ptav in s.product_template_attribute_value_ids
                        )
                
                session.sibling_product_ids = valid_siblings
            else:
                session.sibling_product_ids = False

    @api.depends('usage_ids.cost', 'generation_ids.cost')
    def _compute_usage_stats(self):
        for session in self:
            usage = session.sudo().usage_ids
            gemini = usage.filtered(lambda u: u.provider == 'gemini')
            session.gemini_cost = sum(gemini.mapped('cost'))
            session.gemini_call_count = len(gemini)
            session.net_cost = sum(session.generation_ids.mapped('cost')) + sum(usage.mapped('cost'))

    @api.depends('generation_ids.cost', 'generation_ids.is_approved',
                 'generation_ids.revision_number', 'generation_ids.state')
    def _compute_stats(self):
        """Maliyet, revizyon ve onay istatistiklerini hesapla."""
        for session in self:
            gens = session.generation_ids
            session.total_cost = sum(gens.mapped('cost'))
            session.revision_count = sum(
                max(0, g.revision_number - 1) for g in gens
            )
            done_gens = gens.filtered(lambda g: g.state == 'done')
            if done_gens:
                approved = done_gens.filtered('is_approved')
                session.approval_rate = (len(approved) / len(done_gens)) * 100
            else:
                session.approval_rate = 0.0

    def _compute_photo_count(self):
        for session in self:
            session.photo_count = len(session.photo_ids)
            session.generation_count = len(session.generation_ids)

    @api.depends('generation_ids.state', 'generation_ids.is_approved',
                 'generation_ids.revision_number', 'generation_ids.is_excluded',
                 'state')
    def _compute_review_status(self):
        """İnceleme durumu özeti hesapla.
        
        Örnekler:
          - "✅ 4/4 Onaylı"
          - "🔄 Revize Ediliyor (1)"
          - "⏳ Revizeden Döndü"
          - "3/5 Onaylı · 🔄 1 Revizede"
        """
        for session in self:
            if session.state not in ('review', 'processing', 'failed'):
                session.review_status_display = ''
                continue

            gens = session.generation_ids.filtered(lambda g: not g.is_excluded)
            if not gens:
                session.review_status_display = ''
                continue

            total = len(gens)
            approved = len(gens.filtered('is_approved'))
            in_revision = len(gens.filtered(
                lambda g: g.state in ('pending', 'processing') and g.revision_number > 1
            ))
            returned_from_revision = len(gens.filtered(
                lambda g: g.state == 'done' and g.revision_number > 1 and not g.is_approved
            ))
            failed = len(gens.filtered(lambda g: g.state == 'failed'))

            parts = []

            if approved == total and total > 0:
                parts.append(f'✅ {approved}/{total} Onaylı')
            elif approved > 0:
                parts.append(f'{approved}/{total} Onaylı')

            if in_revision > 0:
                parts.append(f'🔄 {in_revision} Revizede')
            elif returned_from_revision > 0:
                parts.append('⏳ Revizeden Döndü')

            if failed > 0:
                parts.append(f'❌ {failed} Başarısız')

            pending = len(gens.filtered(lambda g: g.state in ('pending', 'processing')))
            if pending > 0 and session.state in ('failed', 'processing'):
                parts.append(f'⏸️ {pending} Bekliyor')

            session.review_status_display = ' · '.join(parts) if parts else ''

    def _auto_select_preset(self):
        """Ürün kategorisine göre doğru manken preset'ini otomatik seç.
        
        Eğer tespit edilen ürün tipi (elbise/tops/bottoms) mevcut preset'in
        garment_type'ı ile uyuşmuyorsa, aynı cinsiyet ve vücut tipindeki
        uygun preset'i bulup otomatik değiştirir.
        
        Bu sayede elbise ürünleri jean'li manken yerine bare-legs manken
        kullanır ve bleed-through önlenir.
        """
        self.ensure_one()
        if not self.model_preset_id:
            return
        
        detected_cat = self._detect_garment_type()
        current_preset = self.model_preset_id
        
        # Kategori eşleştirme: detected_cat → preset garment_type
        cat_to_garment = {
            'tops': 'tops',
            'bottoms': 'bottoms',
            'one_piece': 'one_piece',
            'shoes': 'shoes',
            'bags': 'bags',
            'accessories': 'accessories',
        }
        needed_garment = cat_to_garment.get(detected_cat, 'tops')
        
        # Mevcut preset zaten doğru tipteyse değişiklik gereksiz
        if current_preset.garment_type == needed_garment:
            _logger.info(
                'Preset uyumlu: %s (garment_type=%s, algılanan=%s)',
                current_preset.name, current_preset.garment_type, detected_cat,
            )
            return
        
        # Uygun preset ara: aynı cinsiyet + aynı vücut tipi + doğru garment_type
        domain = [
            ('garment_type', '=', needed_garment),
            ('gender', '=', current_preset.gender),
            ('model_image_front', '!=', False),  # Manken görseli olmalı
        ]
        # Vücut tipi varsa filtrele
        if current_preset.body_type:
            domain.append(('body_type', '=', current_preset.body_type))
        
        matching_preset = self.env['ai.studio.model.preset'].search(domain, limit=1)
        
        if matching_preset:
            _logger.info(
                'Otomatik preset değişimi: %s (%s) → %s (%s) [ürün tipi: %s]',
                current_preset.name, current_preset.garment_type,
                matching_preset.name, matching_preset.garment_type,
                detected_cat,
            )
            self.write({'model_preset_id': matching_preset.id})
        else:
            _logger.warning(
                'Uygun preset bulunamadı: garment_type=%s, gender=%s. '
                'Mevcut preset (%s, garment_type=%s) kullanılıyor. '
                'Daha iyi sonuç için "%s" tipinde yeni bir preset oluşturun.',
                needed_garment, current_preset.gender,
                current_preset.name, current_preset.garment_type,
                needed_garment,
            )

    def _detect_garment_type(self):
        """Ürünün gerçek tipini otomatik algılar.
        
        Öncelik sırası:
        1. session.category elle seçildiyse (auto değilse) → onu kullan
        2. Ürün adı, kategori, Reyon/Ürün Grubu attribute'larından tespit et
        3. Hiçbiri bulunamazsa preset.garment_type veya 'tops' fallback
        """
        self.ensure_one()
        
        # 1. Elle seçilmiş kategori varsa onu kullan
        if self.category and self.category != 'auto':
            _logger.info('_detect_garment_type: Elle seçilmiş kategori=%s', self.category)
            return self.category
        
        # 2. Ürün bilgilerinden otomatik algıla
        product = self.product_id
        if not product:
            fallback = self.model_preset_id.garment_type if self.model_preset_id else 'tops'
            _logger.info('_detect_garment_type: Ürün yok, fallback=%s', fallback)
            return fallback
        
        from ..services.category_constants import classify_garment_text

        tmpl = product.product_tmpl_id
        # Önce SADECE ürün adı: kategori yolu ("Giyim > Üst Giyim" gibi) bir çantayı
        # ya da kemeri yanlışlıkla giysi yapmasın.
        name_text = ' '.join(filter(None, [tmpl.name or '', product.default_code or '']))

        context_texts = []
        categ = tmpl.categ_id
        while categ:
            if categ.name:
                context_texts.append(categ.name)
            categ = categ.parent_id
        try:
            for line in tmpl.attribute_line_ids:
                if (line.attribute_id.name or '') in ('Reyon', 'Ürün Grubu'):
                    context_texts.extend(v.name for v in line.value_ids if v.name)
        except Exception as e:
            _logger.warning('_detect_garment_type: Attribute okuma hatası: %s', e)

        for source, text in (('ad', name_text), ('kategori/attribute', ' '.join(context_texts))):
            cat, kw = classify_garment_text(text)
            if cat:
                _logger.info('_detect_garment_type: %s içinde "%s" → %s', source, kw, cat)
                return cat

        # 3. Fallback: preset veya tops
        fallback = self.model_preset_id.garment_type if self.model_preset_id else 'tops'
        _logger.info('_detect_garment_type: Eşleşme yok, fallback=%s', fallback)
        return fallback

    def _is_coord_set(self):
        """Ürün adı, Reyon / Ürün Grubu niteliği ya da kategorisi 'takım' diyor mu? (Takım Çekimi modu hariç)"""
        self.ensure_one()
        if self.session_type == 'set' or not self.product_id:
            return False
        from ..services.category_constants import normalize_tr
        tmpl = self.product_id.product_tmpl_id
        texts = [tmpl.name or '']
        try:
            for line in tmpl.attribute_line_ids:
                if (line.attribute_id.name or '') in ('Reyon', 'Ürün Grubu'):
                    texts.extend(v.name for v in line.value_ids if v.name)
        except Exception as attr_err:
            _logger.warning('Ürün nitelikleri okunamadı (session=%s): %s', self.id, attr_err)
        categ = tmpl.categ_id
        while categ:
            texts.append(categ.name or '')
            categ = categ.parent_id
        return bool(_SET_RE.search(normalize_tr(' '.join(texts))))

    def _get_product_context_text(self):
        """Ürün adı, kod, kategori ve nitelikleri metin olarak döndürür (Gemini & Prompt için)."""
        self.ensure_one()
        product = self.product_id
        if not product:
            return ""
        parts = []
        tmpl = product.product_tmpl_id
        if tmpl and tmpl.name:
            parts.append(f"Product Name: {tmpl.name}")
        if product.default_code:
            parts.append(f"Product Code / SKU: {product.default_code}")
        if tmpl and tmpl.categ_id:
            parts.append(f"Category: {tmpl.categ_id.complete_name or tmpl.categ_id.name}")
        if self.category and self.category != 'auto':
            cat_label = dict(self._fields['category'].selection).get(self.category, self.category)
            parts.append(f"Session Chosen Category: {cat_label}")
        # Nitelikler (Renk, Beden, Reyon, Ürün Grubu vb.)
        attr_parts = []
        if product.product_template_attribute_value_ids:
            for ptav in product.product_template_attribute_value_ids:
                attr_name = ptav.attribute_id.name
                val_name = ptav.name
                if attr_name and val_name:
                    attr_parts.append(f"{attr_name}: {val_name}")
        if tmpl:
            try:
                for line in tmpl.attribute_line_ids:
                    attr_name = line.attribute_id.name or ''
                    if attr_name in ('Reyon', 'Ürün Grubu', 'Kalıp', 'Kumaş', 'Materyal'):
                        for val in line.value_ids:
                            if val.name and f"{attr_name}: {val.name}" not in attr_parts:
                                attr_parts.append(f"{attr_name}: {val.name}")
            except Exception as attr_err:
                _logger.warning('Ürün nitelikleri okunamadı (session=%s): %s', self.id, attr_err)
        if attr_parts:
            parts.append(f"Attributes: {', '.join(attr_parts)}")
        return " | ".join(parts)

    def _crop_image_detail(self, image_base64, category='tops'):
        """Base64 formatındaki resmi Pillow ile kırpar ve base64 döner.
        
        Kategoriye göre kırpma koordinatları:
        - tops: Göğüs/yaka hizası (üst gövde merkez)
        - bottoms: Kalça/cep hizası (alt gövde merkez)
        - one_piece: Bel hizası (orta gövde)
        - shoes: Alt kısım (ayak bölgesi)
        - bags: Merkez (çantanın gövdesi)
        - accessories: Merkez (ürünün tamamı, geniş kırpma)
        """
        if not image_base64:
            return False
        try:
            import io
            import base64
            from PIL import Image
            
            # Base64 decode
            img_data = base64.b64decode(image_base64)
            img = Image.open(io.BytesIO(img_data))
            w, h = img.size
            
            # Kategoriye göre kırpma koordinatları
            crop_coords = {
                'tops': {
                    # Üst giyim: göğüs/yaka hizası
                    'left': 0.22, 'top': 0.20, 'right': 0.78, 'bottom': 0.55,
                },
                'bottoms': {
                    # Alt giyim: kalça/cep hizası
                    'left': 0.20, 'top': 0.42, 'right': 0.80, 'bottom': 0.75,
                },
                'one_piece': {
                    # Elbise/tek parça: bel hizası
                    'left': 0.18, 'top': 0.30, 'right': 0.82, 'bottom': 0.65,
                },
                'shoes': {
                    # Ayakkabı: alt kısım (ayak bölgesi)
                    'left': 0.10, 'top': 0.60, 'right': 0.90, 'bottom': 0.95,
                },
                'bags': {
                    # Çanta: merkez gövde
                    'left': 0.15, 'top': 0.15, 'right': 0.85, 'bottom': 0.85,
                },
                'accessories': {
                    # Aksesuar: geniş merkez
                    'left': 0.10, 'top': 0.10, 'right': 0.90, 'bottom': 0.90,
                },
            }
            
            coords = crop_coords.get(category, crop_coords['tops'])
            left = int(w * coords['left'])
            top = int(h * coords['top'])
            right = int(w * coords['right'])
            bottom = int(h * coords['bottom'])
                
            # Kırpma işlemi
            cropped_img = img.crop((left, top, right, bottom))
            
            # Tekrar base64'e dönüştür
            buffered = io.BytesIO()
            img_format = img.format or 'JPEG'
            cropped_img.save(buffered, format=img_format, quality=95)
            return base64.b64encode(buffered.getvalue())
        except Exception as e:
            _logger.error("Kırpma hatası: %s", e)
            return image_base64

    # --- Durum Geçişleri ---

    def action_photos_ready(self):
        """Fotoğraflar çekildi, AI'ya göndermeye hazır."""
        for session in self:
            has_front = any(p.photo_type == 'front' for p in session.photo_ids)
            has_back = any(p.photo_type == 'back' for p in session.photo_ids)
            
            if not has_front and not has_back:
                raise UserError(_('Lütfen ürünün Önünü ve Arkasını çekiniz!'))
            if not has_front:
                raise UserError(_('Lütfen ürünün Önünü çekiniz!'))
            if not has_back:
                raise UserError(_('Lütfen ürünün Arkasını çekiniz!'))

            # Detay sınır kontrolü: Ön detay max 1, Arka detay max 1
            front_details = session.photo_ids.filtered(lambda p: p.photo_type == 'detail' and (p.detail_placement or 'front') == 'front')
            if len(front_details) > 1:
                raise UserError(_('En fazla 1 adet Ön Yüz detay fotoğrafı eklenebilir.'))
            back_details = session.photo_ids.filtered(lambda p: p.photo_type == 'detail' and p.detail_placement == 'back')
            if len(back_details) > 1:
                raise UserError(_('En fazla 1 adet Arka Yüz detay fotoğrafı eklenebilir.'))
                
            session.state = 'photos_ready'
            session.date_photos_ready = fields.Datetime.now()

    def action_force_review(self):
        """Takılmış oturumları 'Onay Bekliyor' durumuna al.
        
        photos_ready'de kalmış ama AI üretimleri tamamlanmış oturumlar için.
        Genellikle ürüne kaydetme sırasında concurrent update hatası alan
        oturumları kurtarır.
        """
        self._check_reviewer()
        for session in self:
            if session.generation_ids:
                session.sudo().write({
                    'state': 'review',
                    'date_review_start': fields.Datetime.now(),
                })
                session.message_post(
                    body=_('⚠️ Oturum manuel olarak inceleme durumuna alındı.'),
                )
        if len(self) == 1:
            return self.action_review_generations()

    def action_retry_failed(self):
        """Başarısız ve bekleyen üretimleri kaldığı yerden devam ettir.
        
        - 'failed' ve 'pending' durumdaki generation'ları sıfırlayıp tekrar kuyruğa alır
        - Tamamlanmış ('done') olanlara dokunmaz
        - Thread başlatmaz — Cron otomatik olarak alır ve sırayla işler
          (Sunucu yeniden başlatmalarına dayanıklı kuyruk yönetimi)
        """
        self.ensure_one()
        self._check_reviewer()
        if self.state not in ('processing', 'failed', 'preprocessing', 'review'):
            raise UserError(_('Bu oturum şu an devam ettirilebilir durumda değil.'))
        if self.ai_lease_until and self.ai_lease_until > fields.Datetime.now():
            raise UserError(_('Oturum şu anda arka planda işleniyor; bitmesini bekleyin.'))

        # fal'e gönderilmiş ve sonucu beklenen işler yeniden gönderilmez (ikinci ücret);
        # onları cron request_id ile tamamlar
        retryable = self.generation_ids.filtered(
            lambda g: g.state in ('failed', 'pending')
            or (g.state == 'processing' and not g.fal_request_id)
        )
        if not retryable:
            # Tüm generation'lar zaten tamamlanmışsa oturumu hemen 'review' durumuna al
            if self.generation_ids and all(g.state == 'done' for g in self.generation_ids):
                self.sudo().write({
                    'state': 'review',
                    'date_review_start': fields.Datetime.now(),
                })
                return self.action_review_generations()
            raise UserError(_('Tekrar denenecek başarısız veya bekleyen üretim yok.'))

        self._check_monthly_budget()
        # API anahtarı kontrolü (erken hata yakalama)
        provider_type = self.env['ir.config_parameter'].sudo().get_param(
            'ugurlar_ai_studio.default_provider', 'fashn'
        )
        if provider_type == 'fashn':
            api_key = self.env['ir.config_parameter'].sudo().get_param(
                'ugurlar_ai_studio.fashn_api_key'
            )
        else:
            api_key = self.env['ir.config_parameter'].sudo().get_param(
                'ugurlar_ai_studio.fal_api_key'
            )
        if not api_key:
            raise UserError(_('API anahtarı bulunamadı. Lütfen Yapılandırma ayarlarını kontrol edin.'))

        # Failed olanları pending'e çevir, error mesajını temizle
        retryable.write(dict(CLEAR_FAL_REQUEST, state='pending', error_message=False))

        # Oturumu processing durumuna al
        self.write({
            'state': 'processing',
            'retry_count': 0,  # Manuel retry sayacı sıfırla
        })
        self.message_post(
            body=_('🔄 %d başarısız/bekleyen üretim sırayla işlenmek üzere arka plana alındı.') % len(retryable),
        )

        self._trigger_ai_queue()

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('AI İşleme Başlatıldı'),
                'message': _('%d üretim sırayla işleniyor. Tamamlandığında bildirim alacaksınız.') % len(retryable),
                'type': 'info',
                'sticky': False,
            },
        }

    # ═══════════════════════════════════════════════════════════════════
    # DRY HELPER METODLARI — _process_ai_thread_body ve
    # _retry_generation_thread_body tarafından ortak kullanılır
    # ═══════════════════════════════════════════════════════════════════

    def _detect_security_tags(self, session, image, design_details=''):
        """Mağaza alarmı / fiyat etiketi kutuları (Gemini, ayrı ve deterministik çağrı)."""
        try:
            # Thread içinde çağrılır: self.env'in cursor'ı kapalı olabilir,
            # session thread'in kendi env'ine bağlıdır
            icp = session.env['ir.config_parameter'].sudo()
            gemini_api_key = icp.get_param('ugurlar_ai_studio.gemini_api_key', '')
            if not gemini_api_key:
                return []
            from ..services.garment_analyzer import detect_image_tags
            tags = detect_image_tags(None, image, gemini_api_key=gemini_api_key,
                                     garment_hint=session.product_id.display_name or '',
                                     design_details=design_details)
            if tags:
                _logger.info('Görselde %d etiket/alarm tespit edildi, temizlenecek', len(tags))
            return tags
        except Exception as tag_err:
            _logger.warning('Etiket tespiti hatası: %s', tag_err)
            return []

    def _prepare_garment_for_tryon(self, source_image, provider, session, auto_bg=True, security_tags=None,
                                   photo=None, design_details='', garment_text=''):
        """Kaynak görseli AI try-on için hazırla: preprocess → bg_remove → hanger_remove → upload.

        photo verilirse temizlenmiş görsel fotoğrafta saklanır; aynı kaynak ve ayarla
        tekrar çağrıldığında (Tekrar Dene) ücretli adımlar atlanır.

        Returns:
            tuple: (garment_url, processed_b64, erase_cost) — CDN URL, işlenmiş base64, etiket silme maliyeti
        """
        from ..services.garment_preprocessor import (
            preprocess_garment_image,
            convert_birefnet_output_to_rgb,
            crop_to_content,
        )
        cache_key = None
        if photo and security_tags is None and source_image:
            raw = source_image if isinstance(source_image, bytes) else str(source_image).encode()
            # Sürüm eki: etiket tespit kuralları değişince eski temizlenmiş görseller kullanılmasın
            # (v2: metal halka/kopça artık alarm sanılıp silinmiyor)
            cache_key = '%s:bg%d:%s' % (hashlib.sha1(raw).hexdigest(), int(bool(auto_bg)), GARMENT_CLEAN_VERSION)
            if photo.garment_clean_key == cache_key and photo.garment_clean_image:
                garment_b64 = photo.garment_clean_image
                _logger.info('Temizlenmiş ürün görseli önbellekten kullanıldı (photo=%s, session=%s)',
                             photo.id, session.name)
                return provider.upload_image(garment_b64), garment_b64, 0.0

        # Modele giden ürün görseli kontrast/keskinlik işlemi görmez: CLAHE + unsharp, askıda kalan
        # örgünün orta katlanma çizgisini sertleştirip modele "ön orta dikiş" olarak çizdiriyordu
        preprocessed = preprocess_garment_image(source_image, target_long_edge=2048,
                                                apply_exposure_norm=False, apply_sharpening=False)
        processed_b64 = preprocessed['image_base64']
        garment_b64 = processed_b64

        bg_cost = 0.0
        if auto_bg and processed_b64:
            try:
                bg_removed_b64 = provider.remove_background(processed_b64)
                # BiRefNet ücreti (önceden hiç sayılmıyordu)
                from ..services.fal_provider import FalProvider
                bg_cost = FalProvider.get_estimated_cost(FalProvider.ENDPOINTS['bg_remove'])
                try:
                    bg_removed_data = base64.b64decode(bg_removed_b64)
                    rgb_data = convert_birefnet_output_to_rgb(bg_removed_data)
                    rgb_b64 = base64.b64encode(rgb_data)
                except Exception:
                    rgb_b64 = bg_removed_b64
                # Askı ve mandallar BiRefNet'te ön planda kalır; etiketlerle birlikte tespit edilip silinir
                # Oda gidince ürün kadrajı doldurur: alarm görece büyür, tespit ve silme isabetlenir
                garment_b64 = crop_to_content(rgb_b64)
            except Exception as e:
                _logger.warning('BG remove başarısız, orijinal kullanılacak: %s', e)
                garment_b64 = processed_b64

        # Askı / mandal: ürün metinle segmente edilip zemine bırakılır (kutuyla silinmez)
        mask_cost = 0.0
        if security_tags is None and auto_bg:
            security_tags = self._detect_security_tags(session, garment_b64, design_details)
            garment_b64, security_tags, mask_cost = self._mask_out_hanger(
                session, garment_b64, security_tags, garment_text, design_details)
        # Düğmeye benzeyen nesne: alarm iğnesinin başı mı gerçek düğme mi, yakın planda karar verilir
        fastener = None
        if security_tags:
            security_tags, fastener = self._verify_button_candidates(session, garment_b64, security_tags)

        # Mağaza alarmı / fiyat etiketi: ürüne kırpılmış görselde bul, maskeli AI ile sil
        erased = []
        garment_b64, erase_cost = self._remove_store_tags(session, garment_b64, security_tags,
                                                          design_details=design_details, erased=erased)
        erase_cost = (erase_cost or 0.0) + mask_cost + bg_cost

        if cache_key:
            try:
                with photo.env.cr.savepoint():
                    photo.write({'garment_clean_image': garment_b64, 'garment_clean_key': cache_key,
                                 'garment_tag_boxes': json.dumps(erased),
                                 'garment_fastener_check': json.dumps(fastener) if fastener else False})
            except Exception as ce:
                _logger.warning('Temizlenmiş ürün görseli saklanamadı (photo=%s): %s', photo.id, ce)

        garment_url = provider.upload_image(garment_b64)
        # garment_b64: try-on'a giden temizlenmiş ürün görseli (sonuç denetiminde referans)
        return garment_url, garment_b64, erase_cost

    def _verify_button_candidates(self, session, image_b64, tags):
        """button_like adaylarını yakın planda sınıfla (iğne başı → alarm_tag, düğme → korunur).

        Returns:
            (etiket listesi, dict info veya None)
        """
        if not any(isinstance(t, dict) and t.get('label') == 'button_like' for t in tags or []):
            return tags, None
        gemini_key = session.env['ir.config_parameter'].sudo().get_param('ugurlar_ai_studio.gemini_api_key', '')
        from ..services.garment_analyzer import verify_button_candidates
        try:
            tags, info = verify_button_candidates(gemini_key, image_b64, tags)
        except Exception as e:
            _logger.warning('Düğme adayı doğrulaması başarısız (session=%s): %s', session.id, e)
            return [t for t in tags if not (isinstance(t, dict) and t.get('label') == 'button_like')], None
        return tags, info

    def _apply_fastener_check(self, session, analysis, photo, garment_b64=None):
        """İğne başı silindiyse ve düğme doğrulanmadıysa analizdeki düğme sözlerini çıkar.

        Analiz ham fotoğraftan yapılır: iğne başını düğme sanıyor, prompt ve denetim de düğmeyi
        "ürünün parçası" diye taşıyordu.
        """
        if not isinstance(analysis, dict) or not photo:
            return
        try:
            info = json.loads(photo.garment_fastener_check or '{}')
        except (TypeError, ValueError):
            info = {}
        if not info.get('pins') or info.get('buttons'):
            return
        gemini_key = session.env['ir.config_parameter'].sudo().get_param('ugurlar_ai_studio.gemini_api_key', '')
        from ..services.garment_analyzer import drop_fastener_mentions
        try:
            changed = drop_fastener_mentions(gemini_key, analysis, image=garment_b64)
        except Exception as e:
            _logger.warning('Analizden düğme sözü çıkarılamadı (session=%s): %s', session.id, e)
            return
        if changed:
            _logger.info('Analizden düğme sözü çıkarıldı (session=%s, alanlar=%s): %s',
                         session.id, ', '.join(changed), design_hint(analysis) or '-')

    def _mask_out_hanger(self, session, image_b64, tags, garment_text='', design_details=''):
        """Askı/mandal tespit edildiyse ürünü EVF-SAM ile segmente et, askıyı zemine bırak.

        Returns:
            (base64 görsel, etiket listesi, float cost) — görsel değişirse etiketler yeni görselde
            yeniden taranır (kırpma koordinatları değiştirir)
        """
        from ..services.garment_preprocessor import HANGER_LABELS, apply_garment_mask, crop_to_content
        if not image_b64 or not any(isinstance(t, dict) and t.get('label') in HANGER_LABELS for t in tags or []):
            return image_b64, tags, 0.0
        fal_key = session.env['ir.config_parameter'].sudo().get_param('ugurlar_ai_studio.fal_api_key')
        if not fal_key:
            return image_b64, tags, 0.0
        from ..services.fal_provider import FalProvider
        try:
            mask, cost = FalProvider(fal_key).segment_garment(image_b64, garment_text or 'garment')
            masked = apply_garment_mask(image_b64, mask)
        except Exception as e:
            _logger.warning('Askı segmentasyonu başarısız, askı görselde kalıyor (session=%s): %s', session.id, e)
            return image_b64, tags, 0.0
        if not masked:
            return image_b64, tags, cost or 0.0
        masked = crop_to_content(masked)
        _logger.info('Askı ürün görselinden ayrıldı (session=%s, ürün=%s)', session.id, garment_text or '-')
        return masked, self._detect_security_tags(session, masked, design_details), cost or 0.0

    def _remove_store_tags(self, session, image_b64, tags=None, design_details='', erased=None):
        """Görseldeki mağaza etiketlerini sil (Bria/FLUX → iz denetimi → komşu kumaş dolgusu).

        Silme izi (bulanık şerit, leke) try-on modelinde fermuar / dikiş / parçaya dönüşüyordu:
        AI silmeden sonra bölge Gemini ile denetlenir; iz kalmışsa aynı satırlardaki komşu kumaş
        kopyalanır. erased: liste verilirse silinen kutular (box_2d) eklenir.

        Returns:
            (base64 görsel, float cost) — etiket yoksa / silinemezse girdinin kendisi
        """
        if not image_b64:
            return image_b64, 0.0
        if tags is None:
            tags = self._detect_security_tags(session, image_b64, design_details)
        if not tags:
            _logger.info('Ürün görselinde mağaza etiketi bulunamadı (session=%s)', session.id)
            return image_b64, 0.0
        from ..services.garment_preprocessor import (
            inpaint_tags_base64, tag_box_to_pixels, texture_fill_tags_base64,
        )

        def _valid_boxes(items):
            # Etiket türü ve güven korunur: silinmeyen (düşük güvenli / dev) kutu doku dolgusuna,
            # iz denetimine ve "silinen bölge" kaydına girmez
            out = []
            for t in items or []:
                if tag_box_to_pixels(t, 1000, 1000, pad_ratio=0, min_pad=0):
                    out.append({'box_2d': [round(float(v)) for v in t['box_2d'][:4]],
                                'label': t.get('label') or 'alarm_tag', 'confidence': t.get('confidence')})
            return out

        boxes = _valid_boxes(tags)
        if not boxes:
            _logger.info('Ürün görselinde silinecek güvenilir etiket kutusu yok (session=%s)', session.id)
            return image_b64, 0.0
        icp = session.env['ir.config_parameter'].sudo()
        fal_key = icp.get_param('ugurlar_ai_studio.fal_api_key')
        gemini_key = icp.get_param('ugurlar_ai_studio.gemini_api_key', '')
        result, total_cost = None, 0.0
        if fal_key:
            from ..services.fal_provider import FalProvider
            provider = FalProvider(fal_key)
            current = image_b64
            try:
                # Sil → yeniden tara; kalıntı varsa daha geniş maskeyle ikinci geçiş
                for attempt, pad in enumerate((0.25, 0.6), start=1):
                    data, cost = provider.erase_regions(current, tags, pad_ratio=pad)
                    if not data:
                        break
                    total_cost += cost
                    current = base64.b64encode(_convert_to_jpeg(data, quality=95))
                    if attempt == 2:
                        break  # son geçiş: yeniden tarama sonucu kullanılmaz (ücretli çağrı)
                    tags = self._detect_security_tags(session, current, design_details)
                    if not _valid_boxes(tags):
                        _logger.info('Mağaza etiketi silindi ve doğrulandı (geçiş %d)', attempt)
                        break
                    seen = {tuple(b['box_2d']) for b in boxes}
                    boxes += [b for b in _valid_boxes(tags) if tuple(b['box_2d']) not in seen]
                    _logger.warning('Silme sonrası %d etiket hâlâ görünüyor (geçiş %d)', len(tags), attempt)
                if current is not image_b64:
                    result = current
            except Exception as e:
                _logger.warning('AI etiket silme başarısız, komşu kumaş dolgusu kullanılacak: %s', e)
        if erased is not None:
            # Yalnız gerçekten silinen mağaza etiketleri (askı/mandal kutuları _valid_boxes'a girmez)
            erased.extend({'box_2d': b['box_2d'], 'label': b['label']} for b in boxes)
        if result is not None:
            from ..services.garment_analyzer import erased_area_clean
            if erased_area_clean(gemini_key, result, boxes) is not False:
                return result, total_cost
            _logger.warning('Silme izi kaldı (session=%s), komşu kumaş dolgusu deneniyor', session.id)
            try:
                filled = texture_fill_tags_base64(image_b64, boxes)
            except Exception as e:
                _logger.warning('Komşu kumaş dolgusu başarısız: %s', e)
                filled = image_b64
            if filled is not image_b64 and erased_area_clean(gemini_key, filled, boxes) is not False:
                _logger.info('Etiket bölgesi komşu kumaşla dolduruldu ve doğrulandı (session=%s)', session.id)
                return filled, total_cost
            _logger.warning('Komşu kumaş dolgusu da temiz değil; AI silme sonucu kullanılıyor (session=%s)',
                            session.id)
            return result, total_cost
        # AI silme yok: komşu kumaş dolgusu (Telea bulanık leke bırakır, son çare)
        try:
            filled = texture_fill_tags_base64(image_b64, boxes)
            if filled is not image_b64:
                return filled, 0.0
        except Exception as e:
            _logger.warning('Komşu kumaş dolgusu başarısız: %s', e)
        try:
            return inpaint_tags_base64(image_b64, tags), 0.0
        except Exception as e:
            _logger.warning('OpenCV etiket silme başarısız: %s', e)
            return image_b64, 0.0

    def _garment_view_info(self, session, photo, garment_b64, photo_type, own_photo=True):
        """Prompt ve denetim için: etiketin silindiği kutular + bu açının gerçek yapısı.

        Yapı (arka/yan, yalnız açının kendi fotoğrafı varsa) temizlenmiş görselden bir kez çıkarılır,
        temizleme anahtarıyla fotoğrafta saklanır.

        Returns:
            (list keep_boxes, dict veya None view_construction)
        """
        if not photo:
            return [], None
        try:
            boxes = json.loads(photo.garment_tag_boxes or '[]')
        except (TypeError, ValueError):
            boxes = []
        vc = None
        key = photo.garment_clean_key or ''
        if photo_type in ('back', 'side') and own_photo and garment_b64:
            try:
                cached = json.loads(photo.view_construction or '{}')
            except (TypeError, ValueError):
                cached = {}
            if key and cached.get('key') == key:
                vc = cached
            else:
                from ..services.garment_analyzer import analyze_view_construction
                gemini_key = session.env['ir.config_parameter'].sudo().get_param(
                    'ugurlar_ai_studio.gemini_api_key', '')
                try:
                    vc = analyze_view_construction(gemini_key, garment_b64, view=photo_type) if gemini_key else None
                except Exception as e:
                    _logger.warning('Görünüm yapısı analizi başarısız (photo=%s): %s', photo.id, e)
                    vc = None
                if vc and key:
                    try:
                        with photo.env.cr.savepoint():
                            photo.write({'view_construction': json.dumps(dict(vc, key=key))})
                    except Exception as we:
                        _logger.warning('Görünüm yapısı saklanamadı (photo=%s): %s', photo.id, we)
            if vc:
                _logger.info('Görünüm yapısı (%s, photo=%s): %s', photo_type, photo.id,
                             'düz' if vc.get('plain') else vc.get('partsEn') or '?')
        return (boxes if isinstance(boxes, list) else []), vc

    def _process_detail_generation(self, gen, session, provider, source_image, auto_bg, provider_type, preset):
        """Detay görseli: try-on sonucundan kırp; ayakkabı/çanta/aksesuarda ürün fotoğrafından.

        Returns:
            base64: Detay görseli
        """
        from ..services.garment_preprocessor import (
            preprocess_garment_image,
            convert_birefnet_output_to_rgb,
        )
        garment_cat = session._detect_garment_type()
        crop_from_product = garment_cat in ('shoes', 'bags', 'accessories')

        if not crop_from_product:
            # Üst/Alt/Tek Parça → manken try-on sonucundan kırp (ön işleme gerekmez)
            target_type = 'front'
            if gen.source_photo_id and gen.source_photo_id.photo_type == 'detail' \
                    and gen.source_photo_id.detail_placement == 'back':
                target_type = 'back'
            target_gen = session.generation_ids.filtered(
                lambda g: g.photo_type == target_type and g.state == 'done' and g.generated_image)
            if not target_gen and target_type == 'back':
                target_gen = session.generation_ids.filtered(
                    lambda g: g.photo_type == 'front' and g.state == 'done' and g.generated_image)
            if target_gen:
                return session._crop_image_detail(target_gen[0].generated_image, category=garment_cat)
            _logger.warning('Detay: try-on sonucu yok, ürün fotoğrafı kullanılacak (gen=%s)', gen.id)

        processed_b64 = preprocess_garment_image(
            source_image, target_long_edge=1600,
            security_tags=self._detect_security_tags(session, source_image) if crop_from_product else None,
        )['image_base64']
        clean_b64 = processed_b64
        if auto_bg and processed_b64:
            try:
                bg_removed_b64 = provider.remove_background(processed_b64)
                try:
                    clean_b64 = base64.b64encode(convert_birefnet_output_to_rgb(base64.b64decode(bg_removed_b64)))
                except Exception:
                    clean_b64 = bg_removed_b64
            except Exception as e:
                _logger.warning('Detay arka plan kaldırma başarısız: %s', e)
        if crop_from_product:
            return session._crop_image_detail(clean_b64, category=garment_cat)
        return clean_b64

    def _download_tryon_result(self, tryon_result):
        """Try-on API sonucunu indir ve JPEG'e dönüştür.

        Returns:
            tuple: (gen_b64, gen_seed) veya (None, None) başarısızsa
        """
        import requests as req_lib
        output_url = tryon_result.get('image_url', '')
        if not output_url:
            image_urls = tryon_result.get('image_urls', [])
            output_url = image_urls[0] if image_urls else ''

        if not output_url:
            return None, None

        if output_url.startswith('data:'):
            raw = output_url.split(';base64,', 1)[1]
            img_data = base64.b64decode(raw)
        else:
            img_data = req_lib.get(output_url, timeout=60).content

        img_data = _convert_to_jpeg(img_data)
        gen_b64 = base64.b64encode(img_data)
        gen_seed = tryon_result.get('seed') or False
        return gen_b64, gen_seed

    @api.model
    def _review_queue_domain(self):
        """Onay kuyruğu: incelemedeki ve revizesi (yeniden üretimi) sürmeyen oturumlar.

        Revizeye gönderilen görselin yeni sürümü bitene kadar oturum kuyrukta
        görünmez; bitince kendiliğinden geri gelir.
        """
        return [
            ('state', '=', 'review'),
            ('generation_ids', 'not any', [('state', 'in', ('pending', 'processing'))]),
        ]

    @api.model
    def get_review_queue(self, limit=50):
        """Toplu Onay ekranı: kuyruktaki oturumlar + revizesi süren oturum sayısı."""
        sessions = self.search_read(
            self._review_queue_domain(),
            ['name', 'product_id', 'generation_count', 'approval_rate', 'create_date'],
            limit=limit, order='create_date desc',
        )
        in_revision = self.search_count([
            ('state', '=', 'review'),
            ('generation_ids', 'any', [('state', 'in', ('pending', 'processing'))]),
        ])
        # Ürünü değişmiş görsel içeren oturumlar listede işaretlenir
        flagged = set(self.env['ai.studio.generation'].search([
            ('session_id', 'in', [s['id'] for s in sessions]),
            ('fidelity_failed', '=', True), ('is_excluded', '=', False),
        ]).mapped('session_id').ids)
        for s in sessions:
            s['fidelity_failed'] = s['id'] in flagged
        return {'sessions': sessions, 'in_revision_count': in_revision}

    def action_start_processing(self):
        """AI işlemeyi başlat."""
        self.ensure_one()
        if not (self.env.is_admin() or self.env.user.has_group('ugurlar_ai_studio.group_ai_studio_operator')):
            raise UserError(_('Bu işlem için AI Stüdyo operatör veya yönetici yetkisi gereklidir.'))
        # Çift tıklama / eşzamanlı başlatma: satırı kilitle, ikinci istek beklemeden düşsün
        try:
            self.env.cr.execute(
                "SELECT id FROM ai_studio_session WHERE id = %s FOR UPDATE NOWAIT", (self.id,))
        except Exception:
            raise UserError(_('Bu oturum şu anda başka bir istek tarafından başlatılıyor.'))
        self.invalidate_recordset(['state', 'ai_lease_until', 'date_processing_start'])
        # Tamamlanmış/kaydedilmiş session'ları koruma altına al
        if self.state in ('done', 'saving'):
            raise UserError(_('Bu oturum zaten tamamlanmış. Onaylı görsellerin silinmemesi için yeniden başlatılamaz.'))
        if self.state == 'review' and not self.env.context.get('force_restart'):
            raise UserError(_('Oturum incelemede: yeniden başlatmak ücretli üretimleri ve onayları siler. '
                              'Tek görseli yenilemek için "Reddet" veya "Tekrar Dene" kullanın.'))
        if self.state in ('preprocessing', 'processing'):
            now = fields.Datetime.now()
            lease_active = self.ai_lease_until and self.ai_lease_until > now
            recently_started = (self.date_processing_start
                                and self.date_processing_start > now - timedelta(minutes=LEASE_MINUTES))
            if lease_active or recently_started:
                raise UserError(_('Bu oturum şu anda aktif bir arka plan işlemi tarafından yürütülüyor.'))
        if not self.model_preset_id:
            raise UserError(_('Lütfen bir manken preseti seçin.'))
        if not self.photo_ids:
            raise UserError(_('Fotoğraf yok. Önce fotoğraf çekin.'))
        self._check_monthly_budget()

        # ═══ OTOMATİK PRESET SEÇİMİ ═══
        # Ürün kategorisine göre doğru manken preset'ini seç
        self._auto_select_preset()

        # Provider secimi ve API key kontrolu
        provider_type = self.env['ir.config_parameter'].sudo().get_param(
            'ugurlar_ai_studio.default_provider', 'fashn'
        )
        if provider_type == 'fashn':
            api_key = self.env['ir.config_parameter'].sudo().get_param(
                'ugurlar_ai_studio.fashn_api_key'
            )
            if not api_key:
                raise UserError(_(
                    'FASHN API anahtarı ayarlanmamış. '
                    'Ayarlar → AI Stüdyo menüsünden girin.'
                ))
        else:
            api_key = self.env['ir.config_parameter'].sudo().get_param(
                'ugurlar_ai_studio.fal_api_key'
            )
            if not api_key:
                raise UserError(_(
                    'fal.ai API anahtarı ayarlanmamış. '
                    'Ayarlar → AI Stüdyo menüsünden girin.'
                ))

        photos_by_type = self._photos_by_type()
        front_photo = photos_by_type.get('front')
        if not front_photo:
            raise UserError(_('AI işlemeyi başlatabilmek için en azından Ön Yüz fotoğrafı yüklenmiş olmalıdır.'))

        self.state = 'preprocessing'
        self.date_processing_start = fields.Datetime.now()

        # Eski generation kayıtlarını temizle
        self.generation_ids.unlink()

        # 4 görsel çıktısı için generation kayıtlarını oluştur
        # 1. Ön Görsel (Varsayılan olarak Ana Görsel)
        self.env['ai.studio.generation'].create({
            'session_id': self.id,
            'source_photo_id': front_photo.id,
            'photo_type': 'front',
            'original_image': front_photo.image_original,
            'state': 'pending',
            'provider': provider_type,
            'is_primary': True,
        })

        # 2. Arka Görsel (varsa)
        back_photo = photos_by_type.get('back')
        if back_photo:
            self.env['ai.studio.generation'].create({
                'session_id': self.id,
                'source_photo_id': back_photo.id,
                'photo_type': 'back',
                'original_image': back_photo.image_original,
                'state': 'pending',
                'provider': provider_type,
            })

        # 3. Yan Görsel (varsa side_photo, yoksa front_photo kullanılır)
        side_photo = photos_by_type.get('side')
        self.env['ai.studio.generation'].create({
            'session_id': self.id,
            'source_photo_id': (side_photo or front_photo).id,
            'photo_type': 'side',
            'original_image': (side_photo or front_photo).image_original,
            'state': 'pending',
            'provider': provider_type,
        })

        # 4. Detay Görsel (varsa detail_photo, yoksa front_photo kullanılır)
        detail_photo = photos_by_type.get('detail')
        self.env['ai.studio.generation'].create({
            'session_id': self.id,
            'source_photo_id': (detail_photo or front_photo).id,
            'photo_type': 'detail',
            'original_image': (detail_photo or front_photo).image_original,
            'state': 'pending',
            'provider': provider_type,
        })

        # Eşzamanlılık kuyruk cron'larında (concurrent_limit) uygulanır
        self._trigger_ai_queue()

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('AI İşleme Başladı'),
                'message': _('Fotoğraflar AI tarafından işleniyor. Tamamlandığında bildirim alacaksınız.'),
                'type': 'info',
                'sticky': False,
            },
        }

    def _photos_by_type(self):
        """Görünüm başına kaynak fotoğraf. Takım satırı fotoğrafları ana ürünü ezmez;
        iki detay fotoğrafında ön yerleşimli olan öncelikli."""
        photos_by_type = {}
        for p in self.photo_ids.filtered(lambda p: not p.set_line_id).sorted(
                lambda p: (p.photo_type != 'detail' or p.detail_placement != 'front', p.id)):
            photos_by_type.setdefault(p.photo_type, p)
        return photos_by_type

    def action_batch_reprocess(self):
        """Seçili oturumları toplu olarak sırayla yeniden AI işlemeye gönderir."""
        now = fields.Datetime.now()
        valid_sessions = self.filtered(
            lambda s: s.model_preset_id and any(p.photo_type == 'front' for p in s.photo_ids)
            # İşlenmekte olan (kirası canlı) ve tamamlanmış oturumlara dokunma
            and not (s.ai_lease_until and s.ai_lease_until > now)
            # İncelemedekiler de atlanır: yeniden işleme onayları/ücretli üretimleri siler
            and s.state not in ('done', 'saving', 'review')
        )
        if not valid_sessions:
            raise UserError(_('Seçili oturumlar arasında işlenebilir durumda olan (Ön yüz fotoğrafı ve Manken Preseti olan) oturum bulunamadı.'))
        self._check_monthly_budget()

        # API key kontrolü
        provider_type = self.env['ir.config_parameter'].sudo().get_param(
            'ugurlar_ai_studio.default_provider', 'fashn'
        )
        if provider_type == 'fashn':
            api_key = self.env['ir.config_parameter'].sudo().get_param('ugurlar_ai_studio.fashn_api_key')
            if not api_key:
                raise UserError(_('FASHN API anahtarı ayarlanmamış. Ayarlar → AI Stüdyo menüsünden girin.'))
        else:
            api_key = self.env['ir.config_parameter'].sudo().get_param('ugurlar_ai_studio.fal_api_key')
            if not api_key:
                raise UserError(_('fal.ai API anahtarı ayarlanmamış. Ayarlar → AI Stüdyo menüsünden girin.'))

        gen_vals_list = []
        for session in valid_sessions:
            session.write({
                'state': 'preprocessing',
                'date_processing_start': fields.Datetime.now(),
                'review_locked_by': False,
                'review_lock_time': False,
                'review_lock_token': False,
            })
            session.generation_ids.unlink()

            photos_by_type = session._photos_by_type()
            front_photo = photos_by_type.get('front')
            back_photo = photos_by_type.get('back')
            side_photo = photos_by_type.get('side')
            detail_photo = photos_by_type.get('detail')

            gen_vals_list.append({
                'session_id': session.id,
                'source_photo_id': front_photo.id,
                'photo_type': 'front',
                'state': 'pending',
                'provider': provider_type,
            })
            if back_photo:
                gen_vals_list.append({
                    'session_id': session.id,
                    'source_photo_id': back_photo.id,
                    'photo_type': 'back',
                    'state': 'pending',
                    'provider': provider_type,
                })
            gen_vals_list.append({
                'session_id': session.id,
                'source_photo_id': (side_photo or front_photo).id,
                'photo_type': 'side',
                'state': 'pending',
                'provider': provider_type,
            })
            gen_vals_list.append({
                'session_id': session.id,
                'source_photo_id': (detail_photo or front_photo).id,
                'photo_type': 'detail',
                'state': 'pending',
                'provider': provider_type,
            })

        if gen_vals_list:
            self.env['ai.studio.generation'].create(gen_vals_list)

        # Kuyruk cron'u istek commit edildikten sonra uyanır ve oturumları sırayla alır
        self._trigger_ai_queue()

        skipped_count = len(self) - len(valid_sessions)
        msg = _("%d adet oturum yeniden AI işlemeye gönderildi ve arka planda sırayla işleniyor.") % len(valid_sessions)
        if skipped_count > 0:
            msg += _(" (%d adet eksik fotoğraflı/presetsiz oturum atlandı.)") % skipped_count

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Toplu AI İşleme Başlatıldı'),
                'message': msg,
                'type': 'success',
                'sticky': False,
            },
        }

    @staticmethod
    def _create_provider(api_key, provider_type='fashn'):
        """Ayardaki secime gore provider olustur."""
        if provider_type == 'fashn':
            from ..services.fashn_provider import FashnProvider
            return FashnProvider(api_key)
        else:
            from ..services.fal_provider import FalProvider
            return FalProvider(api_key)

    # ═══ AI KUYRUĞU (cron slotları) ═══
    @api.model
    def _trigger_ai_queue(self):
        """Kuyruk cron'larını uyandır. ir.cron.trigger satırı çağıranın transaction'ıyla
        commit edilir; yani cron, istek kaydettiği 'pending' üretimleri görerek başlar."""
        for xmlid in AI_QUEUE_CRONS:
            cron = self.env.ref(xmlid, raise_if_not_found=False)
            if cron:
                cron.sudo()._trigger()

    def _queue_session_domain(self):
        return [
            ('state', 'in', ['preprocessing', 'processing']),
            ('generation_ids.state', '=', 'pending'),
            # Ön yüz fal kuyruğundaysa önce stuck cron sonucu alsın (referans + analiz)
            ('generation_ids', 'not any', [
                ('photo_type', '=', 'front'),
                ('state', '=', 'processing'),
                ('fal_request_id', '!=', False),
            ]),
        ] + self._lease_free_domain()

    def _queue_saving_domain(self):
        # NEDEN: complete_session görselleri ürüne HTTP isteğinde değil kuyrukta yazar (resize + çok
        # varyantlı product.image oluşturma onlarca sn sürebiliyordu)
        return [('state', '=', 'saving')] + self._lease_free_domain()

    def _queue_revision_domain(self):
        # Oturum işleme durumundaysa bekleyen üretimleri oturum işi alır; inceleme /
        # başarısız oturumdaki tek üretim (revizyon, Tekrar Dene) ayrı iştir
        return [
            ('session_id.state', 'in', ['review', 'failed']),
            ('state', '=', 'pending'),
        ] + self._lease_free_domain('session_id.')

    @api.model
    def _queue_has_work(self):
        return bool(
            self.search_count(self._queue_saving_domain(), limit=1)
            or self.search_count(self._queue_session_domain(), limit=1)
            or self.env['ai.studio.generation'].search_count(self._queue_revision_domain(), limit=1)
            or self.env['ai.studio.model.preset'].search_count(
                [('mannequin_generation_state', '=', 'queued')], limit=1)
        )

    def _queue_lock_and_lease(self, session_id, owner):
        """Oturum kirasını bu cursor'da al (commit ETMEZ). Diğer slot aynı satırı aldıysa False."""
        from psycopg2 import errors as pg_errors
        cr = self.env.cr
        try:
            with cr.savepoint():
                # NEDEN: REPEATABLE READ'de iki slot aynı adayı seçebilir; kilitli satır
                # atlanır, bizim snapshot'tan sonra kiralanmışsa SerializationFailure gelir.
                # Beklenen yarış: odoo.sql_db 'bad query' ERROR'u basmasın (izleme gürültüsü)
                cr.execute("SELECT id FROM ai_studio_session WHERE id = %s "
                           "FOR NO KEY UPDATE SKIP LOCKED", (session_id,), log_exceptions=False)
                if not cr.fetchone():
                    return False
                return _try_acquire_lease(cr, session_id, owner)
        except (pg_errors.SerializationFailure, pg_errors.LockNotAvailable):
            return False

    @api.model
    def _queue_claim_job(self, slot, owner):
        """Sıradaki tek işi seç ve kirasını al (commit ETMEZ; cron sarmalayıcısı commit eder).

        Returns: None | ('session', session_id, False) | ('revision', session_id, gen_id)
                 | ('save', session_id, False) | ('mannequin', preset_id, False)
        """
        global _queue_limit_warned
        limit = int(self.env['ir.config_parameter'].sudo().get_param(
            'ugurlar_ai_studio.concurrent_limit', '2') or 2)
        if limit > len(AI_QUEUE_CRONS) and not _queue_limit_warned:
            _queue_limit_warned = True
            # EKIP-BORC: concurrent_limit slot sayısını aşarsa fazlası kullanılmaz; gerekirse
            # data/cron.xml'e cron_ai_queue_N eklenip AI_QUEUE_CRONS'a yazılmalı
            _logger.warning('AI kuyruğu: concurrent_limit=%d ama yalnız %d kuyruk slotu var; '
                            'eşzamanlılık %d ile sınırlı.', limit, len(AI_QUEUE_CRONS), len(AI_QUEUE_CRONS))
        if slot > limit:
            return None
        # Ürüne kaydetme API anahtarı/bütçe gerektirmez ve onaycıyı bekletir: AI işlerinden önce
        for session in self.search(self._queue_saving_domain(), order='write_date asc, id asc', limit=20):
            if self._queue_lock_and_lease(session.id, owner):
                return ('save', session.id, False)
        if not self._get_active_api_key():
            if self._queue_has_work():
                _logger.warning('AI kuyruğu: bekleyen iş var ama API anahtarı bulunamadı!')
            return None
        # Bütçe yalnız oturum/revizyon üretimlerini durdurur (manken üretimi eskiden de denetlenmezdi)
        if self._budget_status()[0]:
            _logger.warning('AI kuyruğu: aylık AI bütçesi dolu, yeni üretim başlatılmıyor')
        else:
            # NEDEN: revizyon (red, Tekrar Dene) tek görünümlük kısa iştir ve onaycı ekranda
            # bekler; oturum işi 5-15 dk sürer. Oturumlar önce alınırsa toplu yeniden işleme
            # (20 oturum) revizyonları saatlerce bekletir. Revizyon akışı sürekli olamayacağı
            # için (insan tetikler) oturum işleri aç kalmaz.
            for gen in self.env['ai.studio.generation'].search(
                    self._queue_revision_domain(), order='write_date asc, id asc', limit=20):
                if self._queue_lock_and_lease(gen.session_id.id, owner):
                    return ('revision', gen.session_id.id, gen.id)
            for session in self.search(self._queue_session_domain(),
                                       order='date_processing_start asc, id asc', limit=20):
                if self._queue_lock_and_lease(session.id, owner):
                    return ('session', session.id, False)
        preset_id = self.env['ai.studio.model.preset']._queue_claim_mannequin()
        if preset_id:
            return ('mannequin', preset_id, False)
        return None

    @api.model
    def _cron_process_queue(self, slot=1):
        """Kuyruk slot cron'u: tek iş al, işle, iş kaldıysa kuyruğu yeniden tetikle.

        Uzun AI işi (dakikalar) HTTP worker'ında değil burada, cron worker'ında koşar.
        """
        round_cr = _cron_round_cursor()
        round_start = getattr(round_cr, '_ai_queue_round_start', None) or time.time()
        if round_cr is not None:
            # DIKKAT: tur bütçesi cron_cr nesnesinde tutulur; tur bitince cursor ile birlikte gider
            round_cr._ai_queue_round_start = round_start
        deadline = round_start + QUEUE_JOB_BUDGET_SECONDS
        if time.time() > deadline:
            # Bu turun bütçesi önceki kuyruk işinde bitti: iş yeni turda (yeni watchdog süresi) alınsın
            _logger.info('AI kuyruğu: cron turu süre bütçesi dolu (slot %s), iş sonraki tura bırakıldı', slot)
            if self._queue_has_work():
                self._trigger_ai_queue()
            return
        owner = _lease_owner()
        job = self._queue_claim_job(slot, owner)
        if not job:
            return
        # DIKKAT: kira commit edilmeden diğer slot aynı oturumu görür; ayrıca iş boyunca
        # bu cursor'da açık snapshot / satır kilidi kalmamalı (iş kendi cursor'larını açar)
        self.env.cr.commit()
        self._queue_run_job(job, owner, deadline=deadline)
        self.env.invalidate_all()
        if self._queue_has_work():
            self._trigger_ai_queue()

    @api.model
    def _queue_run_job(self, job, owner, deadline=None):
        kind, res_id, gen_id = job
        uid = self.env.uid
        if kind == 'mannequin':
            self.env['ai.studio.model.preset']._run_mannequin_job(res_id)
            return
        if kind == 'save':
            try:
                self._run_save_job(res_id)
                # NEDEN: commit burada (testte cr.commit yasak olduğundan _run_save_job içinde değil)
                self.env.cr.commit()
            except Exception as err:
                # DIKKAT: geri alınmazsa yarım yazım (ve bozulmuş transaction) cron cursor'ında kalır
                self.env.cr.rollback()
                if _is_db_conflict(err):
                    _logger.info('AI kuyruğu: ürüne kaydetme DB çakışması, yeniden denenecek (session=%s)', res_id)
                    self._trigger_ai_queue()
                else:
                    _logger.exception('AI kuyruğu: ürüne kaydetme beklenmeyen hata (session=%s)', res_id)
            finally:
                _release_session_lease(self.pool, res_id, owner)
            return
        api_key = self._get_active_api_key()
        # DIKKAT: okuma cron cursor'ında yeni transaction açar; iş (dakikalar) boyunca
        # idle-in-transaction snapshot kalmasın
        self.env.cr.commit()
        _logger.info('AI kuyruğu: iş başlıyor (%s, session=%s, gen=%s)', kind, res_id, gen_id)
        try:
            if kind == 'session':
                self._process_ai_thread_body(res_id, api_key, uid, lease_owner=owner, deadline=deadline)
            else:
                self._retry_generation_thread_body(res_id, gen_id, api_key, uid, lease_owner=owner)
        except Exception as err:
            _logger.exception('AI kuyruğu: beklenmeyen hata (%s, session=%s, gen=%s)', kind, res_id, gen_id)
            self._queue_mark_job_failed(kind, res_id, gen_id, err, uid)
        finally:
            clear_usage_recorder()
            _release_session_lease(self.pool, res_id, owner)

    @api.model
    def _run_save_job(self, session_id):
        """'saving' oturumun onaylı görsellerini ürüne yaz; başarıda 'done', hatada 'review' (mesajla).

        DIKKAT: hata durumunda oturum 'saving'de bırakılırsa kuyruk aynı işi sonsuza dek alır; 'review'a
        dönmek onaycının yeniden denemesine izin verir. Kaydetme idempotenttir (eski AI görselleri silinip
        yeniden yazılır), kira dolup başka slot alsa da çift kayıt oluşmaz.
        """
        session = self.browse(session_id)
        if session.state != 'saving':
            return
        # NEDEN: kuyruk sistem yetkisiyle yazar; 'saving' yalnız complete_session'ın onay denetiminden geçtiyse
        # güvenilir (write kilidine ek olarak, DB'ye doğrudan/sudo ile yazılmış durumlara karşı).
        # DIKKAT: reviewer_id onay izi olarak yalnız yetkililerin yazabildiği sürece güvenilirdir
        # (_check_saving_transition / _check_approval_gate_created); bu denetimler gevşerse kuyruk onaysız yazar.
        reviewer = session.reviewer_id.sudo()
        if not (reviewer and reviewer.has_group('ugurlar_ai_studio.group_ai_studio_reviewer')):
            reason = _('Ürüne kaydetme reddedildi: oturum onaycı tarafından tamamlanmamış. '
                       'Onaycı "Tamamla" ile yeniden başlatmalı.')
        elif session.generation_ids.filtered(lambda g: g.state in ('pending', 'processing')):
            reason = _('Ürüne kaydetme ertelendi: oturumda hâlâ işlenen üretim var. '
                       'Üretimler bitince onaycı "Tamamla" ile yeniden başlatmalı.')
        else:
            reason = None
        if reason:
            _logger.warning('Ürüne kaydetme reddedildi: oturum %s (reviewer=%s); incelemeye döndü.',
                            session_id, reviewer.id)
            session.write({'state': 'review'})
            session._notify_save_problem(reason)
            return
        try:
            with self.env.cr.savepoint():
                approved = session.generation_ids.filtered(
                    lambda g: g.is_approved and g.state == 'done' and not g.is_excluded)
                if not approved:
                    raise UserError(_('Onaylı görsel bulunamadı.'))
                session._save_to_product(approved)
                # Seçilmeyen alternatif adaylar artık gereksiz — depolamayı boşalt
                session.generation_ids.candidate_ids.unlink()
                session.write({'state': 'done', 'date_done': fields.Datetime.now()})
                session.message_post(body=_('%d onaylı görsel ürüne başarıyla kaydedildi.') % len(approved))
            _logger.info('Ürüne kaydetme: %s (%s) tamamlandı, %d görsel.', session.name, session.id, len(approved))
        except Exception as err:
            if _is_db_conflict(err):
                # NEDEN (D2): eşzamanlı yazım (ör. inceleme kilidi bırakma) oturum satırıyla çakıştı; aynı
                # snapshot'ta 'review' yazmak da çakışır. Oturum 'saving'de kalır, _queue_run_job geri alıp
                # kuyruğu yeniden tetikler (kaydetme idempotent).
                raise
            _logger.exception('Ürüne kaydetme hatası (session=%s)', session_id)
            session.write({'state': 'review'})
            # NEDEN (D1): beklenmeyen hatanın ham metni (SQL, dosya yolu) chatter'a yazılmaz; ayrıntı log'da.
            detail = (str(err)[:300] if isinstance(err, (UserError, ValidationError))
                      else _('beklenmeyen hata, kayıtlara bakın'))
            session._notify_save_problem(_('Ürüne kaydetme başarısız, tekrar "Tamamla" deneyin: %s') % detail)

    def _notify_save_problem(self, text):
        """Chatter notu + onaycıya (reviewer_id) bildirim; bildirim hatası akışı bozmaz.

        NEDEN: popup 'arka planda kaydediliyor' diyip sonraki oturuma geçtiği için hata toast'ı görünmez;
        onaycı haberdar olmazsa oturum sessizce 'review'da kalır (A4 Ö-2).
        """
        self.ensure_one()
        partner = self.reviewer_id.sudo().partner_id
        # NEDEN (D2): yedek not da savepoint içinde; ilk deneme transaction'ı bozduysa ikinci hata akışı kırmaz.
        for kwargs in ({'partner_ids': partner.ids, 'subtype_xmlid': 'mail.mt_comment'}, {}):
            try:
                with self.env.cr.savepoint():
                    self.message_post(body=text, **kwargs)
                return
            except Exception:
                _logger.warning('Kaydetme bildirimi gönderilemedi (session=%s)', self.id, exc_info=True)

    @api.model
    def _queue_mark_job_failed(self, kind, session_id, gen_id, err, uid):
        """Beklenmeyen hatada kalan işleri 'failed' yap (kuyruk aynı işi sonsuza dek almasın).

        fal'e gönderilmiş (request_id'li) üretimlere dokunulmaz: sonucu stuck cron alır.
        """
        try:
            with self.pool.cursor() as cr:
                env = api.Environment(cr, uid, {'lang': 'tr_TR'})
                if kind == 'revision':
                    gen = env['ai.studio.generation'].browse(gen_id)
                    if gen.exists() and gen.state in ('pending', 'processing') and not gen.fal_request_id:
                        gen.write(_failure_vals(err, _('Kritik Sistem Hatası: %s') % str(err)[:200]))
                    cr.commit()
                    return
                session = env['ai.studio.session'].sudo().browse(session_id)
                for g in session.generation_ids.filtered(
                        lambda x: x.state == 'pending' or (x.state == 'processing' and not x.fal_request_id)):
                    g.write(_failure_vals(
                        err, _('Kritik sistem hatası nedeniyle işlem tamamlanamadı: %s') % str(err)[:200]))
                if session.state in ('preprocessing', 'processing') and not session.generation_ids.filtered(
                        lambda x: x.state == 'processing'):
                    has_done = any(x.state == 'done' for x in session.generation_ids)
                    session.write({'state': 'review' if has_done else 'failed'})
                cr.commit()
                try:
                    session.message_post(body=_('Kritik Sistem Hatası: %s') % str(err)[:500])
                    cr.commit()
                except Exception as msg_err:
                    cr.rollback()
                    _logger.warning('AI kuyruğu: hata mesajı paylaşılamadı (session=%s): %s', session_id, msg_err)
        except Exception:
            _logger.exception('AI kuyruğu: hata durumu kaydedilemedi (session=%s, gen=%s)', session_id, gen_id)

    def _process_ai_thread_body(self, session_id, api_key, uid, lease_owner=None, deadline=None):
        """Oturumun bekleyen tüm görünümlerini işle (kuyruk işi; kendi cursor'larını açar).

        deadline (time.time()): aşılınca yeni görünüme başlanmaz, kalanlar 'pending' kalır.
        """
        _logger.info("AI Thread starting for session %s with uid %s", session_id, uid)
        with self.pool.cursor() as cr:
            env = api.Environment(cr, uid, {'lang': 'tr_TR'})
            session = env['ai.studio.session'].browse(session_id)
            # Semaphore beklenirken iş başka bir thread/cron tarafından bitirilmiş ya da
            # oturum iptal edilmiş olabilir: yeniden çalıştırmak mükerrer ücret demek
            if not session.exists() or session.state not in ('preprocessing', 'processing'):
                _logger.info('AI Thread: oturum %s artık işlenecek durumda değil (%s), atlandı.',
                             session_id, session.exists() and session.state)
                return
            _start_usage_recording(env, session)
            provider_type = env['ir.config_parameter'].sudo().get_param(
                'ugurlar_ai_studio.default_provider', 'fashn'
            )
            fal_api_key = env['ir.config_parameter'].sudo().get_param(
                'ugurlar_ai_studio.fal_api_key', ''
            )
            gemini_api_key = env['ir.config_parameter'].sudo().get_param(
                'ugurlar_ai_studio.gemini_api_key', ''
            )

        try:
            provider = self._create_provider(api_key, provider_type)
        except ImportError as ie:
            _logger.error('AI provider kurulu degil: %s', ie)
            with self.pool.cursor() as cr:
                env = api.Environment(cr, uid, {'lang': 'tr_TR'})
                session = env['ai.studio.session'].browse(session_id)
                session.write({'state': 'draft'})
                session.message_post(
                    body=_('Hata: AI provider Python paketi kurulu değil. (%s)') % str(ie)
                )
            return

        with self.pool.cursor() as cr:
            env = api.Environment(cr, uid, {'lang': 'tr_TR'})
            session = env['ai.studio.session'].browse(session_id)

            def _keep_lease():
                # Hazırlık adımları (analiz, etiket silme, görünüm yapısı) dakikalar sürer;
                # kira (LEASE_MINUTES) dolarsa stuck cron işi sahipsiz sanıp devralır
                if lease_owner:
                    _renew_session_lease(cr, session_id, lease_owner)
                    cr.commit()

            for attempt in range(3):
                try:
                    session.write({'state': 'processing'})
                    cr.commit()
                    break
                except Exception as start_err:
                    cr.rollback()
                    _logger.warning('Oturum processing durumu kilit çakışması (session_id=%s, deneme %d/3): %s', session_id, attempt + 1, start_err)
                    time.sleep(1.5)

            # ═══ OTOMATİK PRESET SEÇİMİ (Batch) ═══
            session._auto_select_preset()
            cr.commit()
            
            preset = session.model_preset_id
            generations = session.generation_ids.filtered(
                lambda g: g.state == 'pending'
            )
            # NEDEN: tipi bilinmeyen bekleyen üretim aşağıdaki sıralamaya (ordered_gens) girmez;
            # 'pending' kalırsa kuyruk oturumu her tur yeniden alır ve ücretli analizi tekrarlar
            unknown = generations.filtered(lambda g: g.photo_type not in VIEW_ORDER)
            if unknown:
                unknown.write({'state': 'failed', 'is_retryable': False, 'error_type': 'invalid_input',
                               'error_message': _('Fotoğraf tipi belirsiz; üretim yapılamadı.')})
                cr.commit()
                generations -= unknown
            # Ön yüz fal kuyruğunda sürüyorsa diğer görünümler onun sonucunu (referans +
            # analiz) bekler; cron ön yüzü kurtarınca oturum yeniden başlatılır
            if session.generation_ids.filtered(
                    lambda g: g.photo_type == 'front' and g.state == 'processing' and g.fal_request_id):
                _logger.info('AI Thread: ön yüz fal kuyruğunda (session=%s), diğer görünümler bekletiliyor.',
                             session_id)
                generations = generations.filtered(lambda g: g.photo_type == 'front')

            auto_bg = env['ir.config_parameter'].sudo().get_param(
                'ugurlar_ai_studio.auto_bg_remove', 'True'
            ) == 'True'


            # ═══ KIYAFET ANALIZINI CACHE'LE (tek API cagrisi) ═══
            cached_analysis = None
            try:
                # Retry durumunda front zaten done olabilir, tüm generation'lara bak
                front_gen = generations.filtered(lambda g: g.photo_type == 'front')
                if not front_gen:
                    # Front pending değilse (zaten done), tüm session generation'larından al
                    front_gen = session.generation_ids.filtered(
                        lambda g: g.photo_type == 'front' and g.state == 'done'
                    )
                front_img = front_gen and (front_gen[0].original_image or (front_gen[0].source_photo_id and front_gen[0].source_photo_id.image_original))
                # İşlenecek görünüm yoksa ücretli analiz/yükleme yapılmaz
                if generations and front_gen and front_img:
                    from ..services.garment_preprocessor import preprocess_garment_image
                    _pre = preprocess_garment_image(front_img, target_long_edge=1600)
                    _pre_url = provider.upload_image(_pre['image_base64'])

                    from ..services.garment_analyzer import analyze_garment
                    product_context = session._get_product_context_text()
                    cached_analysis = analyze_garment(
                        fal_api_key, _pre_url, gemini_api_key=gemini_api_key, product_context=product_context
                    )
                    _mark_coord_set(session, cached_analysis)
                    _logger.info(
                        'Kıyafet analizi tamamlandı: %s %s (yüzey: %s), hasGraphic=%s',
                        cached_analysis.get('garmentType', '?'),
                        cached_analysis.get('primaryColor', '?'),
                        cached_analysis.get('surfaceEn') or '-',
                        cached_analysis.get('hasGraphic', False),
                    )
                    _logger.info('Ürün detayları: %s', design_hint(cached_analysis) or '-')
            except Exception as ae:
                _logger.warning('Kıyafet analizi başarısız, varsayılan kullanılacak: %s', ae)
            _keep_lease()

            try:
                mannequin_variant = _mannequin_variant(session, cached_analysis)
            except Exception as nb_err:
                _logger.warning('Manken sürümü belirlenemedi: %s', nb_err)
                mannequin_variant = None
            if mannequin_variant == 'legs':
                _logger.info('Elbise/etek/şort: bacakları açık manken kullanılacak (session=%s)', session_id)
            elif mannequin_variant == 'plain':
                _logger.info('Alt giyim/tulum/takım: düz taytlı manken kullanılacak (session=%s)', session_id)

            # ═══ TÜM GENERATION'LARI İŞLE ═══
            # Cross-view tutarlılık verisi — front sonrası doldurulur
            outfit_consistency = None
            front_result_b64 = None  # Front try-on sonucu — back/side post-processing referansı
            # Ön görünümün API'nin döndürdüğü GERÇEK seed'i (Seedream v4 / FASHN döndürür,
            # Seedream v5 Pro döndürmez). Arka/yan çağrılarına ön görselle birlikte iletilir.
            front_seed = False

            # Varsa önceden tamamlanmış ön yüz üretiminden görsel ve seed'i yükle
            existing_front = session.generation_ids.filtered(
                lambda g: g.photo_type == 'front' and g.state == 'done' and g.generated_image
            )
            if existing_front:
                front_result_b64 = existing_front[0].generated_image
                front_seed = existing_front[0].seed or False
                _logger.info('Mevcut ön yüz üretimi referans olarak yüklendi (seed=%s, session=%s)',
                             front_seed or 'yok', session.name)

            # Fetch prompt locks OUTSIDE the loop (Item 10)
            all_locks = env['ai.studio.prompt.template'].search([
                ('scope', '=', 'global'),
                ('active', '=', True),
            ])
            global_prompt_locks = [l.prompt_text for l in all_locks]

            # Sıralama: front → back → side → detail
            ordered_gens = env['ai.studio.generation'].concat(*(
                generations.filtered(lambda g, t=t: g.photo_type == t) for t in VIEW_ORDER))

            front_failed = False
            started_views = 0
            for gen in ordered_gens:
                photo_type = gen.photo_type
                set_usage_context(generation_id=gen.id)
                # Her iterasyonda sıfırla: çakışma kurtarması önceki görünümün
                # sonucunu (ör. ön yüz görselini) bu generation'a yazmamalı.
                gen_b64 = tryon_result = None
                elapsed = 0.0
                # Ön yüz başarısızsa kalanlar yalnız 'failed' işaretlenir (anlık); bölünmemeli.
                # NEDEN: en az bir görünüm işlenir; yoksa hazırlık bütçeyi yediğinde iş hiç
                # ilerlemeden yeniden tetiklenir ve her turda analiz ücreti ödenir
                if deadline and started_views and not front_failed and time.time() > deadline:
                    _logger.info('Kuyruk süre bütçesi doldu (session_id=%s); kalan görünümler '
                                 'sonraki kuyruk çalıştırmasında işlenecek', session_id)
                    break
                # Oturum iptal/sıfırlandıysa yeni ücretli çağrı yapma
                if lease_owner:
                    _renew_session_lease(cr, session_id, lease_owner)
                cr.execute("SELECT state FROM ai_studio_session WHERE id = %s", (session_id,))
                row = cr.fetchone()
                if not row or row[0] not in ('preprocessing', 'processing'):
                    _logger.info('Oturum artık aktif değil (session_id=%s, state=%s), AI döngüsü durduruluyor',
                                 session_id, row and row[0])
                    break
                started_views += 1
                if front_failed:
                    gen.write({
                        'state': 'failed',
                        'error_message': _('Ön yüz üretimi başarısız olduğu için bu işlem iptal edildi.'),
                    })
                    cr.commit()
                    continue

                try:
                    gen.write(dict(CLEAR_FAL_REQUEST, state='processing'))
                    cr.commit()

                    start_time = time.time()
                    source_image = gen.original_image or (gen.source_photo_id and gen.source_photo_id.image_original)
                    if not source_image:
                        _logger.error('Orijinal fotoğraf bulunamadı (gen_id=%s, session=%s)', gen.id, session.name)
                        gen.write({
                            'state': 'failed',
                            'error_message': _('Orijinal fotoğraf verisi bulunamadı (görsel boş veya silinmiş).'),
                        })
                        if photo_type == 'front':
                            front_failed = True
                        cr.commit()
                        continue

                    # ═══ DETAY FOTOĞRAFI ═══ (AI'a gönderilmez: try-on sonucundan ya da
                    # ayakkabı/çanta/aksesuarda ürün fotoğrafından kırpılır)
                    if photo_type == 'detail':
                        detail_b64 = self._process_detail_generation(
                            gen, session, provider, source_image, auto_bg, provider_type, preset)
                        gen.write({
                            'generated_image': detail_b64,
                            'state': 'done',
                            'fal_endpoint': 'detail-crop',
                            'generation_time_seconds': time.time() - start_time,
                            'cost': 0.0,
                        })
                        try:
                            from ..services.quality_checker import compute_quality_score
                            qc = compute_quality_score(source_image, detail_b64)
                            gen.write({'quality_score': qc['score'], 'quality_details': qc['details']})
                        except Exception as qe:
                            _logger.debug('Kalite kontrol hatası: %s', qe)
                        cr.commit()
                        continue

                    # ═══ APILER İÇİN URL VE FORMAT AYARLARI ═══
                    # Elbise/etek/şort: pantolonlu manken ASLA gönderilmez (kök neden)
                    model_image_data, mannequin_cost = _get_mannequin_image(session, preset, photo_type, mannequin_variant)

                    if not model_image_data:
                        raise UserError(_('Preset manken resmi eksik.'))

                    # Upload images
                    model_url = provider.upload_image(model_image_data)
                    front_output_url = None
                    if not front_result_b64 and photo_type in ('back', 'side'):
                        # Fallback: DB'deki tamamlanmış front kaydından oku
                        f_done = session.generation_ids.filtered(
                            lambda g: g.photo_type == 'front' and g.state == 'done' and g.generated_image
                        )
                        if f_done:
                            front_result_b64 = f_done[0].generated_image
                            front_seed = f_done[0].seed or front_seed
                    if front_result_b64 and photo_type in ('back', 'side'):
                        try:
                            front_output_url = provider.upload_image(front_result_b64)
                        except Exception as up_e:
                            _logger.warning('Ön yüz referans görseli yüklenemedi: %s', up_e)
                            
                    # PERF: Boydan manken çekimlerinde (front, back, side) ekstra makro detay
                    # fotoğraflarını Seedream'e referans olarak göndermiyoruz.
                    # 1) Zaten 1. referans (kıyafet) ve 2. referans (manken) yeterlidir (back/side için 3. ref front'tur).
                    # 2) 4. bir görsel olarak makro kumaş gitmesi Seedream GPU ViT kodlama süresini 30-40s uzatmakta
                    #    ve modelin vücut oranlarını bozabilmektedir.
                    # 3) Detay görseli zaten üretilen manken sonucundan akıllı kırpılarak (crop) elde edilir.
                    detail_urls = []
                    # Arka plan kaldırma ve askı temizleme (DRY helper)
                    # Ön yüz dışındaki açılarda (back, side) ön yüz koordinatları geçersizdir.
                    # security_tags=None verildiğinde _prepare_garment_for_tryon o görseli kendisi tarar.
                    garment_url, processed_garment_b64, erase_cost = self._prepare_garment_for_tryon(
                        source_image, provider, session, auto_bg=auto_bg, security_tags=None,
                        photo=gen.source_photo_id,
                        design_details=design_hint(cached_analysis) if photo_type == 'front' else '',
                        garment_text=_garment_text(cached_analysis),
                    )
                    _keep_lease()
                    if photo_type == 'front':
                        self._apply_fastener_check(session, cached_analysis, gen.source_photo_id,
                                                   processed_garment_b64)
                        _keep_lease()
                    # Hazırlık maliyeti (etiket silme + ilk kez türetilen manken) bu üretime yazılır
                    prep_cost = (erase_cost or 0.0) + (mannequin_cost or 0.0)
                    # Yan görünüm kendi fotoğrafı yoksa ön fotoğraftan üretilir: o açının yapısı bilinmez
                    own_photo = (gen.source_photo_id.photo_type or photo_type) == photo_type
                    keep_boxes, view_construction = self._garment_view_info(
                        session, gen.source_photo_id, processed_garment_b64, photo_type, own_photo=own_photo)
                    _keep_lease()

                    # fal: ayardaki Seedream modeli (v4 Edit seed'li / v5 Pro Edit)
                    tryon_model = _get_tryon_model(env) if provider_type == 'fal' else 'tryon-v1.6'
                    tryon_resolution = '2K'  # Detay korumasi icin 2K zorunlu
                    if provider_type == 'fashn':
                        tryon_model = getattr(preset, f'fashn_model_{photo_type}', False) or getattr(preset, 'fashn_model_front', False) or 'tryon-v1.6'
                        tryon_resolution = '2K' if 'max' in tryon_model else '1K'

                    detected_cat = session._detect_garment_type()
                    from ..services.garment_analyzer import map_to_fashn_category
                    analysis_cat = map_to_fashn_category(cached_analysis or {})
                    
                    # Gemini analizi dress/one_piece diyorsa ama keyword fallback tops dönüyorsa → Gemini'ye güven
                    gemini_clothing_cat = (cached_analysis or {}).get('clothingCategory', '')
                    if detected_cat == 'tops' and gemini_clothing_cat in ('dress', 'one_piece', 'one-piece', 'full-body') \
                            and not (cached_analysis or {}).get('isSet'):
                        _logger.info(
                            'Batch category override: _detect=%s AMMA Gemini=%s → one_piece',
                            detected_cat, gemini_clothing_cat,
                        )
                        detected_cat = 'one_piece'
                    
                    if detected_cat in ('tops', 'bottoms', 'one_piece', 'bags', 'shoes'):
                        category_to_send = detected_cat
                        if isinstance(cached_analysis, dict):
                            cached_analysis['clothingCategory'] = (
                                'tops' if detected_cat == 'tops' else (
                                    'bottoms' if detected_cat == 'bottoms' else (
                                        'dress' if detected_cat == 'one_piece' else detected_cat
                                    )
                                )
                            )
                    elif analysis_cat in ('bottoms', 'one-piece', 'full-body'):
                        category_to_send = 'bottoms' if analysis_cat == 'bottoms' else 'one_piece'
                    else:
                        category_to_send = detected_cat if detected_cat != 'auto' else analysis_cat

                    # VIEW-SPESİFİK PROMPT OLUŞTURMA
                    prompt_text = ""
                    negative_prompt_text = ""
                    try:
                        prompt_locks = global_prompt_locks

                        analysis_data = cached_analysis or {}
                        preset_data = {
                            'gender': preset.gender or 'female',
                            'body_type': preset.body_type or 'standard',
                            'target_audience': preset.target_audience or '',
                        }

                        from ..services.garment_analyzer import build_generation_prompt
                        
                        # Sahne ayrı parametre: beyaz stüdyo tarifinin YERİNE geçer
                        scene_prompt = (session.scene_id.prompt_additions or '') if session.scene_id else ''
                        combined_extra_prompt = ' '.join(filter(None, [
                            _build_revision_instruction(gen),
                            _get_extra_prompt_en(session),
                        ]))

                        built_prompt = build_generation_prompt(
                            analysis_data, preset_data, prompt_locks,
                            combined_extra_prompt.strip(),
                            photo_type=photo_type,
                            outfit_consistency=outfit_consistency,
                            provider_type=provider_type,
                            scene_prompt=scene_prompt,
                            has_front_ref=bool(front_output_url),
                            view_construction=view_construction,
                            keep_boxes=keep_boxes,
                            bbox_grounding=provider_type == 'fal' and 'v5' in (tryon_model or ''),
                        )
                        prompt_text = built_prompt.get('positive', '')
                        negative_prompt_text = built_prompt.get('negative', '')
                        
                        if session.scene_id and session.scene_id.negative_prompt_additions:
                            if negative_prompt_text:
                                negative_prompt_text += f", {session.scene_id.negative_prompt_additions}"
                            else:
                                negative_prompt_text = session.scene_id.negative_prompt_additions
                    except Exception as pe:
                        _logger.warning('Prompt oluşturma başarısız: %s', pe)

                    # Hazırlık maliyeti try-on'dan önce yazılır: try-on başarısız olsa da harcanan
                    # silme / segment / manken ücreti kaybolmasın (temiz görsel önbellekte, tekrar
                    # denemede yeniden ödenmez)
                    spent_before = gen.cost or 0.0
                    if prep_cost:
                        gen.write({'cost': spent_before + prep_cost})
                    # Çeviri / manken önbelleği yazımları try-on boyunca satır kilidi tutmasın
                    cr.commit()

                    # Ön görünüm seed'siz gider (model seçer, sonuçta döner); arka/yan çekimler
                    # ön görünümün seed'ini ve görselini (Image 3) birlikte alır.
                    call_seed = front_seed if photo_type in ('back', 'side') else False
                    if photo_type in ('back', 'side'):
                        _logger.info('%s çekimi: ön görsel %s, seed %s iletiliyor (model=%s, session=%s)',
                                     photo_type, 'Image 3 olarak' if front_output_url else 'YOK',
                                     call_seed or 'yok', tryon_model, session.name)

                    # TRY-ON API ÇAĞRISI
                    tryon_kwargs = dict(
                        model_image_url=model_url,
                        garment_image_url=garment_url,
                        category=category_to_send,
                        mode=session.quality_mode or 'quality',
                        model_name=tryon_model,
                        num_samples=_get_candidate_count(env, photo_type, provider_type),
                        garment_photo_type='flat-lay' if 'fashn/' in tryon_model else 'auto',
                        output_format='jpeg',
                        prompt=prompt_text,
                        negative_prompt=negative_prompt_text,
                        front_output_url=front_output_url,
                        detail_urls=detail_urls,
                        resolution=tryon_resolution,
                        image_size=_get_seedream_image_size(env),
                        photo_type=photo_type,
                        seed=call_seed,
                        garment_type=(analysis_data or {}).get('garmentType', '') if isinstance(analysis_data, dict) else '',
                        on_enqueue=_make_enqueue_recorder(self.pool, gen.id),
                    )
                    tryon_result = provider.virtual_tryon(**tryon_kwargs)
                    # on_enqueue ayrı transaction'da bu satırı güncelledi; REPEATABLE READ
                    # snapshot'ını yenilemezsek sonraki write serileştirme hatası verir
                    cr.commit()

                    elapsed = time.time() - start_time

                    # SONUCU İNDİR (DRY helper)
                    gen_b64, gen_seed = self._download_tryon_result(tryon_result)

                    if gen_b64:
                        # Yalnızca API'nin döndürdüğü gerçek seed kaydedilir (v5 Pro döndürmez)
                        saved_seed = gen_seed or call_seed or False
                        gen.write({
                            'generated_image': gen_b64,
                            'state': 'done',
                            'fal_endpoint': '%s/%s' % (provider_type, tryon_model),
                            'generation_time_seconds': elapsed,
                            'cost': spent_before + tryon_result.get('cost', 0.05) + prep_cost,
                            'seed': saved_seed,
                        })
                        extra_urls = (tryon_result.get('image_urls') or [])[1:]
                        if extra_urls:
                            _store_candidates(gen, extra_urls)

                        # ═══ FRONT SONRASI: REFERANS CACHE + OUTFIT ANALİZİ ═══
                        if photo_type == 'front':
                            front_seed = saved_seed
                            front_result_b64 = gen_b64

                            # Elbise/etek/şortta sonucu kullanılmıyor: ücretli çağrıyı atla
                            if outfit_consistency is None and mannequin_variant != 'legs':
                                try:
                                    from ..services.garment_analyzer import analyze_outfit_consistency
                                    outfit_consistency = analyze_outfit_consistency(
                                        gen_b64,
                                        api_key=fal_api_key,
                                        gemini_api_key=gemini_api_key,
                                        category=category_to_send,
                                    )
                                except Exception as oe:
                                    _logger.warning('Outfit tutarlılık analizi başarısız: %s', oe)


                        # KALİTE KONTROL (+ Gemini görsel denetim + etiket silme)
                        # Denetim + otomatik düzeltme dakikalar sürebilir: kira dolmasın
                        if lease_owner:
                            _renew_session_lease(cr, session_id, lease_owner)
                            cr.commit()
                        try:
                            # Yan görünüm kendi fotoğrafı yoksa (own_photo) kaybolan detay aranmaz
                            def _qc(img_b64, base_cost):
                                return _run_quality_check(
                                    env, source_image, img_b64, gemini_api_key,
                                    analysis=cached_analysis, category=category_to_send, gen=gen,
                                    base_cost=base_cost, reference_image=processed_garment_b64,
                                    photo_type=photo_type, check_missing=own_photo,
                                    view_construction=view_construction, removed_boxes=keep_boxes,
                                )

                            def _refresh():
                                if lease_owner:
                                    _renew_session_lease(cr, session_id, lease_owner)
                                cr.commit()

                            _regenerate, _fallback = _make_regenerators(
                                provider, tryon_kwargs, self._download_tryon_result, _refresh,
                                provider_type, photo_type)
                            first_cost = spent_before + tryon_result.get('cost', 0.0) + prep_cost
                            qc_vals = _qc(gen_b64, first_cost)
                            final_b64, qc_vals = _fidelity_retry(
                                env, gen, gen_b64, qc_vals, first_cost, _regenerate, _qc,
                                fallback=_fallback)
                            gen.write(qc_vals)
                            if final_b64 is not gen_b64:
                                gen_b64 = final_b64
                                if photo_type == 'front':
                                    # Arka/yan görünümler temizlenmiş / seçilmiş ön görseli referans alsın
                                    front_result_b64 = gen_b64
                                    front_seed = qc_vals.get('seed') or front_seed
                        except Exception as qe:
                            _logger.warning('Kalite kontrol hatası (gen=%s): %s', gen.id, qe)

                    else:
                        gen.write({
                            'state': 'failed',
                            'error_message': 'API sonuç döndürmedi.',
                        })
                        if photo_type == 'front':
                            front_failed = True

                    cr.commit()

                except Exception as e:
                    cr.rollback()
                    if _is_client_timeout(e) and _get_request_id(cr, gen.id):
                        # İş fal kuyruğunda sürüyor: yeniden göndermek ikinci kez ücret demek.
                        # 'processing' kalır, cron sonucu request_id ile alır; kalan
                        # görünümler (ön yüz referansına bağlı) sonra devam eder.
                        _logger.warning('fal istemci zaman aşımı (gen=%s): sonuç cron ile kurtarılacak', gen.id)
                        break
                    if _is_db_conflict(e):
                        _logger.warning('AI Üretim sırasında veritabanı kilit çakışması (gen=%s), 1.5s beklenip tekrar denenecek: %s', gen.id, e)
                        time.sleep(1.5)
                        try:
                            with self.pool.cursor() as retry_cr:
                                retry_env = api.Environment(retry_cr, uid, {})
                                r_gen = retry_env['ai.studio.generation'].browse(gen.id)
                                if gen_b64:
                                    r_gen.write({
                                        'generated_image': gen_b64,
                                        'state': 'done',
                                        'fal_endpoint': '%s/%s' % (provider_type, tryon_model),
                                        'generation_time_seconds': elapsed,
                                        'cost': spent_before + (tryon_result or {}).get('cost', 0.05) + prep_cost,
                                    })
                                    retry_cr.commit()
                                    _logger.info('Veritabanı çakışması sonrası AI sonucu başarıyla kaydedildi (gen=%s)', gen.id)
                                    continue
                        except Exception as retry_err:
                            _logger.error('Veritabanı çakışması kurtarma denemesi başarısız oldu: %s', retry_err)

                    from ..services.fal_error_handler import parse_fal_error
                    parsed = parse_fal_error(e)
                    _logger.error('AI üretim hatası (gen=%s): %s', gen.id, e)
                    try:
                        with self.pool.cursor() as err_cr:
                            err_env = api.Environment(err_cr, uid, {'lang': 'tr_TR'})
                            e_gen = err_env['ai.studio.generation'].browse(gen.id)
                            e_gen.write(_failure_vals(e))
                            err_cr.commit()
                        if photo_type == 'front':
                            front_failed = True
                    except Exception as db_e:
                        _logger.error('Uretim hatasi kaydedilemedi (gen=%s): %s', gen.id, db_e)

        # ═══ TÜM ÜRETİMLER TAMAMLANDI — TAZE TRANSACTION İLE STATE GÜNCELLE ═══
        for attempt in range(5):
            try:
                with self.pool.cursor() as final_cr:
                    final_env = api.Environment(final_cr, uid, {'lang': 'tr_TR'})
                    final_session = final_env['ai.studio.session'].sudo().browse(session_id)
                    if final_session.state not in ('preprocessing', 'processing'):
                        # İptal edildi / sıfırlandı — kullanıcının kararını ezme
                        _logger.info('Oturum son durumu yazılmadı, mevcut state=%s (session_id=%s)',
                                     final_session.state, session_id)
                        break

                    has_done = any(g.state == 'done' for g in final_session.generation_ids)
                    has_failed = any(g.state == 'failed' for g in final_session.generation_ids)
                    still_running = any(g.state in ('pending', 'processing') for g in final_session.generation_ids)
                    # Sürmekte olan (ör. cron'un fal'den alacağı) üretim varsa oturum işlemede
                    # kalır; hepsi bitince cron review/failed'a taşır
                    final_state = 'processing' if still_running else ('review' if has_done else 'failed')

                    final_vals = {'state': final_state}
                    if final_state == 'review':
                        final_vals['date_review_start'] = fields.Datetime.now()
                    final_session.write(final_vals)
                    final_cr.commit()
                    _logger.info('Oturum başarıyla %s durumuna geçirildi (session_id=%s)', final_state, session_id)

                    # message_post ayrı bir try içinde, state'i ASLA rollback ettirmemeli
                    try:
                        if has_failed:
                            done_count = len(final_session.generation_ids.filtered(lambda g: g.state == 'done'))
                            fail_count = len(final_session.generation_ids.filtered(lambda g: g.state == 'failed'))
                            final_session.message_post(body=_(
                                'AI üretimi tamamlandı: ✅ %d başarılı, ❌ %d başarısız. '
                                '"🔄 Kaldığı Yerden Devam Et" butonu ile başarısız olanları tekrar deneyebilirsiniz.'
                            ) % (done_count, fail_count))
                        else:
                            final_session.message_post(body=_('AI üretimi tamamlandı. %d görsel onay bekliyor.') % len(final_session.generation_ids))
                        final_cr.commit()
                    except Exception as msg_e:
                        _logger.warning('Oturum tamamlama mesajı paylaşılamadı (session_id=%s): %s', session_id, msg_e)
                    break
            except Exception as final_write_err:
                _logger.warning('Oturum son durum güncellemesi kilit çakışması (session_id=%s, deneme %d/5): %s', session_id, attempt + 1, final_write_err)
                time.sleep(1.0 + attempt * 0.5)

    def _process_single_generation(self, generation, check_budget=True):
        """Tek bir 'pending' generation'ı (retry / revizyon) kuyruğa al.

        İş HTTP isteğinde değil kuyruk cron'unda yapılır (_cron_process_queue).
        """
        # Kuyruk yalnız bu durumlardaki oturumların üretimlerini alır (bkz. _queue_*_domain)
        if self.state not in ('preprocessing', 'processing', 'review', 'failed'):
            raise UserError(_('Bu oturum durumunda (%s) yeniden üretim yapılamaz.') % self.state)
        if check_budget:
            self._check_monthly_budget()
        if not self._get_active_api_key():
            raise UserError(_('AI API anahtarı ayarlanmamış.'))
        self._trigger_ai_queue()

    def _retry_generation_thread_body(self, session_id, gen_id, api_key, uid, lease_owner=None):
        """Tek generation'ı (retry / revizyon) işle (kuyruk işi; kendi cursor'ını açar)."""
        _logger.info("AI Retry Thread starting for session %s, gen %s with uid %s", session_id, gen_id, uid)
        with self.pool.cursor() as cr:
            env = api.Environment(cr, uid, {'lang': 'tr_TR'})

            def _keep_lease():
                # Hazırlık adımları dakikalar sürer; kira dolarsa stuck cron işi devralır
                if lease_owner:
                    _renew_session_lease(cr, session_id, lease_owner)
                    cr.commit()

            # Fetch prompt locks OUTSIDE
            all_locks = env['ai.studio.prompt.template'].search([
                ('scope', '=', 'global'),
                ('active', '=', True),
            ])
            global_prompt_locks = [l.prompt_text for l in all_locks]
            
            provider_type = env['ir.config_parameter'].sudo().get_param(
                'ugurlar_ai_studio.default_provider', 'fashn'
            )
            fal_api_key = env['ir.config_parameter'].sudo().get_param(
                'ugurlar_ai_studio.fal_api_key', ''
            )
            gemini_api_key = env['ir.config_parameter'].sudo().get_param(
                'ugurlar_ai_studio.gemini_api_key', ''
            )
            tryon_model = _get_tryon_model(env)
            tryon_resolution = '2K'

            session = env['ai.studio.session'].browse(session_id)
            gen = env['ai.studio.generation'].browse(gen_id)
            _start_usage_recording(env, session, gen)
            # Semaphore beklenirken üretim başka yerde tamamlanmış/iptal edilmiş olabilir:
            # yeniden çalıştırmak mükerrer ücret ve onaylı görselin üzerine yazma demek
            if not gen.exists() or gen.state != 'pending':
                _logger.info('AI Retry Thread: gen %s artık bekleyen durumda değil (%s), atlandı.',
                             gen_id, gen.exists() and gen.state)
                return
            photo_type = gen.photo_type or 'front'
            # Önceki denemelerde harcanan (başarısız denemenin hazırlığı dahil) üzerine eklenir
            spent_before = gen.cost or 0.0

            try:
                provider = self._create_provider(api_key, provider_type)

                _safe_write_and_commit(cr, gen, dict(CLEAR_FAL_REQUEST, state='processing'))
                if lease_owner:
                    _renew_session_lease(cr, session_id, lease_owner)
                    cr.commit()

                # Türkçe revizyon talimatının İngilizcesi yoksa burada (HTTP isteği
                # dışında) çevir — model İngilizce prompt bekliyor
                if gen.revision_prompt and not gen.revision_prompt_en:
                    try:
                        translated = gen._translate_prompt(gen.revision_prompt)
                        if translated and translated != gen.revision_prompt:
                            _safe_write_and_commit(cr, gen, {'revision_prompt_en': translated})
                    except Exception as tr_err:
                        _logger.warning('Revizyon çevirisi başarısız (gen=%s): %s', gen_id, tr_err)

                # ═══ SEEDREAM REVİZYON EDIT (revision_prompt varsa) ═══
                revision_text = gen.revision_prompt_en or gen.revision_prompt or ''
                parent_gen = gen.parent_generation_id
                if revision_text and parent_gen and parent_gen.generated_image and fal_api_key:
                    try:
                        _logger.info('Seedream EDIT revizyonu baslatiliyor (gen=%s): %s', gen_id, revision_text[:80])
                        from ..services.fal_provider import FalProvider
                        edit_provider = FalProvider(fal_api_key)

                        # Parent görseli CDN'e yükle
                        parent_b64 = parent_gen.generated_image
                        if isinstance(parent_b64, bytes):
                            parent_b64 = parent_b64.decode('ascii')
                        parent_url = edit_provider.upload_image(parent_b64)

                        # Seedream edit prompt
                        seedream_prompt = (
                            f"This is a fashion e-commerce photo (Figure 1). "
                            f"Apply ONLY this specific edit to Figure 1: {revision_text}. "
                            f"Keep everything else in Figure 1 exactly the same — "
                            f"same model, same pose, same hairstyle, same shoes, same background, same lighting. "
                            f"Change ONLY what is described above. Output one image. "
                        )

                        edit_app = 'bytedance/seedream/v5/pro/edit'
                        edit_result = edit_provider.run_queued(
                            edit_app,
                            {'prompt': seedream_prompt, 'image_urls': [parent_url]},
                            on_enqueue=_make_enqueue_recorder(self.pool, gen.id),
                            timeout=180,
                        )
                        cr.commit()  # on_enqueue sonrası snapshot'ı yenile
                        # Düzenleme ücretlendi: görsel indirilemese de (sıfırdan üretime düşülür) sayılır
                        spent_before += FalProvider.ESTIMATED_COSTS.get(edit_app, 0.135)
                        _safe_write_and_commit(cr, gen, {'cost': spent_before})

                        edit_images = edit_result.get('images', []) if isinstance(edit_result, dict) else []
                        img_url = ''
                        if edit_images:
                            first = edit_images[0]
                            img_url = first.get('url', '') if isinstance(first, dict) else (first or '')
                        if img_url:
                            import requests as req_lib
                            import base64 as b64_lib
                            img_resp = req_lib.get(img_url, timeout=30)
                            if img_resp.status_code == 200:
                                img_content = _convert_to_jpeg(img_resp.content)
                                result_b64 = b64_lib.b64encode(img_content).decode('ascii')
                                _safe_write_and_commit(cr, gen, {
                                    'generated_image': result_b64,
                                    'state': 'done',
                                    'error_message': '',
                                    'fal_endpoint': edit_app,
                                    'cost': spent_before,
                                })
                                _logger.info('Seedream EDIT revizyonu basarili (gen=%s)', gen_id)
                                return  # Seedream edit başarılı
                    except Exception as edit_err:
                        cr.rollback()
                        if _is_client_timeout(edit_err) and _get_request_id(cr, gen_id):
                            # İş fal'de sürüyor: sıfırdan üretmek ikinci ücret olur
                            _logger.warning('Seedream EDIT zaman aşımı (gen=%s): sonuç cron ile kurtarılacak', gen_id)
                            return
                        _logger.warning('Seedream EDIT basarisiz, sifirdan uretim yapilacak: %s', edit_err)

                source_image = gen.original_image or (gen.source_photo_id and gen.source_photo_id.image_original)
                preset = session.model_preset_id

                # ═══ DETAY İŞLEMİ (DRY helper) ═══
                if photo_type == 'detail':
                    auto_bg = env['ir.config_parameter'].sudo().get_param(
                        'ugurlar_ai_studio.auto_bg_remove', 'True'
                    ) == 'True'
                    detail_b64 = self._process_detail_generation(
                        gen, session, provider, source_image, auto_bg, provider_type, preset
                    )
                    gen.write({
                        'generated_image': detail_b64,
                        'state': 'done',
                        'fal_endpoint': 'detail-crop',
                        'error_message': False,
                    })
                    cr.commit()
                    return

                # ═══ TRY-ON RETRY İŞLEMİ (DRY helper) ═══
                auto_bg = env['ir.config_parameter'].sudo().get_param(
                    'ugurlar_ai_studio.auto_bg_remove', 'True'
                ) == 'True'

                detected_cat = session._detect_garment_type()

                # Analiz, manken seçiminden ÖNCE: kategori (elbise mi?) kararı hem mankeni
                # (pantolonsuz sürüm) hem promptu hem de denetim ipucunu belirler.
                # Etiketi silinmiş görsel değil orijinal analiz edilir: silme bir detayı
                # (fermuar, logo) götürmüşse analiz de onu görmez, prompt tarif etmez
                analysis = None
                try:
                    from ..services.garment_analyzer import analyze_garment
                    from ..services.garment_preprocessor import preprocess_garment_image
                    _pre = preprocess_garment_image(source_image, target_long_edge=1600)
                    analysis = analyze_garment(fal_api_key, provider.upload_image(_pre['image_base64']),
                                               gemini_api_key=gemini_api_key,
                                               product_context=session._get_product_context_text())
                except Exception as ae:
                    _logger.warning('Retry kıyafet analizi başarısız: %s', ae)
                _mark_coord_set(session, analysis)
                _logger.info('Ürün detayları: %s', design_hint(analysis) or '-')
                _keep_lease()

                # Etiketler _prepare_garment_for_tryon içinde ayrı taramayla bulunur
                garment_url, processed_b64, erase_cost = self._prepare_garment_for_tryon(
                    source_image, provider, session, auto_bg=auto_bg, security_tags=None,
                    photo=gen.source_photo_id,
                    design_details=design_hint(analysis) if photo_type == 'front' else '',
                    garment_text=_garment_text(analysis),
                )
                _keep_lease()
                if photo_type == 'front':
                    self._apply_fastener_check(session, analysis, gen.source_photo_id, processed_b64)
                    _keep_lease()
                own_photo = (gen.source_photo_id.photo_type or photo_type) == photo_type
                keep_boxes, view_construction = self._garment_view_info(
                    session, gen.source_photo_id, processed_b64, photo_type, own_photo=own_photo)
                _keep_lease()
                if isinstance(analysis, dict):
                    gemini_cat = analysis.get('clothingCategory', '')
                    if gemini_cat in ('dress', 'one_piece', 'one-piece', 'full-body') and not analysis.get('isSet'):
                        detected_cat = 'one_piece'
                        analysis['clothingCategory'] = 'dress'
                    elif detected_cat in ('tops', 'bottoms', 'one_piece'):
                        analysis['clothingCategory'] = (
                            'tops' if detected_cat == 'tops' else (
                                'bottoms' if detected_cat == 'bottoms' else 'dress'
                            )
                        )

                mannequin_variant = _mannequin_variant(session, analysis)
                model_image, mannequin_cost = _get_mannequin_image(session, preset, photo_type, mannequin_variant)
                prep_cost = (erase_cost or 0.0) + (mannequin_cost or 0.0)
                if not model_image:
                    raise Exception('Preset manken resmi eksik.')

                model_url = provider.upload_image(model_image)

                if detected_cat in ('tops', 'bottoms', 'one_piece', 'bags', 'shoes'):
                    category_to_send = (
                        'tops' if detected_cat == 'tops' else (
                            'bottoms' if detected_cat == 'bottoms' else (
                                ('one-piece' if provider_type != 'fashn' else 'one-pieces') if detected_cat == 'one_piece' else detected_cat
                            )
                        )
                    )
                elif session.category and session.category != 'auto':
                    category_to_send = {
                        'tops': 'tops',
                        'bottoms': 'bottoms',
                        'one_piece': 'one-pieces' if provider_type == 'fashn' else 'one-piece',
                    }.get(session.category, 'tops')
                else:
                    cat_fallback = preset.garment_type or 'tops'
                    category_to_send = {
                        'tops': 'tops',
                        'bottoms': 'bottoms',
                        'one_piece': 'one-pieces' if provider_type == 'fashn' else 'one-piece',
                    }.get(cat_fallback, 'tops')

                # ═══ CROSS-VIEW TUTARLILIK VERİSİ VE BAZ CACHE (Retry İçin) ═══
                outfit_consistency = None
                front_result_b64 = None
                front_output_url = None
                detail_urls = []
                # Ön görünüm yeniden üretimi seed'siz; arka/yan ön görünümün gerçek seed'ini alır
                front_seed = False

                # PERF: Boydan manken çekimlerinde detay fotoğraflarını göndermiyoruz (hız ve oran tutarlılığı)
                detail_urls = []

                if photo_type in ('back', 'side', 'detail'):
                    # Session içindeki tamamlanmış front kaydını bul
                    front_gen = session.generation_ids.filtered(lambda g: g.photo_type == 'front' and g.state == 'done')
                    if front_gen and front_gen[0].generated_image:
                        front_result_b64 = front_gen[0].generated_image
                        front_seed = front_gen[0].seed or False
                        try:
                            front_output_url = provider.upload_image(front_result_b64)
                        except Exception as up_e:
                            # Ön referanssız devam edilir (tutarlılık düşer ama üretim sürer)
                            _logger.warning('Retry: ön yüz referans görseli yüklenemedi (gen=%s): %s',
                                            gen_id, up_e)

                        # Elbise/etek/şortta sonucu kullanılmıyor (ücretli çağrıyı atla)
                        if mannequin_variant != 'legs':
                            try:
                                from ..services.garment_analyzer import analyze_outfit_consistency
                                outfit_consistency = analyze_outfit_consistency(
                                    front_result_b64,
                                    api_key=fal_api_key,
                                    gemini_api_key=gemini_api_key,
                                    category=category_to_send,
                                )
                            except Exception as oe:
                                _logger.warning('Retry outfit tutarlılık analizi başarısız: %s', oe)

                # ═══ VIEW-SPESİFİK PROMPT ═══
                prompt_text = ""
                negative_prompt_text = ""
                try:
                    prompt_locks = global_prompt_locks

                    from ..services.garment_analyzer import build_generation_prompt

                    preset_data = {
                        'gender': preset.gender or 'female',
                        'body_type': preset.body_type or 'standard',
                        'target_audience': preset.target_audience or '',
                    }

                    built_prompt = build_generation_prompt(
                        analysis, preset_data, prompt_locks,
                        ' '.join(filter(None, [_build_revision_instruction(gen), _get_extra_prompt_en(session)])),
                        photo_type=photo_type,
                        outfit_consistency=outfit_consistency,
                        provider_type=provider_type,
                        scene_prompt=(session.scene_id.prompt_additions or '') if session.scene_id else '',
                        has_front_ref=bool(front_output_url),
                        view_construction=view_construction,
                        keep_boxes=keep_boxes,
                        bbox_grounding=provider_type == 'fal' and 'v5' in _get_tryon_model(env),
                    )
                    prompt_text = built_prompt.get('positive', '') if isinstance(built_prompt, dict) else ''
                    negative_prompt_text = built_prompt.get('negative', '') if isinstance(built_prompt, dict) else ''
                except Exception as pe:
                    _logger.warning('Failed to build retry prompt: %s', pe)

                if provider_type == 'fal':
                    # Ayardaki Seedream modeli (v4 Edit seed'li / v5 Pro Edit)
                    tryon_model = _get_tryon_model(env)
                elif provider_type == 'fashn':
                    tryon_model = getattr(preset, f'fashn_model_{photo_type}', False) or getattr(preset, 'fashn_model_front', False) or 'tryon-v1.6'

                if photo_type in ('back', 'side'):
                    _logger.info('%s yeniden üretimi: ön görsel %s, seed %s iletiliyor (model=%s, session=%s)',
                                 photo_type, 'Image 3 olarak' if front_output_url else 'YOK',
                                 front_seed or 'yok', tryon_model, session.name)

                if prep_cost:
                    gen.write({'cost': spent_before + prep_cost})
                if lease_owner:
                    _renew_session_lease(cr, session_id, lease_owner)
                cr.commit()
                tryon_kwargs = dict(
                    model_image_url=model_url,
                    garment_image_url=garment_url,
                    category=category_to_send,
                    mode=session.quality_mode or 'quality',
                    model_name=tryon_model,
                    num_samples=1,
                    garment_photo_type='flat-lay' if 'fashn/' in tryon_model else 'auto',
                    output_format='jpeg',
                    prompt=prompt_text,
                    negative_prompt=negative_prompt_text,
                    front_output_url=front_output_url,
                    detail_urls=detail_urls,
                    resolution=tryon_resolution,
                    image_size=_get_seedream_image_size(env),
                    photo_type=photo_type,
                    seed=front_seed,
                    garment_type=(analysis or {}).get('garmentType', '') if isinstance(analysis, dict) else '',
                    on_enqueue=_make_enqueue_recorder(self.pool, gen.id),
                )
                tryon_result = provider.virtual_tryon(**tryon_kwargs)
                cr.commit()  # on_enqueue sonrası snapshot'ı yenile (bkz. ana döngü)

                # ═══ SONUCU İNDİR (DRY helper) ═══
                gen_b64, gen_seed = self._download_tryon_result(tryon_result or {})

                if gen_b64:
                    gen_vals = {
                        'generated_image': gen_b64,
                        'state': 'done',
                        'error_message': False,
                        'seed': gen_seed or (front_seed if photo_type in ('back', 'side') else False) or False,
                        # Yeniden üretimin maliyeti de kaydedilmeli (önceden yazılmıyordu)
                        'cost': spent_before + (tryon_result or {}).get('cost', 0.0) + prep_cost,
                        'fal_endpoint': '%s/%s' % (provider_type, tryon_model),
                    }

                    # Kalite kontrol (+ Gemini görsel denetim + etiket silme)
                    try:
                        def _qc(img_b64, base_cost):
                            return _run_quality_check(
                                env, source_image, img_b64, gemini_api_key,
                                analysis=analysis, category=category_to_send, gen=gen,
                                base_cost=base_cost, reference_image=processed_b64,
                                photo_type=photo_type, check_missing=own_photo,
                                view_construction=view_construction, removed_boxes=keep_boxes,
                            )

                        def _refresh():
                            if lease_owner:
                                _renew_session_lease(cr, session_id, lease_owner)
                            cr.commit()

                        _regenerate, _fallback = _make_regenerators(
                            provider, tryon_kwargs, self._download_tryon_result, _refresh,
                            provider_type, photo_type)
                        qc_vals = _qc(gen_b64, gen_vals['cost'])
                        _final_b64, qc_vals = _fidelity_retry(
                            env, gen, gen_b64, qc_vals, gen_vals['cost'], _regenerate, _qc,
                            fallback=_fallback)
                        gen_vals.update(qc_vals)
                    except Exception as qe:
                        _logger.warning('Retry kalite kontrol hatası (gen=%s): %s', gen.id, qe)

                    _safe_write_and_commit(cr, gen, gen_vals)
                else:
                    _safe_write_and_commit(cr, gen, {
                        'state': 'failed',
                        'error_message': _('API görsel çıktısı döndürmedi veya üretim başarısız oldu.'),
                    })

            except Exception as e:
                cr.rollback()
                from ..services.fal_error_handler import format_fal_error_for_log
                _logger.error('Retry hatası: %s', format_fal_error_for_log(e, f'gen={gen_id}'))
                try:
                    if _is_client_timeout(e) and _get_request_id(cr, gen_id):
                        _logger.warning('fal istemci zaman aşımı (gen=%s): sonuç cron ile kurtarılacak', gen_id)
                    else:
                        _safe_write_and_commit(cr, gen, _failure_vals(e))
                except Exception as db_e:
                    cr.rollback()
                    _logger.error('Retry hatasi kaydedilemedi (gen=%s): %s', gen_id, db_e)

            # Session durumu güncellemesi (eğer tüm hatalılar çözüldüyse)
            try:
                if gen.session_id.state == 'failed':
                    all_gens = gen.session_id.generation_ids
                    if not any(g.state == 'failed' for g in all_gens):
                        _safe_write_and_commit(cr, gen.session_id, {'state': 'review'})
            except Exception as se:
                _logger.warning("Retry sonrasi session state guncellenirken hata: %s", se)

    def unlink(self):
        # Üretimler veritabanında cascade ile silinir (generation.unlink çağrılmaz): taslak
        # temizliği / oturum silme harcamayı maliyet raporundan düşürmesin
        self.env['ai.studio.usage']._keep_deleted_generation_costs(self.generation_ids)
        return super().unlink()

    def _get_month_ai_cost(self):
        """Bu ayki toplam AI harcaması (USD): üretimler + Gemini, manken, silinen üretim kayıtları."""
        month_start = fields.Datetime.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        total = 0.0
        for model in ('ai.studio.generation', 'ai.studio.usage'):
            groups = self.env[model].sudo()._read_group(
                [('create_date', '>=', month_start)], aggregates=['cost:sum'])
            total += (groups[0][0] if groups else 0.0) or 0.0
        return total

    def _budget_status(self):
        """(aşıldı mı, harcanan, bütçe) — bütçe 0 ise limitsiz."""
        budget = float(self.env['ir.config_parameter'].sudo().get_param(
            'ugurlar_ai_studio.monthly_budget', '0') or 0)
        if budget <= 0:
            return False, 0.0, 0.0
        spent = self._get_month_ai_cost()
        return spent >= budget, spent, budget

    def _check_monthly_budget(self):
        exceeded, spent, budget = self._budget_status()
        if exceeded:
            raise UserError(_(
                'Aylık AI bütçesi doldu: $%(spent).2f / $%(budget).2f. '
                'Yönetici Ayarlar > AI Studio > Aylık AI Bütçesi değerini artırabilir.',
                spent=spent, budget=budget))

    def _check_reviewer(self):
        """Onaycı/yönetici yetkisi yoksa hata ver (RPC ile doğrudan çağrılara karşı)."""
        if not (self.env.su or self.env.is_admin()
                or self.env.user.has_group('ugurlar_ai_studio.group_ai_studio_reviewer')):
            raise UserError(_('Bu işlem için onaycı veya yönetici yetkisi gereklidir.'))

    def action_mark_done(self):
        """Onaylanmış görselleri ürüne kaydet ve oturumu tamamla (Senkron)."""
        self.ensure_one()
        self._check_reviewer()
        if self.state != 'review':
            raise UserError(_('Bu oturum tamamlanabilir durumda değil.'))
        if self.generation_ids.filtered(lambda g: g.state in ('pending', 'processing')):
            # Süren revizyon, oturum kapandıktan sonra biterse ürüne hiç kaydedilmez
            raise UserError(_('İşlenmekte olan üretimler var; tamamlanmalarını bekleyin.'))
        approved = self.generation_ids.filtered(
            lambda g: g.is_approved and g.state == 'done' and not g.is_excluded
        )
        if not approved:
            raise UserError(_('En az bir görsel onaylanmalı.'))

        has_primary = approved.filtered(lambda g: g.is_primary)
        if not has_primary:
            front = approved.filtered(lambda g: g.photo_type == 'front')[:1]
            primary = front or approved[0]
            primary.is_primary = True

        # Doğrudan ürüne kaydet
        self._save_to_product(approved)
        # Seçilmeyen alternatif adaylar artık gereksiz — depolamayı boşalt
        self.generation_ids.candidate_ids.unlink()

        self.reviewer_id = self.env.user
        self.state = 'done'
        self.date_done = fields.Datetime.now()
        self.message_post(
            body=_('%d onaylı görsel ürüne başarıyla kaydedildi.') % len(approved),
        )

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Başarılı'),
                'message': _('%d görsel ürüne kaydedildi.') % len(approved),
                'type': 'success',
                'sticky': False,
            }
        }

    def _save_to_product(self, approved_generations):
        """Onaylı görselleri ürün kartına aktar."""
        import logging
        _logger = logging.getLogger(__name__)

        # Takım (kombin) kaydı yalnızca gerçekten kombin üretimi varsa. Set satırı
        # olup kombin üretimi olmayan oturumda set moduna girmek onaylı arka/yan/
        # detay görsellerini sessizce atıyordu (kombin üretimini yapan akış yok).
        if approved_generations.filtered(lambda g: g.generation_mode == 'set_combo'):
            return self._save_to_product_set_mode(approved_generations)

        # ═══ TEKLİ MOD ═══
        product = self.product_id
        if not product:
            raise UserError(_('Ürün bulunamadı.'))

        products = product
        if self.apply_to_siblings and self.sibling_product_ids:
            products |= self.sibling_product_ids

        primary = approved_generations.filtered('is_primary')[:1]
        if not primary:
            primary = approved_generations[0]
            primary.is_primary = True

        others = approved_generations - primary
        tmpl = product.product_tmpl_id

        self.env.cr.execute("SELECT id FROM product_template WHERE id = %s FOR NO KEY UPDATE", (tmpl.id,))

        # 1. Eski AI görsellerini temizle — SADECE bu renk grubunun varyantları
        # (template geneli arama diğer renklerin AI galerisini siliyordu)
        existing_ai_images = self.env['product.image'].search([
            ('product_variant_id', 'in', products.ids),
            ('name', 'like', '%% - AI (%%'),
        ])
        if existing_ai_images:
            existing_ai_images.unlink()

        # 2. Ana resmi varyantlara ata; template resmini yalnızca boşsa veya
        # kaydedilen varyantlar template'in tamamını kapsıyorsa değiştir
        if not tmpl.image_1920 or not (tmpl.product_variant_ids - products):
            tmpl.write({'image_1920': primary.generated_image})
        variant_records = products.filtered(lambda p: hasattr(p, 'image_variant_1920'))
        if variant_records:
            variant_records.write({'image_variant_1920': primary.generated_image})

        # 3. Ek görselleri TEK BATCH (vals_list) halinde oluştur (döngü içinde flush_model çağrılmaz!)
        image_vals_list = []
        for prod in products:
            sequence = 10
            for gen in others:
                type_label = dict(
                    gen._fields['photo_type'].selection
                ).get(gen.photo_type, 'Görsel')
                image_vals_list.append({
                    'product_tmpl_id': tmpl.id,
                    'product_variant_id': prod.id,
                    'name': f'{type_label} - AI ({gen.revision_number})',
                    'image_1920': gen.generated_image,
                    'sequence': sequence,
                })
                sequence += 10

        if image_vals_list:
            self.env['product.image'].create(image_vals_list)

    def _save_to_product_set_mode(self, approved_generations):
        """Takım modu: Her ürüne tekli ön + kombin görselleri kaydet.
        
        Sıralama (her ürün için):
          _1: Tekli ön görsel (ANA GÖRSEL) — müşteri bunu görür
          _2: Kombin ön
          _3: Kombin arka  
          _4: Kombin yan
          _5: Kombin detay
        """
        import logging
        _logger = logging.getLogger(__name__)
        
        # Kombin görselleri (tüm ürünlere aynı gidecek)
        combo_gens = approved_generations.filtered(
            lambda g: g.generation_mode == 'set_combo'
        ).sorted(key=lambda g: ['front', 'back', 'side', 'detail'].index(g.photo_type) if g.photo_type in ['front', 'back', 'side', 'detail'] else 99)
        
        # Her takım parçası için
        for set_line in self.set_line_ids:
            product = set_line.product_id
            if not product:
                continue
                
            tmpl = product.product_tmpl_id
            
            # Row lock
            self.env.cr.execute("SELECT id FROM product_template WHERE id = %s FOR NO KEY UPDATE", (tmpl.id,))
            
            # Renk kardeşleri
            products = product
            if self.apply_to_siblings:
                products |= self._get_set_line_siblings(set_line)
            
            # Bu parçanın tekli ön görseli
            if set_line.role == 'primary':
                single_front = approved_generations.filtered(
                    lambda g: g.generation_mode == 'single' and g.photo_type == 'front' and not g.set_line_id
                )[:1]
            else:
                single_front = approved_generations.filtered(
                    lambda g: g.generation_mode == 'single' and g.photo_type == 'front' and g.set_line_id.id == set_line.id
                )[:1]
            
            if not single_front:
                _logger.warning('Takım parçası %s için tekli ön görsel bulunamadı, atlanıyor.', set_line.product_name)
                continue
            
            # Eski AI görsellerini temizle — sadece bu renk grubunun varyantları
            existing_ai = self.env['product.image'].search([
                ('product_variant_id', 'in', products.ids),
                ('name', 'like', '%% - AI (%%'),
            ])
            if existing_ai:
                existing_ai.unlink()
            
            # _1: Tekli ön → Ana görsel (template'i yalnızca boşsa / tamamı kapsanıyorsa)
            if not tmpl.image_1920 or not (tmpl.product_variant_ids - products):
                tmpl.write({'image_1920': single_front.generated_image})
            
            variant_records = products.filtered(lambda p: hasattr(p, 'image_variant_1920'))
            if variant_records:
                variant_records.write({'image_variant_1920': single_front.generated_image})
            
            # _2, _3, _4, _5: Kombin görselleri BATCH halinde oluştur
            combo_image_vals = []
            for prod in products:
                sequence = 10
                for gen in combo_gens:
                    type_label = dict(
                        gen._fields['photo_type'].selection
                    ).get(gen.photo_type, 'Görsel')
                    combo_image_vals.append({
                        'product_tmpl_id': tmpl.id,
                        'product_variant_id': prod.id,
                        'name': f'Takım {type_label} - AI ({self.name})',
                        'image_1920': gen.generated_image,
                        'sequence': sequence,
                    })
                    sequence += 10

            if combo_image_vals:
                self.env['product.image'].create(combo_image_vals)
            
            _logger.info('Takım görselleri kaydedildi: %s (%d varyant)', set_line.product_name, len(products))

    def _get_set_line_siblings(self, set_line):
        """Takım parçasının renk kardeşlerini bul."""
        product = set_line.product_id
        color_attr_names = {'renk', 'color', 'colour'}
        current_color_id = None
        for ptav in product.product_template_attribute_value_ids:
            attr_name = ptav.attribute_id.name.lower().strip()
            if any(c in attr_name for c in color_attr_names):
                current_color_id = ptav.id
                break
        
        if not current_color_id:
            return self.env['product.product']
        
        return product.product_tmpl_id.product_variant_ids.filtered(
            lambda v: v.id != product.id and current_color_id in v.product_template_attribute_value_ids.ids
        )

    def action_cancel(self):
        """Oturumu iptal et."""
        self._check_reviewer()
        for session in self:
            session.state = 'cancelled'
            stuck_gens = session.generation_ids.filtered(
                lambda g: g.state in ('pending', 'processing')
            )
            for g in stuck_gens:
                g.write({
                    'state': 'failed',
                    'error_message': _('Kullanıcı tarafından oturum iptal edildi.'),
                })
            session.message_post(body=_('Oturum iptal edildi.'))

    def action_reset_draft(self):
        """Taslak durumuna geri dön (yalnızca iptal/başarısız oturumlar)."""
        self._check_reviewer()
        for session in self:
            if session.state not in ('cancelled', 'failed'):
                raise UserError(_('Yalnızca iptal edilmiş veya başarısız oturumlar taslağa döndürülebilir.'))
            session.state = 'draft'

    # ═══════════════════════════════════════════════════════════════════
    # KUYRUK YÖNETİMİ (cron) — veritabanı kirası + fal request_id kurtarma
    # ═══════════════════════════════════════════════════════════════════

    def _lease_free_domain(self, prefix=''):
        now = fields.Datetime.now()
        return ['|', (prefix + 'ai_lease_until', '=', False), (prefix + 'ai_lease_until', '<', now)]

    def _get_active_api_key(self):
        icp = self.env['ir.config_parameter'].sudo()
        provider_type = icp.get_param('ugurlar_ai_studio.default_provider', 'fashn')
        return icp.get_param('ugurlar_ai_studio.fashn_api_key' if provider_type == 'fashn'
                             else 'ugurlar_ai_studio.fal_api_key')

    @api.model
    def _recover_submitted_generation(self, gen, client):
        """fal'e gönderilmiş (request_id'li) ama sahibi ölmüş bir üretimin sonucunu al.

        Yeniden GÖNDERMEZ — aynı işin sonucunu fal kuyruğundan okur.
        Returns: 'done' | 'failed' | 'waiting'
        """
        import fal_client
        from ..services.fal_provider import FalProvider
        app, request_id = gen.fal_app, gen.fal_request_id
        try:
            status = client.status(app, request_id)
            if not isinstance(status, fal_client.Completed):
                if gen.submitted_at and gen.submitted_at < fields.Datetime.now() - timedelta(minutes=SUBMITTED_TIMEOUT_MINUTES):
                    try:
                        client.cancel(app, request_id)
                    except Exception as cancel_err:
                        # İptal edilemese de üretim başarısız sayılır; fal işi kendi süresinde düşer
                        _logger.warning('fal isteği iptal edilemedi (gen=%s, request_id=%s): %s',
                                        gen.id, request_id, cancel_err)
                    gen.write({
                        'state': 'failed',
                        'error_message': _('fal.ai %d dakika içinde sonuç vermedi.') % SUBMITTED_TIMEOUT_MINUTES,
                        'error_type': 'timeout',
                        'is_retryable': True,
                    })
                    return 'failed'
                return 'waiting'
            result = client.result(app, request_id)
        except Exception as e:
            gen.write(_failure_vals(e))
            return 'failed'

        images = (result or {}).get('images') or []
        urls = [i.get('url') if isinstance(i, dict) else i for i in images]
        urls = [u for u in urls if u]
        if not urls and isinstance((result or {}).get('image'), dict):
            urls = [result['image'].get('url')]
        gen_b64, _seed = self._download_tryon_result({'image_urls': [u for u in urls if u]})
        if not gen_b64:
            gen.write({'state': 'failed', 'error_message': _('Kurtarılan fal sonucunda görsel yok.'),
                       'error_type': 'empty_result', 'is_retryable': True})
            return 'failed'
        if len(urls) > 1:
            _store_candidates(gen, urls[1:])
        # gen.cost try-on öncesi yazılan hazırlık maliyetini içerir; üzerine bu işin ücreti eklenir
        n_refs = 3 if gen.photo_type in ('back', 'side') else 2
        cost = (gen.cost or 0.0) + FalProvider.compute_cost(
            app, len(urls), n_refs, {'image_size': _get_seedream_image_size(self.env)})
        vals = {
            'generated_image': gen_b64,
            'state': 'done',
            'fal_endpoint': app,
            'cost': cost,
            'quality_details': _('Worker kesintisi sonrası fal kuyruğundan kurtarıldı (kalite denetimi yapılmadı).'),
        }
        # Kurtarılan sonuç da denetlenir: uydurma detay / etiket inceleme ekranında görünsün
        photo = gen.source_photo_id
        gemini_key = self.env['ir.config_parameter'].sudo().get_param('ugurlar_ai_studio.gemini_api_key', '')
        if gemini_key and photo and photo.garment_clean_image:
            try:
                _start_usage_recording(self.env, gen.session_id, gen)
                qc_vals = _run_quality_check(
                    self.env, photo.image_original, gen_b64, gemini_key, category=gen.session_id.category or '',
                    gen=gen, base_cost=cost, reference_image=photo.garment_clean_image,
                    photo_type=gen.photo_type, check_missing=photo.photo_type == gen.photo_type,
                    removed_boxes=json.loads(photo.garment_tag_boxes or '[]'))
                # Kurtarmada yeniden üretim yapılmaz: ürün değiştiyse yalnız işaretlenir
                fidelity = qc_vals.pop('_fidelity', 0) or 0
                qc_vals.pop('_fix', None)
                qc_vals['fidelity_failed'] = bool(fidelity)
                qc_vals['quality_details'] = (FIDELITY_FAILED_PREFIX if fidelity else '') + _('fal kuyruğundan kurtarıldı') + ' | ' + (qc_vals.get('quality_details') or '')
                vals.update(qc_vals)
            except Exception as qe:
                _logger.warning('Kurtarılan sonucun denetimi başarısız (gen=%s): %s', gen.id, qe)
            finally:
                clear_usage_recorder()
        gen.write(vals)
        _logger.info('Cron: fal sonucu kurtarıldı (gen=%s, request_id=%s)', gen.id, request_id)
        return 'done'

    def _finalize_idle_session_state(self):
        """Kirası boş, bekleyen işi kalmamış işleme-durumundaki oturumu review/failed yap."""
        for session in self:
            gens = session.generation_ids
            if any(g.state in ('pending', 'processing') for g in gens):
                continue
            has_done = any(g.state == 'done' for g in gens)
            vals = {'state': 'review' if has_done else 'failed'}
            if has_done:
                vals['date_review_start'] = fields.Datetime.now()
            session.write(vals)

    @api.model
    def _cron_check_stuck_generations(self):
        """Stuck cron girişi: çekirdeği her kayıttan sonra commit ederek çalıştırır."""
        self._check_stuck_generations(commit=self.env.cr.commit)

    def _stuck_step(self, label, record, func):
        """Tek kaydın adımını savepoint içinde çalıştır: bozuk kayıt cron'u durdurmaz."""
        try:
            with self.env.cr.savepoint():
                func()
            return True
        except Exception:
            _logger.exception('Stuck cron: %s başarısız (%s), kayıt atlandı', label, record)
            return False

    @api.model
    def _check_stuck_generations(self, commit=None):
        """Veritabanı tabanlı kuyruk bakımı (commit'siz çekirdek; testler doğrudan çağırır).

        Görevler (sırasıyla), her kayıt kendi savepoint'inde:
        0. fal'e gönderilmiş, sahibi ölmüş üretimlerin sonucunu request_id ile al
        1. Gönderilmeden ölmüş 'processing' üretimleri tekrar 'pending' yap
        2. Bekleyen işi kalmamış oturumları review/failed'a taşı
        3. Kalıcı olmayan hatalarla başarısız oturumları üstel beklemeyle yeniden dene
        4. İş varsa kuyruk cron'larını tetikle (işleme _cron_process_queue'da)
        """
        commit = commit or (lambda: None)
        Gen = self.env['ai.studio.generation']
        now = fields.Datetime.now()

        # ═══ 0: fal kuyruğundan kurtarma (yeniden ücret ödemeden) ═══
        submitted = Gen.search([
            ('state', '=', 'processing'),
            ('fal_request_id', '!=', False),
            ('fal_app', '!=', False),
        ] + self._lease_free_domain('session_id.'), limit=20, order='submitted_at asc')
        fal_key = submitted and self.env['ir.config_parameter'].sudo().get_param('ugurlar_ai_studio.fal_api_key')
        if fal_key:
            import fal_client
            client = fal_client.SyncClient(key=fal_key)
            timeout_at = now - timedelta(minutes=SUBMITTED_TIMEOUT_MINUTES)
            for gen in submitted:
                if not self._stuck_step('fal kurtarma', gen,
                                        lambda: self._recover_submitted_generation(gen, client)):
                    # NEDEN: kurtarma hep patlıyorsa (bozuk sonuç, silinmiş app) üretim sonsuza
                    # dek 'processing' kalır ve her 2 dk tekrar denenir; süre aşımında kapat
                    if gen.submitted_at and gen.submitted_at < timeout_at:
                        self._stuck_step('kurtarılamayan üretimi kapatma', gen, lambda: gen.write({
                            'state': 'failed', 'error_type': 'timeout', 'is_retryable': True,
                            'error_message': _('fal sonucu %d dakika içinde kurtarılamadı.')
                            % SUBMITTED_TIMEOUT_MINUTES,
                        }))
                commit()

        # ═══ 1: gönderilmeden ölmüş işler → tekrar kuyruğa ═══
        orphans = Gen.search([
            ('state', '=', 'processing'),
            '|', ('fal_request_id', '=', False), ('fal_app', '=', False),
            ('write_date', '<', now - timedelta(minutes=2)),
        ] + self._lease_free_domain('session_id.'))
        for gen in orphans:
            def _requeue(gen=gen):
                if gen.retry_count >= 3:
                    gen.write({'state': 'failed', 'error_type': 'orphaned', 'is_retryable': False,
                               'error_message': _('İşlem 3 kez yarıda kesildi (sunucu yeniden başlıyor olabilir).')})
                else:
                    gen.write(dict(CLEAR_FAL_REQUEST, state='pending', error_message=False,
                                   retry_count=gen.retry_count + 1))
                    _logger.warning('Cron: sahipsiz üretim tekrar kuyruğa alındı (gen=%s, deneme %d/3)',
                                    gen.id, gen.retry_count)
            self._stuck_step('sahipsiz üretimi kuyruğa alma', gen, _requeue)

        # ═══ 2: bekleyen işi kalmamış oturumları sonlandır ═══
        active_states = ['preprocessing', 'processing']
        for session in self.search([('state', 'in', active_states)] + self._lease_free_domain()):
            self._stuck_step('oturumu sonlandırma', session, session._finalize_idle_session_state)
        commit()

        # ═══ 3: otomatik yeniden deneme — sadece kalıcı olmayan hatalar, üstel bekleme ═══
        if not self._budget_status()[0]:
            failed_sessions = self.search([
                ('state', '=', 'failed'),
                ('retry_count', '<', 3),
                ('write_date', '>=', now - timedelta(minutes=60)),
            ])
            for session in failed_sessions:
                # 2, 4, 8 dakika bekle
                if session.write_date > now - timedelta(minutes=2 ** (session.retry_count + 1)):
                    continue
                retryable = session.generation_ids.filtered(lambda g: g.state == 'failed' and g.is_retryable)
                if not retryable:
                    continue

                def _auto_retry(session=session, retryable=retryable):
                    retryable.write(dict(CLEAR_FAL_REQUEST, state='pending', error_message=False, error_type=False))
                    session.write({'state': 'processing', 'retry_count': session.retry_count + 1})
                    _logger.info('Cron: başarısız oturum yeniden denemeye alındı (session=%s, retry=%d/3)',
                                 session.name, session.retry_count)
                if self._stuck_step('otomatik yeniden deneme', session, _auto_retry):
                    # Bilgi mesajı ayrı savepoint'te: chatter hatası yeniden denemeyi geri almasın
                    self._stuck_step('yeniden deneme mesajı', session, lambda session=session, n=len(retryable):
                                     session.message_post(body=_(
                                         '🔄 Otomatik yeniden deneme #%d/3 — %d üretim kuyruğa alındı.')
                                         % (session.retry_count, n)))

            # Retry limiti aşılmış oturumlar için tek seferlik bildirim
            for session in self.search([('state', '=', 'failed'), ('retry_count', '=', 3)]):
                def _notify_limit(session=session):
                    session.message_post(
                        body=_('❌ Otomatik yeniden deneme limiti (3/3) aşıldı. '
                               'Lütfen sorunu kontrol edip "🔄 Kaldığı Yerden Devam Et" ile tekrar deneyin.'))
                    session.write({'retry_count': 4})
                self._stuck_step('yeniden deneme limiti bildirimi', session, _notify_limit)

        # Ölü kuyruk işinde (worker yeniden başladı) 'generating' kalan manken: buton gizli
        # kalmasın. write_date işin alındığı an (_queue_claim_mannequin yazar).
        for preset in self.env['ai.studio.model.preset'].search([
                ('mannequin_generation_state', '=', 'generating'),
                ('write_date', '<', now - timedelta(minutes=MANNEQUIN_STUCK_MINUTES))]):
            _logger.warning('Stuck cron: manken üretimi yarıda kalmış (preset=%s), başarısız sayıldı', preset.id)
            self._stuck_step('takılmış manken üretimi', preset,
                             lambda preset=preset: preset.write({'mannequin_generation_state': 'failed'}))
        # NEDEN: kuyruk hiç çalışamıyorsa (API anahtarı silindi / concurrent_limit=0) 'queued' manken
        # sonsuza dek bekler ve "Manken Oluştur" gizli kalır. Kuyruk çalışırken uzun bekleme meşru
        # (toplu yeniden üretim, oturum işleri önce alınır) → yalnız durmuş kuyrukta kapatılır.
        queue_stalled = not self._get_active_api_key() or int(
            self.env['ir.config_parameter'].sudo().get_param('ugurlar_ai_studio.concurrent_limit', '2') or 2) < 1
        if queue_stalled:
            for preset in self.env['ai.studio.model.preset'].search([
                    ('mannequin_generation_state', '=', 'queued'),
                    ('write_date', '<', now - timedelta(minutes=MANNEQUIN_STUCK_MINUTES))]):
                _logger.warning('Stuck cron: kuyruk çalışamıyor, sıradaki manken başarısız sayıldı (preset=%s)',
                                preset.id)
                self._stuck_step('kuyrukta kalmış manken', preset,
                                 lambda preset=preset: preset.write({'mannequin_generation_state': 'failed'}))

        # ═══ 4: kuyruk cron'larını uyandır (kurtarılan ön yüz, yeniden kuyruğa alınanlar) ═══
        if self._queue_has_work():
            self._trigger_ai_queue()

    @api.model
    def _is_approval_authority(self):
        """Sunucu kodu (su), yönetici veya onaycı mı? ('saving' kapısını ve kilitleri bu geçer.)"""
        return bool(self.env.su or self.env.is_admin()
                    or self.env.user.has_group('ugurlar_ai_studio.group_ai_studio_reviewer'))

    def _check_saving_transition(self, vals):
        """'saving' kuyrukta cron yetkisiyle ürüne yazdırır; yalnız onaycı/yönetici (complete_session) veya
        sunucu kodu (su) bu duruma geçirebilir ve onaycıyı (reviewer_id) yazabilir.

        NEDEN: context bayrağı kullanılmadı; RPC istemcisi context'i kendi verebilir, grup denetimi verilemez.
        DIKKAT: operatörün perm_write'ı var; bu denetim kalkarsa onay adımı RPC ile atlanır. _run_save_job
        reviewer_id'ye güvenir: bu alan yalnız yetkili yazabildiği sürece onay izi sayılır.
        """
        if self._is_approval_authority():
            return
        if vals.get('state') == 'saving':
            raise AccessError(_('Oturumu ürüne kaydetmeye yalnız onaycı veya yönetici alabilir.'))
        if 'reviewer_id' in vals:
            raise AccessError(_('Onayıcı alanını yalnız onaycı veya yönetici değiştirebilir.'))
        # NEDEN (J10 KK4): 'done' onaycının kararıdır (D1-kalan: operatör review→done yazabiliyordu).
        # 'review'dan çıkış da kapalı: review→draft→içerik değiştir→review döngüsü onayı atlatırdı.
        if 'state' in vals and (vals['state'] == 'done'
                                or self.filtered(lambda s: s.state == 'review' and s.state != vals['state'])):
            raise AccessError(_('İncelemedeki oturumun durumunu yalnız onaycı veya yönetici değiştirebilir.'))

    def _drop_approvals_on_change(self, vals):
        """Yetkisiz kullanıcı ürüne yazılacak hedefi değiştirince oturumun onaylarını düşür (J10 KK2).

        Döndürür: onayı düşürülecek oturumlar (super().write SONRASI _drop_approvals ile).
        NEDEN: product_id / apply_to_siblings / session_type kuyruğun HANGİ ürünlere yazacağını belirler;
        onaycı başka bir hedefi onaylamıştı.
        """
        if self._is_approval_authority():
            return self.browse()
        changed = self.browse()
        for field_name in APPROVAL_TARGET_FIELDS & set(vals):
            field = self._fields[field_name]
            changed |= self.filtered(
                lambda s: field.convert_to_write(s[field_name], s) != (vals[field_name] or False))
        return changed

    def _drop_approvals(self, reason):
        gens = self.sudo().generation_ids
        approved = gens.filtered('is_approved')
        if not approved:
            return
        gens.filtered(lambda g: g.is_approved or g.is_primary).write({'is_approved': False, 'is_primary': False})
        for session in approved.session_id:
            session.message_post(body=_('Onaydan sonra %s değişti; onaylar kaldırıldı, yeniden inceleme gerekir.')
                                 % reason)

    def _check_approval_gate_created(self):
        """create sonrası denetim: default_* bağlamıyla gelen 'saving' / reviewer_id da yakalanır."""
        if self._is_approval_authority():
            return
        if self.filtered(lambda r: r.state == 'saving' or r.reviewer_id):
            raise AccessError(_('Oturumu ürüne kaydetmeye ve onayıcı atamaya yalnız onaycı veya yönetici yetkilidir.'))

    # Onaydan sonra ('saving'/'done') içerik değişmesin (A4 O1/Y2/O2): kilit kayıt kuralında
    # (security/ai_studio_security.xml, *_operator_edit) — create/o2m/context default/ek yollarının hepsinde
    # geçerli olduğu için model override'ı DEĞİL. Kuralın göremediği tek yol aşağıda.
    @api.model
    def _check_target_session_unlocked(self, vals, label):
        """Açık oturumdaki satırı session_id ile 'saving'/'done' oturuma TAŞIMA engeli.

        NEDEN: kayıt kuralı yazım ÖNCESİ kaydı denetler (o an açık oturumda) → taşımayı yakalamaz.
        """
        target = self.browse(vals.get('session_id') or [])
        if target.state in ('saving', 'done') and not self._is_approval_authority():
            raise AccessError(_('Onaylanan oturuma (%s) yalnız onaycı veya yönetici ekleme yapabilir.') % label)

    def write(self, vals):
        self._check_saving_transition(vals)
        drop = self._drop_approvals_on_change(vals)
        res = super(AiStudioSession, self).write(vals)
        if drop:
            drop._drop_approvals(_('ürün / kardeş / oturum türü'))
        if 'state' in vals:
            for record in self:
                if record.state in ('review', 'failed'):
                    # Bildirim asla state geçişini engellememeli
                    try:
                        record._notify_state_change()
                    except Exception as e:
                        _logger.warning("Durum bildirimi gönderilemedi (session=%s): %s", record.id, e)
                if record.state == 'review':
                    # Review durumuna geçtiğinde Aktivite oluşturmayı dene
                    # AMA asla state geçişini engellememelidir
                    try:
                        record._create_review_activities()
                    except Exception as e:
                        _logger.warning("Review aktivite oluşturma başarısız (session=%s): %s", record.id, e)
                elif record.state in ['done', 'cancelled']:
                    # Aktiviteleri kapatmayı dene (Batch)
                    try:
                        activities = self.env['mail.activity'].search([
                            ('res_id', '=', record.id),
                            ('res_model', '=', 'ai.studio.session'),
                        ])
                        if activities:
                            activities.action_done()
                    except Exception as e:
                        _logger.warning("Aktivite kapatma başarısız (session=%s): %s", record.id, e)

        return res

    def _get_reviewer_users(self):
        """Aktif onaycı/yönetici kullanıcılar."""
        reviewer_group = self.env.ref('ugurlar_ai_studio.group_ai_studio_reviewer', raise_if_not_found=False)
        users_model = self.env['res.users'].sudo()
        if not reviewer_group:
            return users_model
        # Odoo 19: group_ids yalnız doğrudan atanan gruplar; all_group_ids devralınanlar
        # dahil (yönetici grubu onaycıyı implied olarak içerir)
        groups_field = 'all_group_ids' if 'all_group_ids' in users_model._fields else 'groups_id'
        return users_model.search([(groups_field, 'in', reviewer_group.id), ('active', '=', True)])

    def _notify_state_change(self):
        """Anlık bildirim: incelemeye hazır olunca onaycılara toast; oturumu başlatanın
        işlem ekranına durum olayı (5 sn'lik polling'i beklemeden yenilensin)."""
        self.ensure_one()
        bus = self.env['bus.bus'].sudo()
        if self.create_uid.partner_id:
            bus._sendone(self.create_uid.partner_id, 'ai_studio.session_update',
                         {'session_id': self.id, 'state': self.state})
        if self.state == 'review':
            product = self.product_id.display_name or ''
            for user in self._get_reviewer_users():
                bus._sendone(user.partner_id, 'simple_notification', {
                    'title': _('📸 İncelemeye hazır'),
                    'message': '%s — %s' % (self.name, product),
                    'type': 'info',
                    'sticky': False,
                })

    def _create_review_activities(self):
        """Review durumuna geçişte onayıcılara aktivite oluşturur."""
        self.ensure_one()
        activity_type = self.env.ref('mail.mail_activity_data_todo', raise_if_not_found=False)
        if not activity_type:
            return

        reviewer_ids = self._get_reviewer_users().ids
        # processing↔review döngülerinde her seferinde yeni aktivite açılmasın
        existing = self.env['mail.activity'].sudo().search([
            ('res_model', '=', 'ai.studio.session'), ('res_id', '=', self.id),
            ('user_id', 'in', reviewer_ids),
        ]).mapped('user_id').ids
        reviewer_ids = [uid for uid in reviewer_ids if uid not in existing]

        if not reviewer_ids:
            return

        # Model ID'sini güvenli şekilde bul
        res_model = self.env['ir.model'].search([('model', '=', 'ai.studio.session')], limit=1)
        if not res_model:
            return

        for reviewer_id in reviewer_ids:
            try:
                self.env['mail.activity'].create({
                    'res_id': self.id,
                    'res_model_id': res_model.id,
                    'activity_type_id': activity_type.id,
                    'summary': _('Çekim Onayı Bekliyor'),
                    'note': _('%s için AI üretimleri tamamlandı. Onayınız bekleniyor.') % self.name,
                    'user_id': reviewer_id,
                })
            except Exception as e:
                _logger.warning("Aktivite oluşturulamadı (user=%s): %s", reviewer_id, e)
