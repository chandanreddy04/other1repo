/**
 * Cloudflare Worker — health check + automated failover trigger.
 *
 * Runs on Cloudflare's network (independent of the application's
 * cloud) via Cron Trigger every minute. Pings the primary health
 * endpoint and, after N consecutive failures, executes the full
 * failover sequence against the configured TARGET_CLOUD.
 *
 * Supported targets:
 *   - "aws"   (default): RDS PromoteReadReplica + ECS UpdateService
 *     SUPERSEDED — do not deploy with TARGET_CLOUD=aws. The AWS
 *     warm-standby stack (infra/aws/failover/) this mode operated on was
 *     removed in favor of backup-only DR (docs/dr-runbook-aws.md); the
 *     replica/service it would promote/scale do not exist.
 *
 * Env vars (set via `wrangler secret put` or wrangler.toml [vars]):
 *   TARGET_CLOUD              "aws"
 *   HEALTH_URL                URL of the primary's /health/ready
 *   APP_HOSTNAME              hostname of the DNS record being swapped
 *                             (defaults to URL(HEALTH_URL).hostname)
 *   DNS_API_TOKEN             Cloudflare API token (Zone:Edit)
 *   DNS_ZONE_ID               Cloudflare zone ID
 *   DNS_RECORD_ID             DNS record to repoint at failover
 *   SLACK_WEBHOOK_URL         (optional) Slack incoming-webhook URL
 *
 *   AWS-specific (when TARGET_CLOUD=aws):
 *     AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY
 *     AWS_RDS_REGION                 region of the failover RDS replica
 *     AWS_RDS_REPLICA_ID             DBInstanceIdentifier of the replica
 *     AWS_ECS_REGION                 region of the failover ECS service
 *     AWS_ECS_CLUSTER                cluster name
 *     AWS_ECS_SERVICE                service name
 *     AWS_ECS_DESIRED_COUNT          (optional) tasks to scale to; default 2
 *     AWS_FAILOVER_ALB_DNS           DNS to point Cloudflare CNAME at
 *
 * Required IAM policy for AWS_ACCESS_KEY_ID — attach to a dedicated IAM
 * user, NOT to anything broader. The policy must scope to specific ARNs
 * because these credentials live in Cloudflare and shouldn't be able to
 * do more than the failover sequence needs:
 *
 *   {
 *     "Version": "2012-10-17",
 *     "Statement": [
 *       {
 *         "Sid": "PromoteFailoverReplica",
 *         "Effect": "Allow",
 *         "Action": "rds:PromoteReadReplica",
 *         "Resource": "arn:aws:rds:<failover-region>:<account>:db:madeithome-db-<env>-failover"
 *       },
 *       {
 *         "Sid": "ScaleFailoverService",
 *         "Effect": "Allow",
 *         "Action": "ecs:UpdateService",
 *         "Resource": "arn:aws:ecs:<failover-region>:<account>:service/madeithome-cluster-<env>-failover/madeithome-web-<env>-failover"
 *       }
 *     ]
 *   }
 *
 * Rotate the access key quarterly.
 *
 * Prerequisites at runtime (aws mode — SUPERSEDED, see header note):
 *   - Failover stack (infra/aws/failover/, removed — recover from git
 *     history) applied
 *   - ACM cert in failover region validated (operator added CNAME to Cloudflare)
 *   - AWS_FAILOVER_ALB_DNS reachable + serving HTTPS
 */

const HEALTH_TIMEOUT_MS = 10_000;
const FAILURE_THRESHOLD = 3;

export default {
  async scheduled(event, env, ctx) {
    ctx.waitUntil(handleTick(env));
  },
};

async function handleTick(env) {
  const isActive = await env.FAILOVER_KV.get("failover_active");
  if (isActive === "true") {
    console.log("Failover already active — skipping tick");
    return;
  }

  const healthy = await checkHealth(env.HEALTH_URL);
  if (healthy) {
    await env.FAILOVER_KV.put("failures", "0");
    console.log("Health check passed");
    return;
  }

  const raw = await env.FAILOVER_KV.get("failures");
  const failures = (parseInt(raw || "0", 10) || 0) + 1;
  await env.FAILOVER_KV.put("failures", String(failures));
  console.log(`Health check failed — consecutive failures: ${failures}`);

  if (failures >= FAILURE_THRESHOLD) {
    await executeFailover(env);
  }
}

async function checkHealth(url) {
  try {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), HEALTH_TIMEOUT_MS);
    const resp = await fetch(url, { signal: controller.signal });
    clearTimeout(timeout);
    return resp.ok;
  } catch {
    return false;
  }
}

async function executeFailover(env) {
  const target = env.TARGET_CLOUD || "aws";
  const results = { target };
  try {
    if (target === "aws") {
      Object.assign(results, await failoverToAws(env));
    } else {
      throw new Error(`Unknown TARGET_CLOUD: ${target}`);
    }
    await updateDns(env, results);
    await env.FAILOVER_KV.put("failover_active", "true");
    results.lock = "ok";
  } catch (err) {
    results.error = err.message;
  }
  await notifySlack(env, results);
  console.log("Failover complete:", JSON.stringify(results));
}

// ---------------------------------------------------------------------------
// AWS failover — SigV4-signed calls to RDS and ECS
// ---------------------------------------------------------------------------

// Captures sub-step status into a plain object. NEVER throws — failures
// land in the result map so the orchestrator above doesn't lose context
// about which sub-steps got far enough to start.
async function failoverToAws(env) {
  const out = {};

  // 1. RDS PromoteReadReplica
  const rdsBody = new URLSearchParams({
    Action: "PromoteReadReplica",
    DBInstanceIdentifier: env.AWS_RDS_REPLICA_ID,
    Version: "2014-10-31",
  }).toString();
  const rdsResp = await awsRequest({
    region: env.AWS_RDS_REGION,
    service: "rds",
    method: "POST",
    path: "/",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: rdsBody,
    accessKeyId: env.AWS_ACCESS_KEY_ID,
    secretAccessKey: env.AWS_SECRET_ACCESS_KEY,
  });
  out.promote = rdsResp.ok ? "ok" : `failed:${rdsResp.status}`;

  // 2. ECS UpdateService — desiredCount config'd via env so staging and
  // production can scale to different baseline task counts on cutover.
  const desiredCount = parseInt(env.AWS_ECS_DESIRED_COUNT || "2", 10);
  const ecsBody = JSON.stringify({
    cluster: env.AWS_ECS_CLUSTER,
    service: env.AWS_ECS_SERVICE,
    desiredCount,
  });
  const ecsResp = await awsRequest({
    region: env.AWS_ECS_REGION,
    service: "ecs",
    method: "POST",
    path: "/",
    headers: {
      "Content-Type": "application/x-amz-json-1.1",
      "X-Amz-Target": "AmazonEC2ContainerServiceV20141113.UpdateService",
    },
    body: ecsBody,
    accessKeyId: env.AWS_ACCESS_KEY_ID,
    secretAccessKey: env.AWS_SECRET_ACCESS_KEY,
  });
  out.scale_ecs = ecsResp.ok ? "ok" : `failed:${ecsResp.status}`;
  return out;
}

// ---------------------------------------------------------------------------
// DNS swap (Cloudflare API)
// ---------------------------------------------------------------------------

async function updateDns(env, results) {
  if (!env.DNS_API_TOKEN || !env.DNS_ZONE_ID || !env.DNS_RECORD_ID) {
    results.dns = "skipped:missing_config";
    return;
  }
  // AWS uses a CNAME at the ALB DNS. APP_HOSTNAME defaults to the health
  // URL's hostname, but can be set separately if the health endpoint lives
  // on a different name.
  const hostname = env.APP_HOSTNAME || new URL(env.HEALTH_URL).hostname;
  const recordBody = {
    type: "CNAME",
    name: hostname,
    content: env.AWS_FAILOVER_ALB_DNS,
    ttl: 60,
    proxied: true,
  };
  const dnsResp = await fetch(
    `https://api.cloudflare.com/client/v4/zones/${env.DNS_ZONE_ID}/dns_records/${env.DNS_RECORD_ID}`,
    {
      method: "PUT",
      headers: {
        Authorization: `Bearer ${env.DNS_API_TOKEN}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify(recordBody),
    }
  );
  results.dns = dnsResp.ok ? "ok" : `failed:${dnsResp.status}`;
}

async function notifySlack(env, results) {
  if (!env.SLACK_WEBHOOK_URL) return;
  try {
    await fetch(env.SLACK_WEBHOOK_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        text: `🚨 *Made It Home Failover (${results.target})*\n\`\`\`${JSON.stringify(results, null, 2)}\`\`\``,
      }),
    });
  } catch {
    console.error("Failed to post to Slack");
  }
}

// ---------------------------------------------------------------------------
// SigV4 — AWS request signer using Web Crypto (no external libs)
// ---------------------------------------------------------------------------

async function awsRequest({
  region,
  service,
  method,
  path,
  headers,
  body,
  accessKeyId,
  secretAccessKey,
}) {
  const host = `${service}.${region}.amazonaws.com`;
  const url = `https://${host}${path}`;
  const now = new Date();
  const amzDate = now.toISOString().replace(/[:-]|\.\d{3}/g, ""); // YYYYMMDDTHHMMSSZ
  const dateStamp = amzDate.slice(0, 8); // YYYYMMDD

  // `Host` is included in the canonical headers + SignedHeaders per the
  // SigV4 spec. Cloudflare Workers' fetch() will set the outbound Host
  // from the URL, so the signature lines up against what AWS receives.
  const allHeaders = {
    ...headers,
    Host: host,
    "X-Amz-Date": amzDate,
  };
  // Lowercase keys + normalize values (trim + collapse internal whitespace)
  // per the SigV4 canonicalization rules. Without this, any future header
  // with leading whitespace or double-spaces would silently break signing.
  const normalized = Object.fromEntries(
    Object.entries(allHeaders).map(([k, v]) => [
      k.toLowerCase(),
      String(v).trim().replace(/\s+/g, " "),
    ])
  );
  const sortedHeaderNames = Object.keys(normalized).sort();
  const canonicalHeaders = sortedHeaderNames
    .map((h) => `${h}:${normalized[h]}\n`)
    .join("");
  const signedHeaders = sortedHeaderNames.join(";");
  const payloadHash = await sha256Hex(body || "");

  const canonicalRequest = [
    method,
    path,
    "", // query string (none)
    canonicalHeaders,
    signedHeaders,
    payloadHash,
  ].join("\n");

  const credentialScope = `${dateStamp}/${region}/${service}/aws4_request`;
  const stringToSign = [
    "AWS4-HMAC-SHA256",
    amzDate,
    credentialScope,
    await sha256Hex(canonicalRequest),
  ].join("\n");

  const kDate = await hmac(`AWS4${secretAccessKey}`, dateStamp);
  const kRegion = await hmac(kDate, region);
  const kService = await hmac(kRegion, service);
  const kSigning = await hmac(kService, "aws4_request");
  const signature = toHex(await hmac(kSigning, stringToSign));

  const authorization = `AWS4-HMAC-SHA256 Credential=${accessKeyId}/${credentialScope}, SignedHeaders=${signedHeaders}, Signature=${signature}`;

  return fetch(url, {
    method,
    headers: { ...allHeaders, Authorization: authorization },
    body,
  });
}

async function sha256Hex(s) {
  const data = typeof s === "string" ? new TextEncoder().encode(s) : s;
  const buf = await crypto.subtle.digest("SHA-256", data);
  return toHex(new Uint8Array(buf));
}

async function hmac(key, msg) {
  const keyBytes = typeof key === "string" ? new TextEncoder().encode(key) : key;
  const msgBytes = typeof msg === "string" ? new TextEncoder().encode(msg) : msg;
  const cryptoKey = await crypto.subtle.importKey(
    "raw",
    keyBytes,
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"]
  );
  const sig = await crypto.subtle.sign("HMAC", cryptoKey, msgBytes);
  return new Uint8Array(sig);
}

function toHex(bytes) {
  return Array.from(bytes)
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}
