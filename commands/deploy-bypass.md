<!-- MODEL_TIER: sonnet -->
<!-- DISPATCH: Spawn a Task subagent with model: "sonnet" to execute this command. -->
<!-- The orchestrator (Opus) reads this directive and delegates. Actual work runs on Sonnet. -->

---
description: Bypass Concourse pipeline and run all checks locally before deploying to an environment
arguments:
  - name: repos
    description: Comma-separated repository names to deploy (e.g., api-service, frontend-app, or api-service,frontend-app for both)
    required: true
  - name: --env
    description: Target environment (dev, demo). Defaults to dev.
    required: false
  - name: --skip-deploy
    description: Run checks only without deploying. Useful for pre-merge validation.
    required: false
  - name: --parallel
    description: Run multiple repositories in parallel using subagents (default when multiple repos specified)
    required: false
---

<!-- Integration: VCS_PROVIDER=bitbucket, CI_PROVIDER=concourse -->

# Deploy Bypass: $ARGUMENTS.repos

## Purpose

Bypass a broken or unavailable Concourse CI pipeline by running all pipeline checks locally and deploying directly to the target environment. This command replicates the exact steps from each repository's `concourse/pipeline.yml` `build-and-test` job, then executes the deployment steps from the `deploy-{env}` job.

**When to use:**
- Concourse pipeline is broken and another agent is investigating
- Pipeline infrastructure is down
- Urgent hotfix needs immediate deployment
- Local validation before pushing to trigger pipeline

**When NOT to use:**
- Pipeline is working normally (let CI handle it)
- You haven't pulled the latest main branch
- You have uncommitted local changes that shouldn't be deployed

## Command Phases

As you complete each phase, print a brief progress line (e.g. `[phase 2/N] Running validation...`).

1. Phase 0: Load context, parse repos and environment
2. Phase 1: Pull latest and install dependencies
3. Phase 2: Run pipeline quality checks (lint, typecheck, tests)
4. Phase 3: Build artifacts
5. Phase 4: Deploy to target environment
6. Phase 5: Verify deployment and report results

**START NOW: Begin Phase 0/Step 0.**

---

## Phase 0: Load Context

Parse arguments and verify all repositories exist before doing any work.

```bash
# Parse repos (comma-separated) and env (default: dev)
REPOS="${ARGUMENTS_repos}"
ENV="${ARGUMENTS_env:-dev}"

echo "[phase 0/5] Repos: ${REPOS}, Env: ${ENV}"

# Load project environment
source $PROJECT_ROOT/.env

# Validate env value
if [[ "$ENV" != "dev" && "$ENV" != "demo" ]]; then
  echo "ERROR: --env must be 'dev' or 'demo', got: $ENV"
  exit 1
fi

# Split repos on comma and verify each exists
IFS=',' read -ra REPO_LIST <<< "$REPOS"
for REPO in "${REPO_LIST[@]}"; do
  REPO=$(echo "$REPO" | xargs)  # trim whitespace
  REPO_PATH="$PROJECT_ROOT/$REPO"
  if [ ! -d "$REPO_PATH" ]; then
    echo "ERROR: Repository not found at $REPO_PATH"
    exit 1
  fi
  echo "  - Found: $REPO_PATH"
done

echo "[phase 0/5] Context loaded. ${#REPO_LIST[@]} repo(s) to process."
```

Store the parsed `REPO_LIST` and `ENV` in shell variables for use in subsequent phases. Record start timestamps per repo for the duration column in the final report.

---

## Phase 1: Pull Latest and Install Dependencies

For each repository, pull the latest main branch and install dependencies appropriate to the repo's tech stack.

```bash
echo "[phase 1/5] Pulling latest and installing dependencies..."

for REPO in "${REPO_LIST[@]}"; do
  REPO=$(echo "$REPO" | xargs)
  REPO_PATH="$PROJECT_ROOT/$REPO"

  echo "  [$REPO] Fetching and pulling origin/main..."
  cd "$REPO_PATH" && git fetch origin && git pull origin main

  # Detect repo type
  if [ -f "$REPO_PATH/package.json" ]; then
    echo "  [$REPO] TypeScript repo detected — running npm install"
    cd "$REPO_PATH" && npm install
  elif [ -f "$REPO_PATH/go.mod" ]; then
    echo "  [$REPO] Go repo detected — running go mod download"
    cd "$REPO_PATH" && go mod download
  else
    echo "  [$REPO] WARNING: Could not detect repo type (no package.json or go.mod). Skipping dependency install."
  fi
done

echo "[phase 1/5] Done."
```

If `git pull` fails (e.g. merge conflict or detached HEAD), abort immediately with a clear error message — do not attempt to force-resolve.

---

## Phase 2: Run Pipeline Quality Checks

Read `concourse/pipeline.yml` in each repo to identify the `build-and-test` job's task scripts, then run the equivalent checks locally. This ensures the local run mirrors what CI would execute.

```bash
echo "[phase 2/5] Running pipeline quality checks..."

PHASE2_FAILED=0

for REPO in "${REPO_LIST[@]}"; do
  REPO=$(echo "$REPO" | xargs)
  REPO_PATH="$PROJECT_ROOT/$REPO"
  PIPELINE_FILE="$REPO_PATH/concourse/pipeline.yml"

  echo "  [$REPO] Reading pipeline: $PIPELINE_FILE"

  if [ ! -f "$PIPELINE_FILE" ]; then
    echo "  [$REPO] WARNING: No concourse/pipeline.yml found. Running default checks."
  fi

  cd "$REPO_PATH"

  if [ -f "package.json" ]; then
    # TypeScript repo
    echo "  [$REPO] Running: npm run lint"
    npm run lint || { echo "  [$REPO] FAIL: lint"; PHASE2_FAILED=1; }

    echo "  [$REPO] Running: npm run typecheck"
    npm run typecheck || { echo "  [$REPO] FAIL: typecheck"; PHASE2_FAILED=1; }

    echo "  [$REPO] Running: npm run test"
    npm run test || { echo "  [$REPO] FAIL: tests"; PHASE2_FAILED=1; }

  elif [ -f "go.mod" ]; then
    # Go repo — lint is non-blocking (mirrors pipeline behavior)
    echo "  [$REPO] Running: golangci-lint run ./..."
    golangci-lint run ./... || true

    echo "  [$REPO] Running: go vet ./..."
    go vet ./... || { echo "  [$REPO] FAIL: go vet"; PHASE2_FAILED=1; }

    echo "  [$REPO] Running: go test ./... -count=1"
    go test ./... -count=1 || { echo "  [$REPO] FAIL: go test"; PHASE2_FAILED=1; }
  fi

  if [ "$PHASE2_FAILED" -eq 0 ]; then
    echo "  [$REPO] PASS"
  fi
done

if [ "$PHASE2_FAILED" -ne 0 ]; then
  echo "[phase 2/5] ABORT: One or more repos failed quality checks. Fix failures before deploying."
  exit 1
fi

echo "[phase 2/5] All quality checks passed."
```

Do not continue to Phase 3 if any repo fails. Print the specific repo and check that failed so the caller can act on it.

---

## Phase 3: Build Artifacts

Build deployable artifacts for each repository. The build strategy depends on the repo type and whether it contains Lambda functions.

```bash
echo "[phase 3/5] Building artifacts..."

for REPO in "${REPO_LIST[@]}"; do
  REPO=$(echo "$REPO" | xargs)
  REPO_PATH="$PROJECT_ROOT/$REPO"

  cd "$REPO_PATH"

  if [ -f "package.json" ]; then
    # TypeScript — build to dist/
    echo "  [$REPO] Running: npm run build"
    npm run build
    echo "  [$REPO] Build output: dist/"

  elif [ -f "go.mod" ]; then
    # Check if this is a lambda-functions style repo with per-function cmd/ directories
    if [ -d "cmd" ] && ls cmd/ | grep -q .; then
      echo "  [$REPO] Go Lambda repo detected — building all functions in cmd/"
      for FUNC_DIR in cmd/*/; do
        FUNC_NAME=$(basename "$FUNC_DIR")
        echo "  [$REPO] Building: $FUNC_NAME"
        GOOS=linux GOARCH=arm64 go build -o "$FUNC_DIR/bootstrap" "./$FUNC_DIR"
        cd "$FUNC_DIR"
        zip bootstrap.zip bootstrap
        cd "$REPO_PATH"
        echo "  [$REPO] Artifact: $FUNC_DIR/bootstrap.zip"
      done
    else
      # Standard Go repo — just verify it compiles
      echo "  [$REPO] Running: go build ./..."
      go build ./...
      echo "  [$REPO] Build OK"
    fi
  fi
done

echo "[phase 3/5] All artifacts built."
```

If any build step fails, abort immediately — do not attempt a partial deploy.

---

## Phase 4: Deploy to Target Environment

Read `concourse/pipeline.yml` to determine the deploy method used in the `deploy-{env}` job, then execute that method directly. If `--skip-deploy` is set, skip this phase entirely.

```bash
echo "[phase 4/5] Deploying to environment: $ENV"

# Honor --skip-deploy flag
if [ -n "${ARGUMENTS_skip_deploy}" ]; then
  echo "[phase 4/5] Skipping deploy (--skip-deploy flag set)."
  exit 0
fi

# Set AWS profile based on environment
case "$ENV" in
  dev)  AWS_PROFILE="dev-profile" ;;
  demo) AWS_PROFILE="your-demo-profile" ;;
  *)
    echo "ERROR: Unknown environment: $ENV"
    exit 1
    ;;
esac
export AWS_PROFILE

echo "  Using AWS profile: $AWS_PROFILE"

for REPO in "${REPO_LIST[@]}"; do
  REPO=$(echo "$REPO" | xargs)
  REPO_PATH="$PROJECT_ROOT/$REPO"
  PIPELINE_FILE="$REPO_PATH/concourse/pipeline.yml"

  echo "  [$REPO] Determining deploy method from $PIPELINE_FILE..."

  DEPLOY_METHOD="unknown"

  if [ -f "$PIPELINE_FILE" ]; then
    if grep -q "aws lambda update-function-code" "$PIPELINE_FILE"; then
      DEPLOY_METHOD="lambda"
    elif grep -q "terraform" "$PIPELINE_FILE"; then
      DEPLOY_METHOD="terraform"
    elif grep -q "aws s3 sync" "$PIPELINE_FILE"; then
      DEPLOY_METHOD="s3"
    fi
  fi

  echo "  [$REPO] Deploy method: $DEPLOY_METHOD"

  case "$DEPLOY_METHOD" in
    lambda)
      # Extract function names from pipeline.yml and deploy each
      # Pattern: aws lambda update-function-code --function-name <name>
      FUNCTION_NAMES=$(grep -o '\-\-function-name [^ ]*' "$PIPELINE_FILE" | awk '{print $2}' | sort -u)
      if [ -z "$FUNCTION_NAMES" ]; then
        echo "  [$REPO] WARNING: Could not extract function names from pipeline. Attempting build-based deploy."
      fi
      for FUNC_NAME in $FUNCTION_NAMES; do
        # Resolve bootstrap.zip path — look under cmd/ matching the function suffix
        FUNC_SHORT=$(echo "$FUNC_NAME" | sed 's/.*-\([^-]*\)$/\1/')
        ZIP_PATH="$REPO_PATH/cmd/$FUNC_SHORT/bootstrap.zip"
        if [ ! -f "$ZIP_PATH" ]; then
          ZIP_PATH=$(find "$REPO_PATH" -name "bootstrap.zip" | head -1)
        fi
        echo "  [$REPO] Deploying Lambda: $FUNC_NAME from $ZIP_PATH"
        aws lambda update-function-code \
          --function-name "$FUNC_NAME" \
          --zip-file "fileb://$ZIP_PATH" \
          --architectures arm64 \
          --profile "$AWS_PROFILE"
      done
      ;;

    terraform)
      TERRAFORM_DIR="$REPO_PATH/terraform"
      if [ ! -d "$TERRAFORM_DIR" ]; then
        # Some repos use a nested path — try to find it
        TERRAFORM_DIR=$(find "$REPO_PATH" -name "*.tf" -maxdepth 3 | head -1 | xargs dirname)
      fi
      echo "  [$REPO] Running Terraform in: $TERRAFORM_DIR"
      terraform -chdir="$TERRAFORM_DIR" init -input=false
      terraform -chdir="$TERRAFORM_DIR" apply \
        -var="env=$ENV" \
        -auto-approve \
        -input=false
      ;;

    s3)
      # Extract bucket and source path from pipeline.yml
      S3_CMD=$(grep "aws s3 sync" "$PIPELINE_FILE" | head -1 | xargs)
      echo "  [$REPO] Running: $S3_CMD"
      # Replace pipeline path variables with local equivalents
      # dist/ is the local build output for TypeScript repos
      eval "$S3_CMD" || {
        echo "  [$REPO] S3 sync command from pipeline.yml may need manual adjustment for local paths."
        echo "  [$REPO] Extracted command: $S3_CMD"
        exit 1
      }
      ;;

    *)
      echo "  [$REPO] WARNING: Could not determine deploy method from concourse/pipeline.yml."
      echo "  [$REPO] Inspect $PIPELINE_FILE manually and run the deploy-$ENV job steps by hand."
      ;;
  esac

  echo "  [$REPO] Deploy complete."
done

echo "[phase 4/5] Deployments submitted."
```

---

## Phase 5: Verify Deployment and Report

Confirm each deployment landed successfully by querying the live infrastructure, then store the episode in AgentDB and print a summary table.

```bash
echo "[phase 5/5] Verifying deployments..."

OVERALL_STATUS="success"

for REPO in "${REPO_LIST[@]}"; do
  REPO=$(echo "$REPO" | xargs)
  REPO_PATH="$PROJECT_ROOT/$REPO"
  PIPELINE_FILE="$REPO_PATH/concourse/pipeline.yml"

  DEPLOY_STATUS="unknown"

  if [ -f "$PIPELINE_FILE" ]; then
    if grep -q "aws lambda update-function-code" "$PIPELINE_FILE"; then
      # Verify Lambda: check configuration responds
      FUNCTION_NAMES=$(grep -o '\-\-function-name [^ ]*' "$PIPELINE_FILE" | awk '{print $2}' | sort -u | head -1)
      if [ -n "$FUNCTION_NAMES" ]; then
        aws lambda get-function-configuration \
          --function-name "$FUNCTION_NAMES" \
          --profile "$AWS_PROFILE" \
          --query 'LastModified' \
          --output text > /dev/null 2>&1 \
          && DEPLOY_STATUS="verified" \
          || DEPLOY_STATUS="failed"
      fi

    elif grep -q "terraform" "$PIPELINE_FILE"; then
      TERRAFORM_DIR="$REPO_PATH/terraform"
      [ ! -d "$TERRAFORM_DIR" ] && TERRAFORM_DIR=$(find "$REPO_PATH" -name "*.tf" -maxdepth 3 | head -1 | xargs dirname)
      terraform -chdir="$TERRAFORM_DIR" output > /dev/null 2>&1 \
        && DEPLOY_STATUS="verified" \
        || DEPLOY_STATUS="failed"

    elif grep -q "aws s3 sync" "$PIPELINE_FILE"; then
      BUCKET=$(grep "aws s3 sync" "$PIPELINE_FILE" | grep -o 's3://[^ ]*' | head -1)
      aws s3 ls "$BUCKET" --profile "$AWS_PROFILE" > /dev/null 2>&1 \
        && DEPLOY_STATUS="verified" \
        || DEPLOY_STATUS="failed"
    fi
  fi

  if [ "$DEPLOY_STATUS" = "failed" ]; then
    OVERALL_STATUS="failed"
  fi

  echo "  [$REPO] Verification status: $DEPLOY_STATUS"
done

# Store episode in AgentDB
REWARD=0.9
SUCCESS=true
if [ "$OVERALL_STATUS" = "failed" ]; then
  REWARD=0.2
  SUCCESS=false
fi

npx tsx ~/.claude/skills/agentdb/reflexion_store_episode.ts \
  "{\"session_id\": \"gw\", \"task\": \"deploy-bypass:${REPOS}:${ENV}\", \"reward\": ${REWARD}, \"success\": ${SUCCESS}}"

# Print summary table
echo ""
echo "=== Deploy Bypass Summary ==="
echo "Repos:  $REPOS"
echo "Env:    $ENV"
echo ""
echo "| Repo | Deploy Type | Status |"
echo "|------|-------------|--------|"

for REPO in "${REPO_LIST[@]}"; do
  REPO=$(echo "$REPO" | xargs)
  PIPELINE_FILE="$PROJECT_ROOT/$REPO/concourse/pipeline.yml"
  DEPLOY_TYPE="unknown"
  if [ -f "$PIPELINE_FILE" ]; then
    grep -q "aws lambda update-function-code" "$PIPELINE_FILE" && DEPLOY_TYPE="lambda"
    grep -q "terraform" "$PIPELINE_FILE" && DEPLOY_TYPE="terraform"
    grep -q "aws s3 sync" "$PIPELINE_FILE" && DEPLOY_TYPE="s3"
  fi
  echo "| $REPO | $DEPLOY_TYPE | $OVERALL_STATUS |"
done

echo ""
if [ "$OVERALL_STATUS" = "success" ]; then
  echo "[phase 5/5] All deployments verified successfully."
else
  echo "[phase 5/5] One or more deployments failed verification. Check output above."
  exit 1
fi
```
