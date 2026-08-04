from django.db import transaction
from django.http import Http404

from .models import CompanyMembership


ACTIVE_COMPANY_SESSION_KEY = "active_company_id"


class LastActiveAdministratorError(Exception):
    """Raised when an operation would leave a company without an admin."""


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


def _ensure_admin_will_remain(membership, *, role=None, active=None) -> None:
    resulting_role = membership.role if role is None else role
    resulting_active = membership.active if active is None else active
    loses_admin_status = (
        membership.active
        and membership.role == CompanyMembership.Role.ADMIN
        and (
            not resulting_active
            or resulting_role != CompanyMembership.Role.ADMIN
        )
    )
    if not loses_admin_status:
        return

    active_admin_ids = list(
        CompanyMembership.objects.select_for_update()
        .filter(
            company_id=membership.company_id,
            role=CompanyMembership.Role.ADMIN,
            active=True,
        )
        .order_by("pk")
        .values_list("pk", flat=True)
    )
    if active_admin_ids == [membership.pk]:
        raise LastActiveAdministratorError(
            CompanyMembership.LAST_ACTIVE_ADMIN_ERROR
        )


@transaction.atomic
def update_company_membership(
    *,
    membership_id: int,
    company_id: int,
    role: str,
    active: bool,
) -> CompanyMembership:
    """Update a scoped membership while preserving an active administrator."""

    if role not in CompanyMembership.Role.values:
        raise ValueError("Rôle d’appartenance invalide.")

    membership = CompanyMembership.objects.select_for_update().get(
        pk=membership_id,
        company_id=company_id,
    )
    _ensure_admin_will_remain(membership, role=role, active=active)
    membership.role = role
    membership.active = active
    membership.full_clean()
    membership.save(update_fields=("role", "active", "updated_at"))
    return membership


@transaction.atomic
def delete_company_membership(
    *,
    membership_id: int,
    company_id: int,
) -> None:
    """Delete a scoped membership while preserving an active administrator."""

    membership = CompanyMembership.objects.select_for_update().get(
        pk=membership_id,
        company_id=company_id,
    )
    _ensure_admin_will_remain(
        membership,
        role=membership.role,
        active=False,
    )
    membership.delete()
