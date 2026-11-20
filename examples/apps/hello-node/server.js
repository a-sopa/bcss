const http = require("node:http");

const port = Number(process.env.PORT || 8080);
http
  .createServer((_req, res) => {
    res.writeHead(200, { "Content-Type": "text/html; charset=utf-8" });
    res.end("<h1>Hello from Node on OwnCloud</h1>");
  })
  .listen(port, () => console.log(`listening on ${port}`));
