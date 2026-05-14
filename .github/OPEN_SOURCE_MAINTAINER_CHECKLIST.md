# Open Source Maintainer Checklist

This checklist tracks security and governance settings that must be configured
in GitHub UI or org settings (not in repository files).

## Branch protection and merge safety (`main`)

- [ ] Require pull requests before merging
- [ ] Require at least 1 approving review
- [ ] Dismiss stale approvals when new commits are pushed
- [ ] Require review from Code Owners
- [ ] Require all review conversations to be resolved
- [ ] Require status checks to pass before merge
- [ ] Restrict who can push to `main` (maintainers only)
- [ ] Require signed commits
- [ ] Disable force pushes
- [ ] Disable branch deletion

## Required status checks

- [ ] `Test (Python 3.10)`
- [ ] `Test (Python 3.11)`
- [ ] `Test (Python 3.12)`
- [ ] `Scan for secrets`
- [ ] `Analyze (Python)`

## GitHub Actions security

- [ ] Require approval for first-time/outside contributor workflow runs
- [ ] Confirm secrets are not exposed to fork pull requests
- [ ] Keep workflow permissions least-privilege over time
- [ ] Keep third-party actions pinned to commit SHAs

## Security features

- [ ] Enable Dependabot alerts
- [ ] Enable Dependabot security updates
- [ ] Enable secret scanning
- [ ] Enable secret scanning push protection

## Organization controls

- [ ] Enforce org-wide two-factor authentication (2FA)
