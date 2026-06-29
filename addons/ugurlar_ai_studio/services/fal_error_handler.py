"""fal.ai hata ayristirma ve Turkce hata mesaji yardimlcilari.

fal.ai API'si iki tip hata dondurur:
1. Model hatalari (422): content_policy_violation, image_too_large, vb.
2. Altyapi hatalari (500/504): generation_timeout, runner_error, vb.

Bu modul her iki tipi de ayristirir ve kullaniciya anlamli Turkce mesajlar sunar.
"""
import json
import logging

_logger = logging.getLogger(__name__)

# --- fal.ai Hata Tipleri -> Turkce Mesajlar ---
FAL_ERROR_MESSAGES = {
    # Model hatalari (errors.md)
    'content_policy_violation': 'Icerik politikasi ihlali. Lutfen gorseli veya promptu kontrol edin.',
    'image_too_large': 'Gorsel cok buyuk. Lutfen daha kucuk cozunurluklu bir gorsel kullanin.',
    'image_too_small': 'Gorsel cok kucuk. Lutfen daha yuksek cozunurluklu bir gorsel kullanin.',
    'image_load_error': 'Gorsel yuklenemedi. Dosya bozuk veya desteklenmeyen formatta olabilir.',
    'file_download_error': 'Dosya indirilemedi. URL erisilebilir ve herkese acik olmali.',
    'face_detection_error': 'Gorselde yuz tespit edilemedi.',
    'file_too_large': 'Dosya boyutu cok buyuk.',
    'no_media_generated': 'AI gorsel uretemedi. Farkli bir prompt veya ayar deneyin.',
    'generation_timeout': 'Islem zaman asimina ugradi. Tekrar deneyin veya kalite modunu dusurun.',
    'internal_server_error': 'fal.ai sunucu hatasi. Lutfen tekrar deneyin.',
    'downstream_service_error': 'Harici servis hatasi. Lutfen tekrar deneyin.',
    'downstream_service_unavailable': 'Harici servis su anda kullanilamiyor. Lutfen daha sonra deneyin.',
    'unsupported_image_format': 'Desteklenmeyen gorsel formati. JPG, PNG veya WebP kullanin.',
    'feature_not_supported': 'Bu ozellik desteklenmiyor.',
    'one_of': 'Gecersiz deger. Lutfen izin verilen degerlerden birini secin.',
    'greater_than': 'Deger minimum sinirin altinda.',
    'less_than': 'Deger maksimum sinirin ustunde.',
    'multiple_of': 'Deger belirtilen katin kati olmali.',
    'invalid_parameters': 'Girdi parametreleri veya görsel formatı geçersiz. Lütfen ayarları kontrol edin.',
    'body_pose_detection_error': 'Manken görselinde insan vücut duruşu/pozu tespit edilemedi. Lütfen manken şablonundaki (Model Preset) model görselini kontrol edin. Net, tam veya yarım boy bir insan fotoğrafı olmalıdır.',
    # Altyapi hatalari (request-errors.md)
    'TIMEOUT': 'Sunucu zaman asimi. Tekrar deneyin.',
    'RATE_LIMITED': 'Istek hiz limiti asildi. Biraz bekleyip tekrar deneyin.',
    'concurrent_requests_limit': 'Eszamanli istek limiti asildi. Biraz bekleyip tekrar deneyin.',
}

# Yeniden denenebilir hata tipleri
RETRYABLE_ERRORS = {
    'internal_server_error',
    'downstream_service_unavailable',
    'generation_timeout',
    'TIMEOUT',
    'RATE_LIMITED',
    'concurrent_requests_limit',
}


def parse_fal_error(exception):
    """fal.ai hatasini ayristir ve Turkce mesaj dondur.

    Args:
        exception: Yakalanan Exception nesnesi

    Returns:
        dict: {
            'message': str (Turkce kullanici mesaji),
            'error_type': str (makine-okunabilir hata tipi),
            'is_retryable': bool,
            'details': dict (ek baglam bilgisi),
        }
    """
    error_str = str(exception)
    error_type = 'unknown'
    details = {}
    is_retryable = False

    # 1. fal_client SDK hatalarini ayristir
    #    SDK genellikle HTTP hata cevabini string olarak firlatir
    try:
        # JSON formatinda hata mesaji varsa ayristir
        if '{' in error_str and 'detail' in error_str:
            # "API error (422): [{"loc":..., "type":"content_policy_violation"...}]"
            json_start = error_str.find('[')
            json_end = error_str.rfind(']') + 1
            if json_start >= 0 and json_end > json_start:
                error_list = json.loads(error_str[json_start:json_end])
                if error_list and isinstance(error_list, list):
                    first_error = error_list[0]
                    error_type = first_error.get('type', 'unknown')
                    details = first_error.get('ctx', {})
            else:
                # {"detail": "...", "error_type": "..."} formati
                json_start = error_str.find('{')
                json_end = error_str.rfind('}') + 1
                if json_start >= 0 and json_end > json_start:
                    error_obj = json.loads(error_str[json_start:json_end])
                    error_type = error_obj.get('error_type', error_obj.get('type', 'unknown'))
                    details = error_obj.get('ctx', {})

    except (json.JSONDecodeError, IndexError, KeyError):
        pass

    # 2. HTTP durum kodu tabanli eslestirme
    if error_type == 'unknown':
        if 'failed to detect body pose' in error_str.lower():
            error_type = 'body_pose_detection_error'
        elif '422' in error_str:
            if 'content' in error_str.lower() and 'policy' in error_str.lower():
                error_type = 'content_policy_violation'
            elif 'too large' in error_str.lower():
                error_type = 'image_too_large'
            elif 'too small' in error_str.lower():
                error_type = 'image_too_small'
            else:
                error_type = 'invalid_parameters'
        elif '504' in error_str or 'timeout' in error_str.lower():
            error_type = 'generation_timeout'
        elif '429' in error_str:
            error_type = 'RATE_LIMITED'
        elif '500' in error_str or '503' in error_str:
            error_type = 'internal_server_error'

    is_retryable = error_type in RETRYABLE_ERRORS

    # Turkce mesaj olustur
    message = FAL_ERROR_MESSAGES.get(error_type, 'AI isleme hatasi: %s' % error_str[:200])

    # Baglam bilgisi varsa mesaji zenginlestir
    if error_type == 'image_too_large' and details:
        max_w = details.get('max_width', '?')
        max_h = details.get('max_height', '?')
        message = 'Gorsel cok buyuk. Maksimum boyut: %sx%s piksel.' % (max_w, max_h)
    elif error_type == 'image_too_small' and details:
        min_w = details.get('min_width', '?')
        min_h = details.get('min_height', '?')
        message = 'Gorsel cok kucuk. Minimum boyut: %sx%s piksel.' % (min_w, min_h)

    return {
        'message': message,
        'error_type': error_type,
        'is_retryable': is_retryable,
        'details': details,
    }


def format_fal_error_for_log(exception, context=''):
    """Loglama icin detayli hata bilgisi dondur."""
    parsed = parse_fal_error(exception)
    retryable_str = 'yeniden denenebilir' if parsed['is_retryable'] else 'kalici'
    return (
        'fal.ai Hata [%s] (%s) %s: %s'
        % (parsed['error_type'], retryable_str, context, parsed['message'])
    )
