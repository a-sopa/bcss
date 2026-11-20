import os

import boto3
from flask import Flask

application = Flask(__name__)
STORE_NAME = os.environ.get("STORE_NAME", "Shop")


def queue_order(order):
    boto3.client("sqs").send_message(QueueUrl=os.environ["ORDERS_QUEUE_URL"], MessageBody=order)


@application.route("/")
def home():
    return f"<h1>{STORE_NAME}</h1><p>An Elastic Beanstalk app, now running on OwnCloud.</p>"
