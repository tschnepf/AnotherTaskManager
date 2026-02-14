# RBAC Matrix

## Roles
- owner
- admin
- member

## Core Rules
- owner: full organization control.
- admin: manage organization resources except owner transfer/removal.
- member: limited to own and assigned task operations.

## Assignment Rules
- owner/admin can assign tasks to any same-organization user.
- member can assign tasks only to self.
- assignment across organizations is rejected.
