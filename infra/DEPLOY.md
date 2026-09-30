# Deploying Plenty (handoff notes)

Everything runs locally with no AWS account (`AGENT_MODE=mock`). These steps switch on the real AWS services one at a time. Each switch is a single environment variable, and each has a local fallback, so you can deploy the app first and turn services on as access comes through.

Region: `me-central-1` (UAE). No real keys live in this repo; `.env.example` holds dummy values only.

## 1. Create the supporting resources

```bash
aws cloudformation deploy \
  --region me-central-1 \
  --stack-name plenty-demo \
  --template-file infra/template.yaml \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides Stage=demo AlertEmail=you@example.com   # AlertEmail is optional

aws cloudformation describe-stacks --region me-central-1 --stack-name plenty-demo \
  --query "Stacks[0].Outputs" --output table
```

This creates:

| Resource | Name | Used for | Env var |
| --- | --- | --- | --- |
| DynamoDB table (pk/sk, on-demand) | `plenty-demo` | rescues, offers, jobs, impact | `DDB_TABLE` |
| SNS topic | `plenty-demo-notifications` | copy of every message sent | `SNS_TOPIC_ARN` |
| S3 bucket (private, 7-day expiry) | `plenty-demo-photos-<account>` | surplus photos | `PHOTO_BUCKET` |
| IAM role + instance profile | `plenty-demo-app` | what the app runs as | none |

The role allows Bedrock `InvokeModel`/`InvokeModelWithResponseStream` (this covers the Converse API), Amazon Location `geo-routes:CalculateRoutes`, and read/write on only the table, topic and bucket above.

## 2. Turn on Bedrock model access

In the Bedrock console for `me-central-1`, open **Model access** and enable the Anthropic Claude model you want. Then set `BEDROCK_MODEL_ID` to the inference profile ID shown there. The default, `global.anthropic.claude-sonnet-4-6`, is a global cross-Region inference profile; confirm the exact ID in your account, because the IDs available differ per account and Region.

Check it from the machine that will run the app:

```bash
aws bedrock-runtime converse --region me-central-1 \
  --model-id global.anthropic.claude-sonnet-4-6 \
  --messages '[{"role":"user","content":[{"text":"Say hi"}]}]'
```

If Bedrock fails before the agent has made its first tool call, the app falls back to the mock planner and says so in the ops trace (`BEDROCK_FALLBACK=true`). Set it to `false` once you trust the setup.

## 3. Run the app

The app is one container. **Run exactly one instance with one worker**: the live event stream that feeds the phone screens lives in process memory.

### Option A: EC2 (simplest for a demo)

1. Launch a small instance (t3.small is plenty) in `me-central-1` with the `plenty-demo-app` instance profile. Open port 80 (or 8000) in the security group.
2. On the instance:

```bash
sudo dnf install -y docker git && sudo systemctl start docker
git clone https://github.com/abponcio/Pentli.git && cd Pentli
cp .env.example .env    # then edit .env: see step 4
sudo docker build -t plenty .
sudo docker run -d --restart unless-stopped -p 80:8000 --env-file .env plenty
```

No access keys are needed on EC2: boto3 picks up the instance profile.

### Option B: App Runner or ECS Fargate

Build and push the image to ECR, then create the service with the `plenty-demo-app` role as the **instance role** (App Runner) or **task role** (ECS), port 8000, health check path `/api/health`, and the environment variables from step 4. Keep it to one instance (App Runner: an auto scaling configuration with max size 1; ECS: desired count 1).

## 4. Environment for the deployed app

```bash
AGENT_MODE=bedrock
AWS_REGION=me-central-1
BEDROCK_REGION=me-central-1
BEDROCK_MODEL_ID=<inference profile ID from step 2>
STORE=dynamodb
DDB_TABLE=plenty-demo
ROUTING=location
NOTIFY=sns
SNS_TOPIC_ARN=<TopicArn output>
PHOTO_BUCKET=<PhotoBucketName output>
DEMO_CLOCK=19:40
PUBLIC_BASE_URL=https://<your public address>   # used by the judge QR code
```

Turn them on one at a time if anything misbehaves; each service can be switched back to its local fallback on its own (`STORE=memory`, `ROUTING=haversine`, `NOTIFY=inapp`, empty `PHOTO_BUCKET`, `AGENT_MODE=mock`).

## 5. Check it

```bash
curl https://<host>/api/health     # {"ok":true}
curl https://<host>/api/config     # shows agent mode, model, store, routing
```

Then open `https://<host>/ops` on the big screen and `https://<host>/kitchen` on a phone, and send "50 chicken biryani, has cashews, cooked at 6". The ops header shows which services are live.

Phone notifications and the microphone need HTTPS. On EC2, put the instance behind an ALB with an ACM certificate, or use App Runner, which gives you HTTPS by default.

## 6. Tear down

```bash
aws cloudformation delete-stack --region me-central-1 --stack-name plenty-demo
```

Empty the photo bucket first if the delete fails on it.
