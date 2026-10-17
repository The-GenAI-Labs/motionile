# Bootstrap the first super administrator

Use this procedure once after Phase 6 reaches an environment, or to recover an environment that has no usable `super_admin`. The target account must already exist and have a verified email address or phone number. The command records a `system` audit actor and refuses an unknown user or role.

## Connect to the environment

Find the instance and open a Session Manager shell as described in [Access and operations](access-and-operations.md), then switch to the deploy user.

```bash
sudo -iu deploy
```

Confirm the deployed application is healthy before changing access:

```bash
/srv/motionile/bundle/scripts/compose.sh ps
/srv/motionile/bundle/scripts/compose.sh exec -T api python -m motionile.scripts.grant_role --help
```

## Grant the role

Use the account's normalized email address or E.164 phone number. Quote phone numbers so the leading plus sign is preserved.

```bash
/srv/motionile/bundle/scripts/compose.sh exec -T api python -m motionile.scripts.grant_role \
  --identifier '<EMAIL_OR_PHONE>' \
  --role super_admin
```

Expected result: the command identifies the account and reports that `super_admin` was granted, or that it was already assigned. It never prints credentials, session tokens or contact verification data.

The account's existing session receives the new effective permissions on its next authorized request because the live authorization cache is invalidated after the transaction commits. Reload `/admin` to enter the console.

## Verify and record

Sign in as the account and confirm `/admin` loads. Open the audit log and verify the role grant has actor type `system`, target type `user`, the target account ID and the `super_admin` role in its metadata. Record the operator, environment, reason and audit entry ID in the change ticket.

If the command reports that no matching verified account exists, complete registration and contact verification for the intended account, then run the command again. Do not edit the `user_roles` table directly because that bypasses escalation checks, audit recording and cache invalidation.
