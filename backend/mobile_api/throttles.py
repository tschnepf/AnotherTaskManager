from rest_framework.throttling import SimpleRateThrottle


class MobileAuthRateThrottle(SimpleRateThrottle):
    scope = "mobile_auth"

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}


class MobileSyncRateThrottle(SimpleRateThrottle):
    scope = "mobile_sync"

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}


class MobileIntentRateThrottle(SimpleRateThrottle):
    scope = "mobile_intent"

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}
