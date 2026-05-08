For Notifly GitHub PR work, the user prefers PRs to be assigned to `clix-so-bot`; after creating or updating a PR, review comments and GitHub check results should be checked, while Cloudflare Preview Worker Deploy can be treated as non-blocking unless explicitly needed.
§
User explicitly corrected that home directories such as /ubuntu/home, /home/ubuntu, or $HOME must never be deleted or destructively mutated, whether on a remote container or local system.
§
User corrected that remote/container tasks must never be executed against the local Hermes runtime by assumption; establish and verify the intended target system first, and never destructively mutate home directories.
§
User is studying Notifly infrastructure and prefers explanations in a senior-engineer mentor style: mechanism-first, practical, with mental models, concrete flows, failure modes, and verification steps.
§
User is not very familiar with AWS; when discussing infrastructure or cloud terms, they prefer brief supplemental explanations/mental models alongside the answer.