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
