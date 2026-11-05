# AWS Workshop Studio deployment

This path is for the event account reached through `https://catalog.us-east-1.prod.workshops.aws/join`. It does not turn an expiring workshop account into permanent hosting. Exact allowed services, regions and expiry are controlled by the event organizer.

User-provided event details: **OneDegree - AWS Breaking Barriers 2026**, console region **us-west-2**, total account spend cap **$500**. Budget, service restrictions and security guardrails are enforced by the organizer and cannot be changed by participants. The copied countdown was “1 day 19 hours 47 minutes”; obtain the actual event-end timestamp rather than treating that snapshot as a live timer. Detailed allowed services/security constraints remain to be supplied or read from the event.

## Login from this Mac

1. Open the join link, choose the offered login method (often Email one-time password), enter your email code yourself, then enter the event access code supplied by the organizer. Accept the event terms yourself.
2. From the event dashboard choose **Open AWS console**. Use the region shown by the event; `us-east-1` in the join-page URL does not establish which region your resources may use.
3. On the dashboard choose **Get AWS CLI credentials** / **AWS CLI credentials**. Workshop temporary credentials have three parts: access key ID, secret access key and session token. All three are required. Do not send them in chat or commit them.
4. Run `uv run python scripts/configure_workshop_profile.py` in FINAL. Enter the three values in its hidden terminal prompts, plus the event region. It saves the named `workshop` profile under your user `.aws` files with private permissions; no credential is printed.
5. Verify `aws sts get-caller-identity --profile workshop`. Tell the agent the profile name, region, event end time and accessible services, not the keys.

Credentials can expire before the event ends. Return to the event dashboard for fresh values and rerun the helper when STS reports expiration. `aws login` is an alternative console-login facility for suitable accounts; the workshop dashboard's CLI credentials are the direct event-provided method and do not require assuming that extra sign-in permissions are enabled.

## Deployment and lifetime

- Use the existing Terraform/ECS/Aurora stack only after checking the workshop role's permissions and available services. Creating GitHub OIDC/IAM roles or Aurora may be restricted. Report the exact denied API if that happens; do not silently switch to a different product or bypass restrictions.
- Keep production GitHub OIDC configuration separate from workshop temporary credentials. A session token is not a durable CI authentication mechanism.
- The GitHub repository and `uv.lock` preserve source and dependencies. A local PostgreSQL volume preserves local demo state. Resources, ECR images, S3 objects, database contents and Terraform state stored only inside the workshop account may be lost on account cleanup.
- Before the event ends, export required demo data and evidence to ignored local storage, record image SHA and deployment parameters, and preserve instructions to redeploy into a durable account. Do not depend on the workshop URL or Aurora endpoint remaining available.
- Use synthetic or mocked data for the event, as required by the existing BRD and workshop terms. A real PostgreSQL/AWS integration test can use simulated source records; label data provenance honestly.

Official references: [AWS-hosted workshop account access](https://catalog.us-east-1.prod.workshops.aws/v2/workshops/63320e83-6abc-493d-83d8-f822584fb3cb/en-US/getting-started/aws-hosted), [AWS EKS workshop event login](https://www.eksworkshop.com/docs/introduction/setup/aws-event).
