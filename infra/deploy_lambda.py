"""Package the app and deploy it as one AWS Lambda function with a public HTTPS function URL.

Used on the hackathon account, which has no EC2, ECS or App Runner. Create infra/workshop.yaml first
(stack name below), then run with AWS credentials in the environment:

    python infra/deploy_lambda.py            # build, upload, create or update, print the URL

The app runs unchanged under the AWS Lambda Web Adapter; live updates stream over the function URL.
"""
import io
import os
import secrets
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

import boto3

ROOT = Path(__file__).resolve().parent.parent
STAGE = os.environ.get("STAGE", "demo")
STACK = f"plentli-{STAGE}"
FUNCTION = f"plentli-{STAGE}"
REGION = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "us-west-2"
MODEL_ID = os.environ.get("BEDROCK_MODEL_ID", "us.anthropic.claude-sonnet-4-6")
ADAPTER_LAYER = f"arn:aws:lambda:{REGION}:753240598075:layer:LambdaAdapterLayerX86:27"
BUILD = Path(os.environ.get("BUILD_DIR", "/tmp/plentli-lambda"))

RUN_SH = """#!/bin/bash
exec python3 -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
"""


def build() -> bytes:
    if BUILD.exists():
        shutil.rmtree(BUILD)
    BUILD.mkdir(parents=True)
    reqs = [line for line in (ROOT / "requirements.txt").read_text().splitlines() if line and not line.startswith("boto3")]
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", "--target", str(BUILD), "--platform", "manylinux2014_x86_64",
                    "--implementation", "cp", "--python-version", "3.11", "--only-binary=:all:", *reqs], check=True)
    for folder in ("app", "data", "web"):
        shutil.copytree(ROOT / folder, BUILD / folder, ignore=shutil.ignore_patterns("__pycache__"))
    (BUILD / "run.sh").write_text(RUN_SH)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for path in BUILD.rglob("*"):
            if path.is_file() and "__pycache__" not in path.parts:
                info = zipfile.ZipInfo(str(path.relative_to(BUILD)))
                info.external_attr = (0o755 if path.name == "run.sh" else 0o644) << 16
                info.compress_type = zipfile.ZIP_DEFLATED
                z.writestr(info, path.read_bytes())
    return buf.getvalue()


def main() -> None:
    outputs = {o["OutputKey"]: o["OutputValue"] for o in
               boto3.client("cloudformation", region_name=REGION).describe_stacks(StackName=STACK)["Stacks"][0]["Outputs"]}
    lam = boto3.client("lambda", region_name=REGION)
    s3 = boto3.client("s3", region_name=REGION)

    code = build()
    key = f"deploy/{FUNCTION}-{int(time.time())}.zip"
    s3.put_object(Bucket=outputs["PhotoBucketName"], Key=key, Body=code)
    print(f"Uploaded {len(code) / 1e6:.1f} MB")

    try:
        existing = lam.get_function_configuration(FunctionName=FUNCTION)
        token = existing["Environment"]["Variables"].get("TASK_TOKEN") or secrets.token_urlsafe(24)
    except lam.exceptions.ResourceNotFoundException:
        existing, token = None, secrets.token_urlsafe(24)

    env = {
        "AWS_LAMBDA_EXEC_WRAPPER": "/opt/bootstrap", "AWS_LWA_INVOKE_MODE": "response_stream", "PORT": "8000",
        "AWS_LWA_READINESS_CHECK_PATH": "/api/health", "AWS_LWA_PASS_THROUGH_PATH": "/events",
        "AGENT_MODE": "bedrock", "BEDROCK_REGION": REGION, "BEDROCK_MODEL_ID": MODEL_ID,
        "STORE": "dynamodb", "DDB_TABLE": outputs["TableName"], "ROUTING": "location",
        "NOTIFY": "sns", "SNS_TOPIC_ARN": outputs["TopicArn"], "PHOTO_BUCKET": outputs["PhotoBucketName"],
        "DEMO_CLOCK": os.environ.get("DEMO_CLOCK", "19:40"), "TASK_TOKEN": token,
    }
    settings = dict(FunctionName=FUNCTION, Role=outputs["AppRoleArn"], Handler="run.sh", Runtime="python3.11",
                    Timeout=900, MemorySize=1024, Layers=[ADAPTER_LAYER], Environment={"Variables": env})
    if existing:
        lam.update_function_code(FunctionName=FUNCTION, S3Bucket=outputs["PhotoBucketName"], S3Key=key)
        lam.get_waiter("function_updated_v2").wait(FunctionName=FUNCTION)
        lam.update_function_configuration(**{k: v for k, v in settings.items() if k != "FunctionName"}, FunctionName=FUNCTION)
    else:
        lam.create_function(**settings, Code={"S3Bucket": outputs["PhotoBucketName"], "S3Key": key}, Architectures=["x86_64"])
    lam.get_waiter("function_updated_v2" if existing else "function_active_v2").wait(FunctionName=FUNCTION)
    # A failed background agent run should not be retried: the screens have already moved on.
    lam.put_function_event_invoke_config(FunctionName=FUNCTION, MaximumRetryAttempts=0)

    try:
        url = lam.get_function_url_config(FunctionName=FUNCTION)["FunctionUrl"]
    except lam.exceptions.ResourceNotFoundException:
        url = lam.create_function_url_config(FunctionName=FUNCTION, AuthType="NONE", InvokeMode="RESPONSE_STREAM")["FunctionUrl"]
        for action, sid in (("lambda:InvokeFunctionUrl", "public-url"), ("lambda:InvokeFunction", "public-url-invoke")):
            extra = {"FunctionUrlAuthType": "NONE"} if action == "lambda:InvokeFunctionUrl" else {"InvokedViaFunctionUrl": True}
            try:
                lam.add_permission(FunctionName=FUNCTION, StatementId=sid, Action=action, Principal="*", **extra)
            except lam.exceptions.ResourceConflictException:
                pass
    print("PLENTLI_URL", url)


if __name__ == "__main__":
    main()
