# Requirements: Help seeker chat and profile

Traces to: BR-8

## User story
As a help seeker, I describe my need in plain words, create a profile when needed, and send a request to the right provider.

## Acceptance criteria (EARS)
1. WHEN a visitor asks about One Degree THE SYSTEM SHALL answer without requiring login.
2. WHEN a visitor asks for a service and is not signed in THE SYSTEM SHALL ask them to create a profile or log in and SHALL NOT return provider details.
3. WHEN a visitor signs up from the chat THE SYSTEM SHALL continue with the need they started with.
4. WHEN a signed-in seeker asks for a service THE SYSTEM SHALL return up to three different matching services, nearest first when a ZIP code is known.
5. WHEN a seeker chooses a provider THE SYSTEM SHALL ask for sharing consent if not yet given and SHALL create the request only after confirmation.
6. IF a message indicates danger or self-harm THEN THE SYSTEM SHALL show 911, 988 and 211 information first.
