# -*- coding: utf-8 -*-
"""
Google Ads API Client Service.
"""

class GoogleAdsClient:
    def __init__(self, credentials, developer_token, customer_id, manager_id=None):
        self.credentials = credentials
        self.developer_token = developer_token
        self.customer_id = customer_id
        self.manager_id = manager_id

    def get_campaigns(self):
        """
        Fetch campaigns from Google Ads.
        """
        raise NotImplementedError("Google API integration to be implemented in a later milestone.")

    def get_metrics(self, query):
        """
        Fetch metrics based on GAQL query.
        """
        raise NotImplementedError("Google API integration to be implemented in a later milestone.")

    def create_campaign(self):
        """
        Create a new campaign in Google Ads.
        """
        raise NotImplementedError("Google API integration to be implemented in a later milestone.")

    def mutate(self, operations):
        """
        Perform a bulk mutate operation.
        """
        raise NotImplementedError("Google API integration to be implemented in a later milestone.")
