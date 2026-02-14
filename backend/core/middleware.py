class TenantContextMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.user_id = None
        request.organization_id = None
        request.role = None
        if getattr(request, "user", None) and request.user.is_authenticated:
            request.user_id = str(request.user.id)
            request.organization_id = (
                str(request.user.organization_id) if request.user.organization_id else None
            )
            request.role = request.user.role
        return self.get_response(request)
