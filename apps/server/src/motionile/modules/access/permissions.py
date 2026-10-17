from dataclasses import dataclass


@dataclass(frozen=True)
class PermissionDefinition:
    key: str
    description: str


PERMISSIONS = (
    PermissionDefinition("users.read", "Read users and their administrative details"),
    PermissionDefinition("users.manage", "Suspend, restore, and sign users out"),
    PermissionDefinition("users.roles.assign", "Assign roles to users"),
    PermissionDefinition("roles.read", "Read roles and permissions"),
    PermissionDefinition("roles.manage", "Create, edit, and delete roles"),
    PermissionDefinition("audit.read", "Read audit events"),
    PermissionDefinition("analytics.read", "Read administrative analytics"),
    PermissionDefinition("settings.read", "Read private system settings"),
    PermissionDefinition("settings.manage", "Update system settings"),
    PermissionDefinition("flags.manage", "Manage feature flags"),
    PermissionDefinition("catalog.manage", "Manage the catalog"),
    PermissionDefinition("billing.read", "Read products, orders, payments, subscriptions, refunds and webhook events"),
    PermissionDefinition("billing.products.manage", "Create, edit, version and activate products"),
    PermissionDefinition("billing.refunds.create", "Refund payments"),
    PermissionDefinition("billing.credits.adjust", "Grant or remove credits for a user"),
    PermissionDefinition("billing.webhooks.manage", "Replay and inspect webhook events"),
)

PERMISSION_KEYS = frozenset(definition.key for definition in PERMISSIONS)
