from django.http import Http404

from .models import CompanyMembership


ACTIVE_COMPANY_SESSION_KEY = "active_company_id"


def available_company_memberships(user):
    """Return active memberships whose companies can be selected."""

    if not user.is_authenticated:
        return CompanyMembership.objects.none()

    return (
        CompanyMembership.objects.filter(
            user=user,
            active=True,
            company__active=True,
        )
        .select_related("company")
        .order_by("company__name", "company__code")
    )


def clear_active_company(request) -> None:
    """Remove the company context stored in the current session."""

    request.session.pop(ACTIVE_COMPANY_SESSION_KEY, None)


def set_active_company(request, company_id: int) -> CompanyMembership:
    """Validate and store a company selected by the current user."""

    try:
        company_id = int(company_id)
    except (TypeError, ValueError) as exc:
        raise Http404("Société inaccessible.") from exc

    membership = available_company_memberships(request.user).filter(
        company_id=company_id
    ).first()
    if membership is None:
        raise Http404("Société inaccessible.")

    request.session[ACTIVE_COMPANY_SESSION_KEY] = membership.company_id
    return membership


def resolve_active_company_membership(request) -> CompanyMembership | None:
    """Revalidate the session company and auto-select a sole membership."""

    memberships = available_company_memberships(request.user)
    session_company_id = request.session.get(ACTIVE_COMPANY_SESSION_KEY)

    if session_company_id is not None:
        try:
            session_company_id = int(session_company_id)
        except (TypeError, ValueError):
            clear_active_company(request)
        else:
            membership = memberships.filter(company_id=session_company_id).first()
            if membership is not None:
                return membership
            clear_active_company(request)

    available = list(memberships[:2])
    if len(available) == 1:
        membership = available[0]
        request.session[ACTIVE_COMPANY_SESSION_KEY] = membership.company_id
        return membership

    return None
