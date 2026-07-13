# -*- coding: utf-8 -*-
from odoo import models, fields, api
from datetime import datetime

class SocialMediaPost(models.Model):
    _name = 'social.media.post'
    _description = 'Social Media Post'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(string="Post Title", required=True)
    message = fields.Text(string="Post Message", required=True)
    
    # Scheduling
    post_type = fields.Selection([
        ('post', 'Gönderi (Akış)'),
        ('story', 'Hikaye (Story)'),
        ('reels', 'Reels (Kısa Video)')
    ], string="Gönderi Tipi", default='post', required=True)
    scheduled_date = fields.Datetime(string="Scheduled Date", default=fields.Datetime.now, required=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('scheduled', 'Scheduled'),
        ('posting', 'Posting...'),
        ('posted', 'Posted'),
        ('error', 'Error')
    ], string="Status", default='draft', tracking=True)
    
    # YouTube Specific
    youtube_privacy = fields.Selection([
        ('public', 'Herkese Açık (Public)'),
        ('unlisted', 'Liste Dışı (Unlisted)'),
        ('private', 'Gizli (Private)')
    ], string="YouTube Gizlilik", default='public', tracking=True)
    youtube_tags = fields.Char(string="YouTube Etiketleri", help="Virgülle ayırarak yazın (Örn: moda,giyim,trend)")

    # Platforms
    account_ids = fields.Many2many('social.media.account', string="Publish to Accounts", required=True)
    
    # Media
    image_ids = fields.Many2many('ir.attachment', string="Images/Videos")

    # Products (AI context)
    product_tmpl_ids = fields.Many2many('product.template', string="Posttaki Ürünler (AI İçin)", help="Bu gönderiye yorum geldiğinde yapay zeka bu ürünlerin stok ve fiyat bilgilerini kullanır.")

    post_line_ids = fields.One2many('social.media.post.line', 'post_id', string="Platform Statuses")

    def action_schedule(self):
        for rec in self:
            rec.state = 'scheduled'
            # Make images public so Facebook/Instagram can download them
            if rec.image_ids:
                rec.image_ids.sudo().write({'public': True})
            # Create lines
            for account in rec.account_ids:
                self.env['social.media.post.line'].create({
                    'post_id': rec.id,
                    'account_id': account.id,
                    'state': 'pending'
                })

    def action_draft(self):
        self.write({'state': 'draft'})
        self.post_line_ids.unlink()

    @api.model
    def _cron_publish_scheduled_posts(self):
        """ Cron job to publish posts whose time has come """
        
        # Check if automated posting is enabled in settings
        enable_posting = self.env['ir.config_parameter'].sudo().get_param('social_media_ai.enable_posting', 'True')
        if enable_posting != 'True':
            return
            
        posts = self.search([
            ('state', '=', 'scheduled'),
            ('scheduled_date', '<=', fields.Datetime.now())
        ])
        for post in posts:
            post.state = 'posting'
            self.env.cr.commit()
            all_success = True
            
            for line in post.post_line_ids.filtered(lambda l: l.state == 'pending'):
                # Call specific API logic per platform
                success = line._publish_to_platform()
                if not success:
                    all_success = False

            post.state = 'posted' if all_success else 'error'
            self.env.cr.commit()


class SocialMediaPostLine(models.Model):
    _name = 'social.media.post.line'
    _description = 'Post Line Status'

    post_id = fields.Many2one('social.media.post', required=True, ondelete='cascade')
    account_id = fields.Many2one('social.media.account', required=True)
    platform = fields.Selection(related='account_id.platform')
    
    state = fields.Selection([
        ('pending', 'Pending'),
        ('success', 'Success'),
        ('error', 'Error')
    ], default='pending')
    
    error_message = fields.Text(string="Error Details")
    platform_post_id = fields.Char(string="Platform Post ID")

    def _publish_to_platform(self):
        """ Real API logic for Meta """
        self.ensure_one()
        try:
            if self.platform == 'facebook':
                return self._publish_to_facebook()
            elif self.platform == 'instagram':
                return self._publish_to_instagram()
            elif self.platform == 'youtube':
                return self._publish_to_youtube()
            else:
                self.state = 'success'
                self.platform_post_id = "DUMMY_ID"
                return True
        except Exception as e:
            self.state = 'error'
            self.error_message = str(e)
            return False

    def _publish_to_facebook(self):
        import requests
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        page_id = self.account_id.meta_page_id
        token = self.account_id.api_token
        
        if not page_id or not token:
            raise ValueError("Facebook Page ID or Token is missing.")

        images = self.post_id.image_ids
        message = self.post_id.message

        if not images:
            if self.post_id.post_type != 'post':
                raise ValueError("Hikaye (Story) veya Reels paylaşımları için en az 1 görsel/video gereklidir.")
            # Text only post
            url = f"https://graph.facebook.com/v19.0/{page_id}/feed"
            payload = {'message': message, 'access_token': token}
            res = requests.post(url, data=payload).json()
            if 'error' in res:
                raise ValueError(res['error']['message'])
            self.platform_post_id = res.get('id')
        elif self.post_id.post_type == 'story':
            is_video = images[0].mimetype and images[0].mimetype.startswith('video')
            route = "content" if is_video else "image"
            media_url = f"{base_url}/web/{route}/{images[0].id}"
            
            if is_video:
                # 3-step Resumable Upload for Facebook Video Stories
                start_url = f"https://graph.facebook.com/v19.0/{page_id}/video_stories"
                start_payload = {'upload_phase': 'start', 'access_token': token}
                start_res = requests.post(start_url, data=start_payload).json()
                if 'error' in start_res:
                    raise ValueError("Upload Phase 1 Error: " + start_res['error']['message'])
                
                video_id = start_res.get('video_id')
                upload_url = start_res.get('upload_url')
                
                # Phase 2: Transfer (pass file_url in headers for rupload.facebook.com)
                headers = {'Authorization': f'OAuth {token}', 'file_url': media_url}
                transfer_res = requests.post(upload_url, headers=headers).json()
                if 'error' in transfer_res:
                    raise ValueError("Upload Phase 2 Error: " + transfer_res['error']['message'])
                
                # Phase 3: Finish
                finish_payload = {'upload_phase': 'finish', 'video_id': video_id, 'access_token': token}
                finish_res = requests.post(start_url, data=finish_payload).json()
                if 'error' in finish_res:
                    raise ValueError("Upload Phase 3 Error: " + finish_res['error']['message'])
                    
                self.platform_post_id = finish_res.get('id') or video_id
            else:
                url = f"https://graph.facebook.com/v19.0/{page_id}/photo_stories"
                payload = {'url': media_url, 'access_token': token}
                res = requests.post(url, data=payload).json()
                if 'error' in res:
                    raise ValueError(res['error']['message'])
                self.platform_post_id = res.get('post_id') or res.get('id')
        elif self.post_id.post_type == 'reels':
            url = f"https://graph.facebook.com/v19.0/{page_id}/videos"
            media_url = f"{base_url}/web/content/{images[0].id}"
            payload = {'file_url': media_url, 'description': message, 'access_token': token}
            res = requests.post(url, data=payload).json()
            if 'error' in res:
                raise ValueError(res['error']['message'])
            self.platform_post_id = res.get('id')
        elif len(images) == 1:
            # Single Image or Video
            is_video = images[0].mimetype and images[0].mimetype.startswith('video')
            route = "content" if is_video else "image"
            media_url = f"{base_url}/web/{route}/{images[0].id}"
            
            if is_video:
                url = f"https://graph.facebook.com/v19.0/{page_id}/videos"
                payload = {'file_url': media_url, 'description': message, 'access_token': token}
            else:
                url = f"https://graph.facebook.com/v19.0/{page_id}/photos"
                payload = {'url': media_url, 'message': message, 'access_token': token}
                
            res = requests.post(url, data=payload).json()
            if 'error' in res:
                raise ValueError(res['error']['message'])
            self.platform_post_id = res.get('post_id') or res.get('id')
        else:
            # Carousel / Multiple Images
            attached_media = []
            for img in images:
                url = f"https://graph.facebook.com/v19.0/{page_id}/photos"
                img_url = f"{base_url}/web/image/{img.id}"
                payload = {'url': img_url, 'published': 'false', 'access_token': token}
                res = requests.post(url, data=payload).json()
                if 'error' in res:
                    raise ValueError(res['error']['message'])
                attached_media.append({'media_fbid': res.get('id')})

            # Publish the multi-photo post
            feed_url = f"https://graph.facebook.com/v19.0/{page_id}/feed"
            import json
            payload = {
                'message': message,
                'attached_media': json.dumps(attached_media),
                'access_token': token
            }
            res2 = requests.post(feed_url, data=payload).json()
            if 'error' in res2:
                raise ValueError(res2['error']['message'])
            self.platform_post_id = res2.get('id')

        self.state = 'success'
        return True

    def _publish_to_instagram(self):
        import requests
        import time
        import urllib.parse
        
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        ig_id = self.account_id.meta_ig_id
        token = self.account_id.api_token
        
        if not ig_id or not token:
            raise ValueError("Instagram Account ID or Token is missing.")

        images = self.post_id.image_ids
        message = self.post_id.message

        if not images:
            raise ValueError("Instagram requires at least one image/video.")

        container_ids = []
        is_video_post = False
        
        for img in images:
            is_video = img.mimetype and img.mimetype.startswith('video')
            route = "content" if is_video else "image"
            
            # Add a dummy extension to the URL because Instagram API requires it
            ext = "/video.mp4" if is_video else "/image.jpg"
            img_url = f"{base_url}/web/{route}/{img.id}{ext}"
            encoded_url = urllib.parse.quote(img_url, safe='')
            
            if is_video:
                is_video_post = True
                media_param = f"video_url={encoded_url}"
            else:
                media_param = f"image_url={encoded_url}"

            # Is carousel item?
            is_carousel = "true" if len(images) > 1 and self.post_id.post_type == 'post' else "false"
            
            cont_url = f"https://graph.facebook.com/v19.0/{ig_id}/media?{media_param}&is_carousel_item={is_carousel}&access_token={token}"
            
            if self.post_id.post_type == 'story':
                cont_url = f"https://graph.facebook.com/v19.0/{ig_id}/media?{media_param}&media_type=STORIES&access_token={token}"
            elif self.post_id.post_type == 'reels':
                cont_url = f"https://graph.facebook.com/v19.0/{ig_id}/media?{media_param}&media_type=REELS&access_token={token}"
                
            if len(images) == 1 and self.post_id.post_type != 'story':
                 cont_url += f"&caption={urllib.parse.quote(message, safe='')}"
                 
            res = requests.post(cont_url).json()
            if 'error' in res:
                raise ValueError(res['error']['message'])
            container_ids.append(res.get('id'))

        publish_container_id = container_ids[0]

        if len(images) > 1:
            # Create Carousel Container
            import json
            children = "%2C".join(container_ids)
            carousel_url = f"https://graph.facebook.com/v19.0/{ig_id}/media?media_type=CAROUSEL&children={children}&caption={urllib.parse.quote(message, safe='')}&access_token={token}"
            res2 = requests.post(carousel_url).json()
            if 'error' in res2:
                raise ValueError(res2['error']['message'])
            publish_container_id = res2.get('id')

        # Publish the container (with retry for videos)
        pub_url = f"https://graph.facebook.com/v19.0/{ig_id}/media_publish?creation_id={publish_container_id}&access_token={token}"
        
        max_retries = 18 if is_video_post else 1
        wait_time = 10  # wait 10 seconds between retries for video processing
        
        for attempt in range(max_retries):
            if is_video_post and attempt > 0:
                time.sleep(wait_time)
                
            res3 = requests.post(pub_url).json()
            
            if 'error' not in res3:
                self.platform_post_id = res3.get('id')
                self.state = 'success'
                return True
                
            error_msg = res3['error']['message']
            # If it's processing, Instagram returns specific errors (like Media ID is not available).
            # We retry if we have attempts left.
            if attempt == max_retries - 1:
                raise ValueError(f"Publish Error (Attempt {attempt+1}): {error_msg}")
        
        return False

    def _publish_to_youtube(self):
        self.account_id._refresh_youtube_token()
        token = self.account_id.api_token
        
        if not token:
            raise ValueError("YouTube API Token is missing. Please re-authenticate.")

        images = self.post_id.image_ids
        if not images:
            raise ValueError("YouTube platform requires a video attachment.")
            
        attachment = images[0]
        if not attachment.mimetype or not attachment.mimetype.startswith('video'):
            raise ValueError("YouTube only supports video uploads.")

        import requests
        import base64
        
        video_data = base64.b64decode(attachment.datas)
        
        url = 'https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status'
        headers = {
            'Authorization': f'Bearer {token}',
            'X-Upload-Content-Length': str(len(video_data)),
            'X-Upload-Content-Type': attachment.mimetype,
            'Content-Type': 'application/json; charset=UTF-8'
        }
        
        is_shorts = self.post_id.post_type in ('story', 'reels')
        tags = ['shorts'] if is_shorts else []
        title = self.post_id.name
        description = self.post_id.message
        
        if is_shorts and '#shorts' not in description.lower():
            description += "\n\n#shorts"
            
        if self.post_id.youtube_tags:
            custom_tags = [t.strip() for t in self.post_id.youtube_tags.split(',') if t.strip()]
            tags.extend(custom_tags)
            
        privacy_status = self.post_id.youtube_privacy or 'public'
            
        metadata = {
            "snippet": {
                "title": title,
                "description": description,
                "tags": tags,
                "categoryId": "22" # 22 = People & Blogs
            },
            "status": {
                "privacyStatus": privacy_status,
                "selfDeclaredMadeForKids": False
            }
        }
        
        # Step 1: Start Resumable Upload
        res = requests.post(url, headers=headers, json=metadata, timeout=20)
        if not res.ok:
            raise ValueError(f"YouTube Upload Init Error: {res.status_code} - {res.text}")
            
        upload_url = res.headers.get('Location')
        if not upload_url:
            raise ValueError("YouTube did not return an upload URL")
            
        # Step 2: Upload Data
        headers2 = {
            'Authorization': f'Bearer {token}',
            'Content-Type': attachment.mimetype
        }
        res2 = requests.put(upload_url, headers=headers2, data=video_data, timeout=300) # Allow 5 minutes for upload
        if not res2.ok:
            raise ValueError(f"YouTube Upload Error: {res2.status_code} - {res2.text}")
            
        self.platform_post_id = res2.json().get('id')
        self.state = 'success'
        return True
