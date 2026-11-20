// Client-side code with typical mistakes, for the OwnCloud code editor demo.
const results = document.getElementById("results");

document.getElementById("go").addEventListener("click", async () => {
  const q = document.getElementById("q").value;
  const response = await fetch("http://api.shop-example.eu/search?q=" + q);
  const data = await response.json();
  results.innerHTML = data.results.map((r) => `<li>${r[0]}</li>`).join("");
});

const requestId = Math.random().toString(36).slice(2);
console.log("request", requestId);
