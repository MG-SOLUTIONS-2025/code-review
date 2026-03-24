# GitHub / Gitea CLI Reference for Autofix

This file provides the exact API queries needed to fetch unresolved review threads for the autofix workflow. The GitHub REST API does not expose unresolved review thread state — GraphQL is required.

## Fetch unresolved review threads (GitHub GraphQL)

```bash
gh api graphql -f query='
  query($owner: String!, $repo: String!, $pr: Int!) {
    repository(owner: $owner, name: $repo) {
      pullRequest(number: $pr) {
        reviewThreads(first: 100) {
          nodes {
            isResolved
            comments(first: 10) {
              nodes {
                id
                body
                author { login }
                createdAt
                path
                line
              }
            }
          }
        }
      }
    }
  }
' -f owner=OWNER -f repo=REPO -F pr=PR_NUMBER
```

Filter the result to `nodes` where `isResolved == false`, then look for comments whose `body` contains `🤖 Prompt for AI Agents`.

## Fetch unresolved review threads (Gitea REST)

Gitea exposes review comments via REST:

```bash
# List all pull request reviews
curl -H "Authorization: token $GIT_TOKEN" \
  "$GITEA_URL/api/v1/repos/$OWNER/$REPO/pulls/$PR_NUMBER/reviews"

# List comments on a specific review
curl -H "Authorization: token $GIT_TOKEN" \
  "$GITEA_URL/api/v1/repos/$OWNER/$REPO/pulls/$PR_NUMBER/reviews/$REVIEW_ID/comments"

# List all issue/PR comments (includes top-level review comments)
curl -H "Authorization: token $GIT_TOKEN" \
  "$GITEA_URL/api/v1/repos/$OWNER/$REPO/issues/$PR_NUMBER/comments"
```

Filter comments by checking if `body` contains `<!-- ai-review-sha:` (AI reviewer comments) and `🤖 Prompt for AI Agents` (actionable fix blocks).

## Post a reaction (acknowledge a comment)

After applying a fix, post a thumbs-up reaction to the original comment:

```bash
# GitHub
gh api repos/$OWNER/$REPO/issues/comments/$COMMENT_ID/reactions \
  -X POST -f content="+1"

# Gitea
curl -X POST -H "Authorization: token $GIT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"content": "+1"}' \
  "$GITEA_URL/api/v1/repos/$OWNER/$REPO/issues/comments/$COMMENT_ID/reactions"
```

## Gateway API quick reference

```bash
# Trigger a review (CI / manual)
curl -X POST "$GATEWAY_URL/api/reviews/run" \
  -H "Authorization: Bearer $GATEWAY_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"project_id": "12345", "mr_id": 42, "force": false}'

# Get existing review result (parsed from comment)
curl "$GATEWAY_URL/api/reviews/result?project_id=12345&mr_id=42"

# Post a comment via gateway
curl -X POST "$GATEWAY_URL/api/reviews/comment" \
  -H "Authorization: Bearer $GATEWAY_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"project_id": "12345", "mr_id": 42, "body": "## Summary\n..."}'
```
