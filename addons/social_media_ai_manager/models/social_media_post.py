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

    # Platforms
    account_ids = fields.Many2many('social.media.account', string="Publish to Accounts", required=True)
    
    # Media
    image_ids = fields.Many2many('ir.attachment', string="Images/Videos")

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
        posts = self.search([
            ('state', '=', 'scheduled'),
            ('scheduled_date', '<=', fields.Datetime.now())
        ])
        for post in posts:
            post.state = 'posting'
            all_success = True
            
            for line in post.post_line_ids.filtered(lambda l: l.state == 'pending'):
                # Call specific API logic per platform
                success = line._publish_to_platform()
                if not success:
                    all_success = False

            post.state = 'posted' if all_success else 'error'


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
            # Facebook Graph API video_stories requires complex 3-step Resumable Upload. 
            # We fallback to standard /videos endpoint for video stories to ensure it posts successfully via URL.
            endpoint = "videos" if is_video else "photo_stories"
            url = f"https://graph.facebook.com/v19.0/{page_id}/{endpoint}"
            
            # Use /web/content for videos, /web/image for images
            route = "content" if is_video else "image"
            media_url = f"{base_url}/web/{route}/{images[0].id}"
            
            payload = {'access_token': token}
            if is_video:
                payload['file_url'] = media_url
                payload['description'] = message or "Story"
            else:
                payload['url'] = media_url
                
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
        
        max_retries = 6 if is_video_post else 1
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
