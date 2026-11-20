import json
import os

import boto3

TABLE_NAME = os.environ.get("TABLE_NAME", "orders")
RECEIPTS_BUCKET = os.environ.get("RECEIPTS_BUCKET", "receipts")


def receipt_url(order_id):
    return boto3.client("s3").generate_presigned_url(
        "get_object", Params={"Bucket": RECEIPTS_BUCKET, "Key": f"{order_id}.pdf"}, ExpiresIn=3600
    )


def lambda_handler(event, context):
    if event["httpMethod"] == "POST":
        order = json.loads(event.get("body") or "{}")
        boto3.resource("dynamodb").Table(TABLE_NAME).put_item(Item=order)
        return {"statusCode": 201, "body": json.dumps({"saved": order})}

    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps({
            "service": "orders",
            "stage": os.environ.get("STAGE"),
            "table": TABLE_NAME,
            "path": event["path"],
            "query": event["queryStringParameters"],
            "request_id": context.aws_request_id,
        }),
    }
