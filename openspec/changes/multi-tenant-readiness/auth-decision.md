# Decision: adopt WorkOS AuthKit for B2B login

Use **WorkOS AuthKit** for invitation/admin-provisioned login and organizations. **Clerk** is the runner-up. Do not select Supabase Auth or self-hosted Logto now. This is a design decision, not an implemented login flow; `multi-tenant-auth` owns delivery.

## Options (official sources retrieved 2026-09-27)

| Provider | Relevant evidence | Decision |
|---|---|---|
| [WorkOS AuthKit](https://workos.com/pricing) | First 1 million active users free; AuthKit includes social auth, password, magic auth, and MFA. | Selected for invitation-based B2B organizations and generous initial capacity. |
| [Clerk Organizations](https://clerk.com/docs/guides/organizations/overview), [pricing](https://clerk.com/pricing) | Organizations group users with roles and permissions; users can belong to multiple organizations. Free-plan organization limits and browser-tab token caveats need planning. 50,000 retained users per app free; Pro starts at $25/month ($20 annually); MFA is paid. | Runner-up; reevaluate if its organization UX is preferable. |
| [Supabase Auth MAU pricing](https://supabase.com/docs/guides/platform/manage-your-usage/monthly-active-users) | 50,000 MAU free; Pro includes 100,000 MAU, then $0.00325/MAU. Authentication is strong, but organization semantics would require more application work. | Not selected now. |
| [Logto RBAC](https://docs.logto.io/authorization/role-based-access-control) | Open-source/self-hostable; global and organization-level RBAC. Self-hosting adds operational ownership. | Not selected now. |

Pricing and features can change; recheck official sources before any production purchase.

## Authorization seam and migration

1. Verify provider JWT signatures, audience, issuer, expiry, and organization membership server-side. Map only verified identity and organization membership to Qora's `CallerIdentity`; map approved organization IDs to client IDs on the server.
2. Keep `CallerIdentity`, tenant-access helpers, plans, and entitlements as **application authorization**. AuthKit proves identity and organization membership only; never trust URL `clientId` or frontend claims by themselves. A superadmin can edit entitlements but has **no plan bypass** when operating on a client.
3. Retain the global API key temporarily for superadmin migration/operations. Introduce invitation-based admin-provisioned users, transition panel requests to verified user tokens, then remove `VITE_API_KEY` from browser bundles and retire the global key from browser access. Test cross-tenant and signed-URL boundaries before rollout.
