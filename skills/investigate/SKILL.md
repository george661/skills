---
name: "CloudWatch Alarm Investigation"
description: "Investigate AWS CloudWatch alarms by analyzing metrics, logs, and correlating events to determine root cause. Use when receiving alarm notifications, troubleshooting production issues, or investigating AWS infrastructure problems. Automatically creates Jira bugs for code issues found."
---

# CloudWatch Alarm Investigation Skill

## What This Skill Does

This skill provides a structured approach to investigating CloudWatch alarms:

1. **Retrieves alarm configuration** - Gets alarm details, thresholds, and evaluation settings
2. **Analyzes state history** - Reviews when alarm triggered and any state transitions
3. **Queries related metrics** - Collects correlated metrics from the same service
4. **Searches CloudWatch Logs** - Finds error messages, stack traces, and request context
5. **Correlates evidence** - Builds timeline and identifies patterns
6. **Determines root cause** - Classifies as bug, infrastructure, external, or expected
7. **Creates Jira issue** - Automatically files bugs with evidence attached

## Prerequisites

- AWS CLI configured with valid credentials
- IAM permissions:
  - `cloudwatch:DescribeAlarms`
  - `cloudwatch:DescribeAlarmHistory`
  - `cloudwatch:GetMetricData`
  - `logs:DescribeLogGroups`
  - `logs:StartQuery`
  - `logs:GetQueryResults`
- Jira MCP configured (for automatic bug creation)
- AgentDB MCP configured (for memory storage)

## Quick Start

```bash
# Basic investigation (defaults to 1 hour time range, us-east-1)
/investigate api-service-error-rate-high

# Specify region
/investigate api-service-error-rate-high --region us-west-2

# Extended time range
/investigate api-service-error-rate-high --timerange 6h

# Using full ARN
/investigate arn:aws:cloudwatch:us-east-1:123456789:alarm:api-service-error-rate-high
```

---

## Investigation Flow

```
┌─────────────────────────────────────────────────────────────┐
│                    CloudWatch Alarm                         │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  Phase 0: Verify AWS Access                                 │
│  - Validate credentials                                     │
│  - Parse alarm identifier                                   │
│  - Set time range                                           │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  Phase 1: Get Alarm Details                                 │
│  - Describe alarm configuration                             │
│  - Get state history                                        │
│  - Identify trigger time                                    │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  Phase 2: Query Metrics                                     │
│  - Get alarmed metric data                                  │
│  - Query related metrics (errors, latency, etc.)            │
│  - Analyze patterns                                         │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  Phase 3: Search Logs                                       │
│  - Identify relevant log groups                             │
│  - Query for errors and exceptions                          │
│  - Extract stack traces                                     │
│  - Find request context                                     │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  Phase 4: Analyze Root Cause                                │
│  - Correlate metrics and logs                               │
│  - Build timeline                                           │
│  - Form hypothesis with confidence                          │
│  - Classify: bug | infrastructure | external | expected     │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
              ┌───────────────┴───────────────┐
              │                               │
              ▼                               ▼
┌─────────────────────────┐     ┌─────────────────────────┐
│  Bug Identified         │     │  Not a Bug              │
│  - Create Jira issue    │     │  - Document findings    │
│  - Attach evidence      │     │  - Suggest alarm tuning │
│  - Link to alarm        │     │  - Record pattern       │
└─────────────────────────┘     └─────────────────────────┘
              │                               │
              └───────────────┬───────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  Phase 6: Store & Report                                    │
│  - Store findings in AgentDB                                │
│  - Record pattern for learning                              │
│  - Generate summary report                                  │
└─────────────────────────────────────────────────────────────┘
```

---

## Root Cause Classifications

| Classification | Description | Action |
|----------------|-------------|--------|
| **bug** | Code issue causing errors | Create Jira bug, link to alarm |
| **infrastructure** | Config, capacity, or resource issue | Document remediation steps |
| **external** | 3rd party or network issue | Document dependency failure |
| **expected** | Known limitation or false positive | Suggest alarm tuning |

---

## Platform Service Mapping

| Alarm Namespace | the project Service | Primary Log Group | Repository |
|-----------------|------------|-------------------|------------|
| AWS/Lambda | Lambda functions | /aws/lambda/{fn} | api-service |
| AWS/ApiGateway | API Gateway | /aws/api-gateway/{api} | api-service |
| AWS/ECS | ECS tasks | /ecs/{service} | agents |
| AWS/CloudFront | CDN distribution | /aws/cloudfront/{dist} | frontend-app |
| AWS/Cognito | Auth pool | /aws/cognito/{pool} | auth-service |
| AWS/RDS | Database | /aws/rds/{db} | api-service |
| AWS/SQS | Message queues | N/A (metrics only) | api-service |

---

## Common Alarm Patterns

### Error Rate Spike
**Indicators:**
- Sudden increase in error metric
- Corresponding log errors with stack traces
- Often correlates with deployment

**Investigation Focus:**
- Recent deployments or config changes
- Stack traces in logs
- Dependency failures

### Latency Degradation
**Indicators:**
- P99/P95 latency exceeds threshold
- May not have errors
- Often affects specific endpoints

**Investigation Focus:**
- Database query times
- External API latency
- Cold start issues (Lambda)

### Throttling
**Indicators:**
- Throttle metric non-zero
- Concurrent execution limits
- May show 429 errors

**Investigation Focus:**
- Traffic patterns
- Concurrency limits
- Scaling configuration

### Resource Exhaustion
**Indicators:**
- Memory/CPU utilization high
- Timeout errors
- OOM kills in logs

**Investigation Focus:**
- Memory leaks
- Inefficient algorithms
- Resource allocation

---

## AWS CLI Commands Reference

### Describe Alarm
```bash
aws cloudwatch describe-alarms \
  --alarm-names "alarm-name" \
  --region us-east-1
```

### Get Alarm History
```bash
aws cloudwatch describe-alarm-history \
  --alarm-name "alarm-name" \
  --history-item-type StateUpdate \
  --start-date "2024-01-01T00:00:00Z" \
  --end-date "2024-01-02T00:00:00Z"
```

### Query Metrics
```bash
aws cloudwatch get-metric-data \
  --metric-data-queries '[{
    "Id": "m1",
    "MetricStat": {
      "Metric": {
        "Namespace": "AWS/Lambda",
        "MetricName": "Errors",
        "Dimensions": [{"Name": "FunctionName", "Value": "my-function"}]
      },
      "Period": 60,
      "Stat": "Sum"
    }
  }]' \
  --start-time "2024-01-01T00:00:00Z" \
  --end-time "2024-01-01T01:00:00Z"
```

### CloudWatch Logs Insights
```bash
aws logs start-query \
  --log-group-name "/aws/lambda/my-function" \
  --start-time 1704067200000 \
  --end-time 1704070800000 \
  --query-string 'fields @timestamp, @message
    | filter @message like /error/i
    | sort @timestamp desc
    | limit 100'
```

---

## Troubleshooting

### Alarm Not Found
**Cause:** Incorrect alarm name or region
**Solution:**
```bash
# List all alarms to find correct name
aws cloudwatch describe-alarms --region us-east-1 | jq '.MetricAlarms[].AlarmName'
```

### No Logs Found
**Cause:** Log group doesn't exist or wrong pattern
**Solution:**
```bash
# List available log groups
aws logs describe-log-groups --region us-east-1 | jq '.logGroups[].logGroupName'
```

### Insufficient Permissions
**Cause:** IAM policy missing required actions
**Solution:** Ensure role has CloudWatch and Logs read permissions

### Query Timeout
**Cause:** Time range too large or too many logs
**Solution:** Reduce time range or add more specific filters

---

## Integration with the platform Workflows

After investigation completes:

1. **If bug created:** Use `/work PROJ-XXX` to implement fix
2. **If infrastructure issue:** Document remediation and apply manually
3. **If false positive:** Consider updating alarm configuration

The investigation findings are stored in AgentDB memory for future reference and pattern learning.

---

## See Also

- [/fix-pipeline](../commands/fix-pipeline.md) - Fix CI/CD pipeline failures
- [/audit](../commands/audit.md) - UI compliance testing
- [/bug](../commands/bug.md) - Manual bug creation with evidence
