export const handler = async (event, context) => ({
  statusCode: 200,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({
    message: "Hello from a Node.js Lambda, running on OwnCloud",
    method: event.httpMethod,
    path: event.path,
    requestId: context.awsRequestId,
  }),
});
