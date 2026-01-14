class TokenStorage:
    def __init__(self, access_token=None, refresh_token=None):
        self.access_token = access_token
        self.refresh_token = refresh_token

example_token_storage = TokenStorage()