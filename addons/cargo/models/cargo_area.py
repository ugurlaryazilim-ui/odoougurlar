# -*- coding: utf-8 -*-
"""Kargo il/ilçe kodları ve ilçe eşleme mantığı (02-tasarim 1.4.2, K-25).

Veri sağlayıcı eklentisinden gelir (ör. cargo_ups). Burada yalnız model ve eşleme kuralı vardır.
KURAL: yalnız TAM anahtar eşleşmesi. Alt dize, bulanık eşleme, posta kodu ya da varsayılan ilçe YOKTUR;
eşleşmeyen, belirsiz ya da yasak girdi boş/aday listesi olarak döner, çağıran açık hata verir.
"""
import re
import unicodedata

from odoo import api, fields, models

# NEDEN: Türkçe harfler büyük harfe çevrilmeden ÖNCE ASCII'ye çevrilir; aksi halde
# 'i'.upper() -> 'I' ama 'ı'/'İ' ayrımı ve birleşik noktalı i (i + U+0307) yanlış anahtar üretir.
_TR_TO_ASCII = str.maketrans('İıŞşÇçĞğÜüÖö', 'IISSCCGGUUOO')
# Girdi metnini parçalayan ayraçlar. BOŞLUK ayraç DEĞİLDİR: "Merkez Efendi" MERKEZ olmamalı.
_INPUT_SPLIT = re.compile(r'[/,\-()\\]')
# Kayıt adını düzey-2 parçalarına bölen ayraçlar (ör. 'KALE (DEMRE)', 'A/B').
_NAME_SPLIT = re.compile(r'[()/]')
_MIN_PART_LEN = 3


class CargoArea(models.Model):
    _name = 'cargo.area'
    _description = 'Kargo il/ilçe kodu'
    _order = 'provider, city_code, name'

    # NEDEN: provider Char; sağlayıcı = delivery.carrier.delivery_type değeri (selection_add ile
    # eklendiği için çekirdek tanımaz). Aynı ilçe iki sağlayıcıda ayrı kod taşıyabilir.
    provider = fields.Char(string='Sağlayıcı', required=True, index=True)
    state_id = fields.Many2one('res.country.state', string='İl', required=True, index=True, ondelete='restrict')
    name = fields.Char(string='İlçe (sağlayıcı adı)', required=True)
    name_key = fields.Char(string='Ad anahtarı', compute='_compute_name_key', store=True, index=True)
    alias_names = fields.Char(
        string='Diğer adlar',
        help='Virgülle ayrılmış. Adresteki ilçe yazımı sağlayıcı listesinden farklıysa (ör. eski ad) buraya '
             'eklenir; yalnız tam yazım eşleşir.')
    match_keys = fields.Char(string='Eşleme anahtarları', compute='_compute_match_keys', store=True)
    city_code = fields.Integer(string='İl kodu')
    area_code = fields.Integer(string='İlçe kodu', required=True)

    _provider_area_code_uniq = models.Constraint(
        'UNIQUE(provider, area_code)', 'Aynı sağlayıcıda ilçe kodu tekrar edemez.')

    # NEDEN: 6360 sayılı Kanun (2012) ile büyükşehir olan 30 ilin plaka kodları. Büyükşehirde il merkezi
    # tek ilçe değildir; "Merkez" yazan adres hangi merkez ilçe olduğunu söylemez. Bu bir ülke bilgisidir,
    # sağlayıcı bilgisi değildir.
    # DIKKAT: Yeni büyükşehir kanunla eklenirse buraya eklenir; yanlış çıkarma "Merkez" adreslerini sessizce
    # tek kayda bağlar (yanlış ilçeye gönderi).
    _TR_METROPOLITAN_STATE_CODES = frozenset((
        '01', '06', '07', '09', '10', '16', '20', '21', '25', '26', '27', '31', '33', '34', '35', '38',
        '41', '42', '44', '45', '46', '47', '48', '52', '54', '55', '59', '61', '63', '65'))

    # ----- normalize ve anahtarlar -----
    @api.model
    def _normalize(self, text):
        """TR->ASCII, NFKD (şapka/birleşik nokta atılır), büyük harf, yalnız harf/rakam."""
        if not text:
            return ''
        text = unicodedata.normalize('NFKD', str(text).translate(_TR_TO_ASCII))
        return ''.join(ch for ch in text.upper() if ch.isalnum() and not unicodedata.combining(ch))

    @api.model
    def _alias_list(self, alias_names):
        return [part.strip() for part in (alias_names or '').split(',') if part.strip()]

    @api.depends('name')
    def _compute_name_key(self):
        for area in self:
            area.name_key = self._normalize(area.name)

    @api.depends('name', 'alias_names')
    def _compute_match_keys(self):
        for area in self:
            level1 = {self._normalize(area.name)}
            level1.update(self._normalize(alias) for alias in self._alias_list(area.alias_names))
            level2 = set()
            parts = _NAME_SPLIT.split(area.name or '')
            if len(parts) > 1:      # ayraç yoksa düzey 2 düzey 1'in kopyası olur
                level2.update(key for key in map(self._normalize, parts) if len(key) >= _MIN_PART_LEN)
            keys = ['L1:%s' % key for key in sorted(level1) if key]
            keys += ['L2:%s' % key for key in sorted(level2)]
            # Boşlukla ayrılmış belirteçler; anahtarlar yalnız harf/rakam olduğundan belirsizlik yoktur.
            area.match_keys = ' '.join(keys)

    # ----- eşleme -----
    @api.model
    def _input_key_tiers(self, state, district):
        """Girdi anahtarlarını öncelik sırasıyla (tam, il atılmış, ayraçlı parçalar) gruplar; yasaklar atılır."""
        full = self._normalize(district)
        if not full:
            return []
        state_key = self._normalize(state.name)
        metropolitan = state.code in self._TR_METROPOLITAN_STATE_CODES
        # DIKKAT: yasak girdiler hiçbir koşulda kayda eşlenmez (shopicargo'daki sessiz yanlış ilçe kaynağı):
        # il adı ve büyükşehirde 'Merkez' / '<İl>Merkez' / 'Merkez<İl>'.
        forbidden = {state_key}
        if metropolitan:
            forbidden.update(('MERKEZ', state_key + 'MERKEZ', 'MERKEZ' + state_key))

        stripped = []
        if state_key and full != state_key:
            if full.startswith(state_key):
                stripped.append(full[len(state_key):])
            if full.endswith(state_key):
                stripped.append(full[:-len(state_key)])
        parts = [self._normalize(part) for part in _INPUT_SPLIT.split(district)]

        tiers = []
        seen = set()
        # NEDEN: tasarım "tam anahtar + parçalar" birleşik kümesini anlatır; ancak 'Kale (Demre)' hem
        # 'KALE (DEMRE)' hem düz 'DEMRE' kaydına denk gelip sebepsiz belirsiz olurdu. Bu yüzden tam anahtar
        # önce denenir, il atılmış hali sonra, ayraçlı parçalar en son (ilk bulunan aşama kazanır).
        for tier in ([full], [key for key in stripped if len(key) >= _MIN_PART_LEN],
                     [key for key in parts if len(key) >= _MIN_PART_LEN]):
            keys = []
            for key in tier:
                if key and key not in forbidden and key not in seen:
                    seen.add(key)
                    keys.append(key)
            if keys:
                tiers.append(keys)
        return tiers

    @api.model
    def _match_candidates(self, provider, state, district):
        """Aday kayıtlar: 0 (eşleşmedi/yasak), 1 (kesin) ya da çok (belirsiz). Sessiz seçim yapılmaz."""
        if not provider or not state or state.country_id.code != 'TR':
            return self.browse()
        tiers = self._input_key_tiers(state, district)
        if not tiers:
            return self.browse()
        # NEDEN: il başına en çok ~40 kayıt var; Python süzgeci belirteç sınırını (KALE ≠ PAMUKKALE)
        # LIKE kaçışlarına bağlı kalmadan garanti eder.
        areas = self.search([('provider', '=', provider), ('state_id', '=', state.id)])
        tokens = {area.id: set((area.match_keys or '').split()) for area in areas}
        for keys in tiers:
            for level in ('L1', 'L2'):
                wanted = {'%s:%s' % (level, key) for key in keys}
                found = areas.filtered(lambda area: tokens[area.id] & wanted)
                if found:
                    return found
        return self.browse()

    @api.model
    def _match(self, provider, state, district):
        """Yalnız tek aday varsa o kayıt, aksi halde boş."""
        found = self._match_candidates(provider, state, district)
        return found if len(found) == 1 else self.browse()
