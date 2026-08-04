from .services import resolve_active_company_membership


def company_context(request):
    """Expose the revalidated company context to the Tabler shell."""

    if not request.user.is_authenticated:
        return {}

    membership = getattr(request, "active_company_membership", None)
    if membership is None:
        membership = resolve_active_company_membership(request)

    return {
        "active_company": membership.company if membership else None,
        "active_company_membership": membership,
    }
