# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request

class LegalPagesController(http.Controller):

    @http.route('/privacy', type='http', auth='public', website=True)
    def privacy_policy(self, **kw):
        return request.render('social_media_ai_manager.page_privacy_policy', {})

    @http.route('/terms', type='http', auth='public', website=True)
    def terms_of_service(self, **kw):
        return request.render('social_media_ai_manager.page_terms_of_service', {})

    @http.route('/data-deletion', type='http', auth='public', website=True)
    def data_deletion(self, **kw):
        return request.render('social_media_ai_manager.page_data_deletion', {})
