from core.models import User


def is_owner(user: User) -> bool:
    return getattr(user, "role", None) == User.Role.OWNER


def is_admin(user: User) -> bool:
    return getattr(user, "role", None) == User.Role.ADMIN


def is_member(user: User) -> bool:
    return getattr(user, "role", None) == User.Role.MEMBER


def can_manage_org_resources(user: User) -> bool:
    return is_owner(user) or is_admin(user)


def can_assign_to_user(actor: User, assignee: User) -> bool:
    if actor.organization_id != assignee.organization_id:
        return False
    if can_manage_org_resources(actor):
        return True
    return actor.id == assignee.id
