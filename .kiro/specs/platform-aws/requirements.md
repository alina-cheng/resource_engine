# Requirements: AWS platform and delivery

Traces to: BR-13

## User story
As an operator, I deploy and run the system on AWS with cost control and visibility.

## Acceptance criteria (EARS)
1. THE SYSTEM SHALL deploy through GitHub Actions using OIDC credentials and Terraform.
2. THE SYSTEM SHALL run the web tier on ECS Fargate behind an ALB with the database in private subnets.
3. THE SYSTEM SHALL run imports and maintenance as scheduled one-off tasks from the same image.
4. THE SYSTEM SHALL keep secrets in Secrets Manager and encrypt data at rest.
5. THE SYSTEM SHALL also run locally with one command.
6. WHEN an AWS web request starts a long job THE SYSTEM SHALL enqueue it and return a persisted job ID, SHALL record the task ARN/start failure, and SHALL expose authenticated admin status polling.
7. WHEN Cognito requests a first-password or supported MFA challenge THE SYSTEM SHALL complete it through a short-lived signed challenge session before issuing an application session.
8. WHEN using an expiring workshop account THE SYSTEM SHALL use the organizer's allowed region/services and temporary credentials, keep production OIDC separate, and document data export/redeployment before expiry.
9. THE SYSTEM SHALL use the committed uv.lock in local development, CI and container dependency installation.
